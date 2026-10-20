"""D04 deterministic execution. All transport calls occur outside PostgreSQL transactions."""

import json
from datetime import datetime, timedelta
from uuid import uuid4

from alap.application.experiments import digest, new_id, require
from alap.application.ports import Authenticator, GatewayPort
from alap.domain.lifecycle import Authority, Effect, Kind
from alap.domain.rules import DomainError, freeze_revision
from alap.domain.stability import check_stable

TABLE = {Kind.RUN: "runs", Kind.TASK: "tasks", Kind.COMMAND: "command_ledger", Kind.LEASE: "leases"}
COMMAND_TERMINAL = {"SUCCEEDED", "FAILED_CONFIRMED", "REJECTED_BEFORE_EXECUTE", "CANCELLED"}


class ExecutionService:
    def __init__(
        self, foundation, *, authenticator: Authenticator, gateways: dict[str, GatewayPort]
    ):
        self.base = foundation
        self.transaction = foundation.transaction
        self.auth, self.gateways = authenticator, gateways

    def _engine(self, repo, actor):
        principal = self.base._principal(repo, actor)
        require(
            principal["kind"] == "service" and principal["issuer"] == "alap-engine",
            "FORBIDDEN",
            "Explicitly provisioned engine principal required",
        )

    def _locked(self, repo, actor, run_id, *, authorize=True, active=True):
        self._engine(repo, actor)
        initial = repo.get("runs", run_id)
        if authorize:
            self.base._principal(repo, initial["created_by"])
        generation = repo.generation()
        require(
            not active or generation["mode"] == "ACTIVE",
            "RECOVERY_REQUIRED",
            "Control generation blocked",
        )
        initial = repo.get("runs", run_id)
        experiment = repo.get("experiments", initial["experiment_id"], lock=True)
        approval = repo.get("approvals", initial["approval_id"], lock=True)
        plan = repo.get("plan_revisions", initial["plan_revision_id"])
        controls = [
            repo.get("resource_controls", r, lock=True)
            for r in sorted(plan["plan_json"]["proposal"]["requested_resources"])
        ]
        leases = repo.find("leases", {"holder_run_id": run_id}, lock=True)
        run = repo.get("runs", run_id, lock=True)
        tasks = repo.find("tasks", {"run_id": run_id}, lock=True)
        commands = repo.find("command_ledger", {"run_id": run_id}, lock=True)
        if authorize:
            self.base._current(repo, experiment, plan)
            self.base._approval_integrity(approval, plan)
            # Revoked/disabled starter membership cannot be silently replaced by service privilege.
            self.base._access(repo, run["created_by"], experiment, "write", plan["plan_json"])
            require(
                approval["state"] == "APPROVED" and repo.now() < approval["expires_at"],
                "APPROVAL_INVALID",
                "Approval absent, expired or revoked",
            )
        return {
            "generation": generation,
            "experiment": experiment,
            "approval": approval,
            "plan": plan,
            "controls": controls,
            "leases": leases,
            "run": run,
            "tasks": tasks,
            "commands": commands,
        }

    def _change(
        self, repo, ctx, row, kind, event, actor, facts, *, authority=Authority.ENGINE, updates=None
    ):
        decision = self.base._decision(
            repo, ctx["experiment"], row, kind, event, actor, authority, repo.now(), facts
        )
        values = {"state": decision.current.state, "state_version": decision.current.version}
        values.update(updates or {})
        repo.update(TABLE[kind], row["id"], values)
        if Effect.FREEZE_DISPATCH in decision.effects:
            repo.update("runs", ctx["run"]["id"], {"dispatch_blocked": True})
            ctx["run"]["dispatch_blocked"] = True
        if Effect.QUARANTINE_RESOURCES in decision.effects:
            for control in ctx["controls"]:
                repo.update(
                    "resource_controls", control["id"], {"quarantined": True, "reason": event}
                )
                control["quarantined"] = True
        if Effect.ENABLE_DISPATCH in decision.effects:
            repo.update("runs", ctx["run"]["id"], {"dispatch_blocked": False})
            ctx["run"]["dispatch_blocked"] = False
        if Effect.REQUEST_SAFE_STOP in decision.effects:
            for command in ctx["commands"]:
                if command["state"] in COMMAND_TERMINAL | {"NOT_DISPATCHED"}:
                    continue
                if not repo.find("stop_requests", {"command_id": command["id"]}):
                    repo.insert(
                        "stop_requests",
                        {
                            "id": new_id(),
                            "command_id": command["id"],
                            "actor_id": actor,
                            "reason": event,
                            "state": "PENDING",
                            "dedup_key": "stop:" + command["id"],
                        },
                    )
        self.base._event(
            repo,
            ctx["experiment"],
            kind=str(kind),
            identity=row["id"],
            event=event,
            actor=actor,
            old_version=row["state_version"],
            new_version=decision.current.version,
            from_state=row["state"],
            to_state=decision.current.state,
            evidence_ids=decision.evidence_ids,
            effects=decision.effects,
            now=decision.decided_at,
        )
        row.update(values)
        return decision

    def _creation(self, repo, ctx, kind, row, actor):
        self.base._event(
            repo,
            ctx["experiment"],
            kind=kind,
            identity=row["id"],
            event="created",
            actor=actor,
            to_state=row["state"],
        )

    def _lease_facts(self, repo, ctx):
        valid = {}
        now = repo.now()
        for control in ctx["controls"]:
            claim = repo.claim(control["id"])
            lease = next(
                (
                    lease_item
                    for lease_item in ctx["leases"]
                    if claim and lease_item["id"] == claim["lease_id"]
                ),
                None,
            )
            require(
                lease
                and lease["state"] == "ACTIVE"
                and now < lease["expires_at"]
                and not control["quarantined"]
                and lease["epoch"] == ctx["generation"]["epoch"]
                and control["epoch"] == ctx["generation"]["epoch"]
                and lease["token"] == control["last_fencing_token"],
                "LEASE_INVALID",
                "Resource lease is expired, quarantined or not current",
            )
            instrument = repo.get("instruments", control["id"])
            require(
                instrument["policy_version"]
                == ctx["plan"]["plan_json"]["policy_versions"][control["id"]]
                and instrument["capability_version"]
                == ctx["plan"]["plan_json"]["capability_versions"][control["id"]],
                "POLICY_MISMATCH",
                "Registered device versions differ from approval",
            )
            gateway = repo.get("gateways", instrument["gateway_id"])
            require(
                gateway["epoch"] == ctx["generation"]["epoch"],
                "GATEWAY_NOT_READY",
                "Gateway not reconciled",
            )
            valid[control["id"]] = lease
        return valid

    def acquire(self, actor, run_id, *, duration_s=60):
        require(0 < duration_s <= 300, "INVALID_LEASE", "Finite lease duration required")
        with self.transaction() as repo:
            ctx = self._locked(repo, actor, run_id)
            run = ctx["run"]
            require(
                run["state"] in ("READY", "WAITING_RESOURCE", "PAUSED"),
                "RUN_NOT_READY",
                "Cannot acquire for active run",
            )
            existing = [repo.claim(c["id"]) for c in ctx["controls"]]
            if existing and all(c and c["holder_run_id"] == run_id for c in existing):
                self._lease_facts(repo, ctx)
                return [c["lease_id"] for c in existing]
            busy = any(
                c["quarantined"] or str(c["epoch"]) != str(ctx["generation"]["epoch"])
                for c in ctx["controls"]
            ) or any(existing)
            if busy:
                if run["state"] == "READY":
                    self._change(
                        repo,
                        ctx,
                        run,
                        Kind.RUN,
                        "resources_unavailable",
                        actor,
                        {"resources_busy": {"resources": [c["id"] for c in ctx["controls"]]}},
                    )
                return []
            # Every resource is checked before creating any lease or claim.
            expires = min(repo.now() + timedelta(seconds=duration_s), ctx["approval"]["expires_at"])
            for control in ctx["controls"]:
                token = control["last_fencing_token"] + 1
                instrument = repo.get("instruments", control["id"])
                gateway = repo.get("gateways", instrument["gateway_id"])
                require(
                    gateway["epoch"] == ctx["generation"]["epoch"],
                    "GATEWAY_NOT_READY",
                    "Handshake required before allocation",
                )
                binding = digest(
                    {
                        "resource": control["id"],
                        "run": run_id,
                        "epoch": str(ctx["generation"]["epoch"]),
                        "token": token,
                        "plan_hash": run["plan_hash"],
                    }
                )
                lease = {
                    "id": new_id(),
                    "resource_id": control["id"],
                    "holder_run_id": run_id,
                    "epoch": ctx["generation"]["epoch"],
                    "token": token,
                    "expires_at": expires,
                    "scope_hash": run["plan_hash"],
                    "binding_hash": binding,
                    "state": "ACTIVE",
                    "state_version": 0,
                }
                repo.insert("leases", lease)
                repo.add_claim(lease)
                repo.update("resource_controls", control["id"], {"last_fencing_token": token})
                control["last_fencing_token"] = token
                ctx["leases"].append(lease)
                self._creation(repo, ctx, "lease", lease, actor)
            if run["state"] == "WAITING_RESOURCE":
                self._change(
                    repo,
                    ctx,
                    run,
                    Kind.RUN,
                    "resources_acquired",
                    actor,
                    {
                        "lease_valid": {
                            "leases": [lease_item["id"] for lease_item in ctx["leases"]]
                        },
                        "authorization_valid": {"approval": ctx["approval"]["id"]},
                    },
                )
            return [
                lease_item["id"] for lease_item in ctx["leases"] if lease_item["state"] == "ACTIVE"
            ]

    def materialize(self, actor, run_id):
        with self.transaction() as repo:
            ctx = self._locked(repo, actor, run_id)
            if ctx["tasks"]:
                return [t["id"] for t in ctx["tasks"]]
            require(
                ctx["run"]["state"] in ("READY", "WAITING_RESOURCE"),
                "RUN_NOT_READY",
                "Run must be unstarted",
            )
            definitions = {t["id"]: t for t in ctx["plan"]["plan_json"]["proposal"]["tasks"]}
            identities = {t["plan_task_id"]: t for t in ctx["run"]["task_identities"]}
            for identity in identities.values():
                task = {
                    "id": identity["id"],
                    "experiment_id": ctx["experiment"]["id"],
                    "run_id": run_id,
                    "plan_task_id": identity["plan_task_id"],
                    "attempt_no": identity["attempt_no"],
                    "state": "PENDING",
                    "state_version": 0,
                    "binding_hash": ctx["run"]["plan_hash"],
                    "definition": definitions[identity["plan_task_id"]],
                }
                repo.insert("tasks", task)
                self._creation(repo, ctx, "task", task, actor)
            for identity in identities.values():
                for parent in definitions[identity["plan_task_id"]]["depends_on"]:
                    repo.dependency(run_id, identity["id"], identities[parent]["id"])
            return [t["id"] for t in identities.values()]

    def _readbacks(self, task):
        # Group windows per gateway so sampling one sensor does not age another sensor out.
        groups = {}
        with self.transaction() as repo:
            for condition in task["preconditions"]:
                require(
                    condition["kind"] == "stable_window",
                    "CONDITION_UNSUPPORTED",
                    "D04 supports stable windows",
                )
                gateway = repo.get("instruments", condition["resource_id"])["gateway_id"]
                groups.setdefault(gateway, []).append(condition)
        values = []
        for gateway, conditions in groups.items():
            observed = self.auth.open(self.gateways[gateway].telemetry({"conditions": conditions}))
            require(
                observed["gateway_id"] == gateway
                and [w["condition"] for w in observed["windows"]] == conditions,
                "WRONG_GATEWAY",
                "Readback identity or condition differs",
            )
            values.extend(
                (w["condition"], {"gateway_id": gateway, "samples": w["samples"]})
                for w in observed["windows"]
            )
        return values

    def _fresh(self, repo, readbacks):
        now = repo.now()
        for condition, observed in readbacks:
            check_stable(condition, observed["samples"], now)
        return {"samples": [o for _, o in readbacks]}

    def prepare(self, actor, run_id, plan_task_id):
        with self.transaction() as repo:
            self._engine(repo, actor)
            initial = repo.get("runs", run_id)
            plan = repo.get("plan_revisions", initial["plan_revision_id"])
            task = next(
                t for t in plan["plan_json"]["proposal"]["tasks"] if t["id"] == plan_task_id
            )
        readbacks = self._readbacks(task)
        with self.transaction() as repo:
            ctx = self._locked(repo, actor, run_id)
            leases = self._lease_facts(repo, ctx)
            row = next(t for t in ctx["tasks"] if t["plan_task_id"] == plan_task_id)
            previous = next((c for c in ctx["commands"] if c["task_id"] == row["id"]), None)
            if previous and previous["state"] != "NOT_DISPATCHED":
                return previous["id"]
            require(
                ctx["run"]["state"] in ("READY", "RUNNING"),
                "DISPATCH_BLOCKED",
                "Run cannot dispatch",
            )
            if ctx["run"]["state"] == "RUNNING":
                require(not ctx["run"]["dispatch_blocked"], "DISPATCH_BLOCKED", "Run is frozen")
            by_name = {t["plan_task_id"]: t for t in ctx["tasks"]}
            require(
                all(by_name[p]["state"] == "SUCCEEDED" for p in task["depends_on"]),
                "DEPENDENCIES_PENDING",
                "All dependencies must have verified success",
            )
            fresh = self._fresh(repo, readbacks)
            facts = {
                "authorization_valid": {"approval": ctx["approval"]["id"]},
                "lease_valid": {"leases": [lease_item["id"] for lease_item in leases.values()]},
                "preconditions_fresh": fresh,
                "run_dispatch_allowed": {"run_id": run_id},
            }
            if ctx["run"]["state"] == "READY":
                repo.update("runs", run_id, {"dispatch_blocked": False})
                ctx["run"]["dispatch_blocked"] = False
                self._change(repo, ctx, ctx["run"], Kind.RUN, "start", actor, facts)
            if previous:
                return previous["id"]
            if row["state"] == "PENDING":
                self._change(
                    repo,
                    ctx,
                    row,
                    Kind.TASK,
                    "dependencies_succeeded",
                    actor,
                    {"dependencies_succeeded": {"parents": task["depends_on"]}},
                )
            require(row["state"] == "READY", "TASK_NOT_READY", "Task cannot be retried or reopened")
            lease = leases[task["resource_id"]]
            now = repo.now()
            skill, version = task["skill_ref"].rsplit("@", 1)
            command = {
                "schema_version": "2.0",
                "command_id": new_id(),
                "experiment_id": ctx["experiment"]["id"],
                "run_id": run_id,
                "task_id": row["id"],
                "instrument_id": task["resource_id"],
                "lease_id": lease["id"],
                "fencing_token": lease["token"],
                "policy_version": ctx["plan"]["plan_json"]["policy_versions"][task["resource_id"]],
                "capability_version": ctx["plan"]["plan_json"]["capability_versions"][
                    task["resource_id"]
                ],
                "skill_id": skill,
                "skill_version": version,
                "parameters": task["parameters"],
                "deadline_at": min(
                    now + timedelta(seconds=task["timeout_s"]),
                    *(lease_item["expires_at"] for lease_item in leases.values()),
                ).isoformat(),
                "issued_at": now.isoformat(),
                "authorized_plan_hash": ctx["run"]["plan_hash"],
                "control_epoch": str(ctx["generation"]["epoch"]),
            }
            self.base.catalog.validate_command(command)
            frozen = freeze_revision(command)
            command_row = {
                "id": command["command_id"],
                "experiment_id": ctx["experiment"]["id"],
                "run_id": run_id,
                "task_id": row["id"],
                "attempt_no": row["attempt_no"],
                "payload_bytes": frozen.canonical_bytes,
                "payload_hash": frozen.plan_hash,
                "binding_hash": frozen.plan_hash,
                "instrument_id": task["resource_id"],
                "lease_id": lease["id"],
                "epoch": lease["epoch"],
                "token": lease["token"],
                "state": "NOT_DISPATCHED",
                "state_version": 0,
            }
            repo.insert("command_ledger", command_row)
            repo.insert("command_deliveries", {"id": command_row["id"], "status": "PENDING"})
            self._creation(repo, ctx, "command", command_row, actor)
            return command_row["id"]

    def dispatch(self, actor, command_id, *, crash_after_commit=False):
        with self.transaction() as repo:
            self._engine(repo, actor)
            initial = repo.get("command_ledger", command_id)
            task = repo.get("tasks", initial["task_id"])["definition"]
        readbacks = self._readbacks(task)
        with self.transaction() as repo:
            ctx = self._locked(repo, actor, initial["run_id"])
            leases = self._lease_facts(repo, ctx)
            command = next(c for c in ctx["commands"] if c["id"] == command_id)
            require(
                command["state"] == "NOT_DISPATCHED",
                "ALREADY_DISPATCHED",
                "Never retry attempted delivery",
            )
            require(
                not ctx["run"]["dispatch_blocked"] and ctx["run"]["state"] == "RUNNING",
                "DISPATCH_BLOCKED",
                "Run gate is closed",
            )
            envelope = json.loads(bytes(command["payload_bytes"]))
            require(
                repo.now() < datetime.fromisoformat(envelope["deadline_at"]),
                "DEADLINE_EXPIRED",
                "Prepared command expired",
            )
            fresh = self._fresh(repo, readbacks)
            facts = {
                "authorization_valid": {"approval": ctx["approval"]["id"]},
                "lease_valid": {"leases": [lease_item["id"] for lease_item in leases.values()]},
                "preconditions_fresh": fresh,
                "run_dispatch_allowed": {"run": ctx["run"]["id"]},
            }
            row = next(t for t in ctx["tasks"] if t["id"] == command["task_id"])
            self._change(
                repo,
                ctx,
                command,
                Kind.COMMAND,
                "dispatch",
                actor,
                {**facts, "journal_prepared": {"command_id": command_id}},
            )
            self._change(
                repo,
                ctx,
                row,
                Kind.TASK,
                "dispatch",
                actor,
                {**facts, "command_prepared": {"command_id": command_id}},
            )
            repo.update(
                "command_deliveries",
                command_id,
                {
                    "status": "ATTEMPTED",
                    "claimed_by": actor,
                    "claimed_until": repo.now(),
                    "delivery_attempt_id": new_id(),
                },
            )
            gateway_id = repo.get("instruments", command["instrument_id"])["gateway_id"]
            signed = self.auth.seal({"command": envelope, "task": row["definition"]})
        if crash_after_commit:
            raise ConnectionError("injected crash after DISPATCHED commit, before send")
        try:
            receipt = self.gateways[gateway_id].accept(signed)
            self.ingest(actor, command_id, receipt)
        except ConnectionError, TimeoutError, DomainError:
            self.mark_unknown(actor, command_id)
            raise
        return receipt

    def mark_unknown(self, actor, command_id):
        with self.transaction() as repo:
            self._engine(repo, actor)
            initial = repo.get("command_ledger", command_id)
            ctx = self._locked(repo, actor, initial["run_id"], authorize=False, active=False)
            command = next(c for c in ctx["commands"] if c["id"] == command_id)
            if command["state"] in COMMAND_TERMINAL | {"UNKNOWN", "NEEDS_RECONCILIATION"}:
                return
            require(
                command["state"] != "NOT_DISPATCHED", "NOT_SENT", "Unsent command is not uncertain"
            )
            facts = {
                "outcome_uncertain": {
                    "command_id": command_id,
                    "reason": "delivery/result uncertain",
                }
            }
            self._change(repo, ctx, command, Kind.COMMAND, "uncertain", actor, facts)
            task = next(t for t in ctx["tasks"] if t["id"] == command["task_id"])
            self._change(repo, ctx, task, Kind.TASK, "uncertain", actor, facts)
            if ctx["run"]["state"] not in ("UNKNOWN", "NEEDS_RECONCILIATION"):
                self._change(repo, ctx, ctx["run"], Kind.RUN, "uncertain", actor, facts)

    def ingest(self, actor, command_id, signed, *, reconcile=False):
        receipt = self.auth.open(signed)
        current_readbacks = []
        if reconcile and receipt["state"] in ("SUCCEEDED", "VERIFYING"):
            with self.transaction() as repo:
                self._engine(repo, actor)
                initial = repo.get("command_ledger", command_id)
                task = repo.get("tasks", initial["task_id"])["definition"]
            conditions = (
                [task["success_condition"]]
                if task["success_condition"]["kind"] == "stable_window"
                else task["preconditions"]
            )
            current_readbacks = self._readbacks({"preconditions": conditions})
        with self.transaction() as repo:
            self._engine(repo, actor)
            initial = repo.get("command_ledger", command_id)
            ctx = self._locked(repo, actor, initial["run_id"], authorize=False, active=False)
            command = next(c for c in ctx["commands"] if c["id"] == command_id)
            instrument = repo.get("instruments", command["instrument_id"])
            require(
                receipt["gateway_id"] == instrument["gateway_id"]
                and receipt["command_id"] == command_id
                and receipt["payload_hash"] == command["payload_hash"]
                and receipt["epoch"] == str(command["epoch"]),
                "RECEIPT_MISMATCH",
                "Receipt identity, epoch or bytes differ",
            )
            identity = f"{receipt['gateway_id']}:{receipt['epoch']}:{receipt['receipt_seq']}"
            existing = repo.find(
                "gateway_receipts",
                {
                    "gateway_id": receipt["gateway_id"],
                    "epoch": command["epoch"],
                    "receipt_seq": receipt["receipt_seq"],
                },
            )
            if existing:
                require(
                    existing[0]["raw_receipt"] == signed, "RECEIPT_CONFLICT", "Receipt ID reused"
                )
                return
            repo.insert(
                "gateway_receipts",
                {
                    "id": identity,
                    "gateway_id": receipt["gateway_id"],
                    "epoch": command["epoch"],
                    "receipt_seq": receipt["receipt_seq"],
                    "command_id": command_id,
                    "payload_hash": command["payload_hash"],
                    "raw_receipt": signed,
                    "received_at": repo.now(),
                },
            )
            if command["state"] in COMMAND_TERMINAL:
                if receipt["state"] in COMMAND_TERMINAL and receipt["state"] != command["state"]:
                    repo.update("runs", ctx["run"]["id"], {"dispatch_blocked": True})
                    for control in ctx["controls"]:
                        repo.update(
                            "resource_controls",
                            control["id"],
                            {"quarantined": True, "reason": "conflicting_terminal_receipt"},
                        )
                    self.base._event(
                        repo,
                        ctx["experiment"],
                        kind="incident",
                        identity=identity,
                        event="receipt_conflict",
                        actor=actor,
                        to_state="OPEN",
                        evidence_ids=(),
                        effects=["freeze_dispatch", "quarantine_resources"],
                    )
                return  # Retain terminal history; contradictions become separate incidents.
            task = next(t for t in ctx["tasks"] if t["id"] == command["task_id"])
            if command["state"] in ("UNKNOWN", "NEEDS_RECONCILIATION"):
                require(
                    reconcile,
                    "RECONCILIATION_REQUIRED",
                    "Unknown outcomes require explicit reconciliation",
                )
                require(
                    receipt["state"] in ("SUCCEEDED", "VERIFYING", "REJECTED_BEFORE_EXECUTE"),
                    "RECONCILIATION_PENDING",
                    "No verified durable result",
                )
                for row, kind in [
                    (command, Kind.COMMAND),
                    (task, Kind.TASK),
                    (ctx["run"], Kind.RUN),
                ]:
                    if row["state"] == "UNKNOWN":
                        self._change(
                            repo,
                            ctx,
                            row,
                            kind,
                            "begin_reconciliation",
                            actor,
                            {"dispatch_disabled": {"run": ctx["run"]["id"]}},
                            authority=Authority.RECONCILER,
                        )
                if receipt["state"] == "REJECTED_BEFORE_EXECUTE":
                    require(
                        receipt["result"].get("never_executed") is True,
                        "RECONCILIATION_PENDING",
                        "Authenticated nonexecution evidence required",
                    )
                    self._change(
                        repo,
                        ctx,
                        command,
                        Kind.COMMAND,
                        "reconciled_not_executed",
                        actor,
                        {
                            "reconciliation_complete": {"receipt": identity},
                            "never_executed": {"receipt": identity},
                        },
                        authority=Authority.RECONCILER,
                    )
                    self._change(
                        repo,
                        ctx,
                        task,
                        Kind.TASK,
                        "reconciled_failure",
                        actor,
                        {
                            "reconciliation_complete": {"receipt": identity},
                            "command_failed": {"command": command_id},
                            "device_quiescent": {"receipt": identity},
                        },
                        authority=Authority.RECONCILER,
                    )
                    if all(c["state"] in COMMAND_TERMINAL for c in ctx["commands"]):
                        self._change(
                            repo,
                            ctx,
                            ctx["run"],
                            Kind.RUN,
                            "reconciled_pause",
                            actor,
                            {
                                "reconciliation_complete": {"receipt": identity},
                                "children_quiescent": {"receipt": identity},
                            },
                            authority=Authority.RECONCILER,
                        )
                    return
                current_evidence = self._fresh(repo, current_readbacks)
                self._change(
                    repo,
                    ctx,
                    command,
                    Kind.COMMAND,
                    "reconciled_success",
                    actor,
                    {
                        "reconciliation_complete": {
                            "receipt": identity,
                            "readback": current_evidence,
                        },
                        "execution_finished": {"receipt": identity},
                    },
                    authority=Authority.RECONCILER,
                )
            else:
                gateway_fact = {"gateway_authenticated": {"gateway": receipt["gateway_id"]}}
                if receipt["state"] == "ACCEPTED":
                    if command["state"] == "DISPATCHED":
                        self._change(
                            repo,
                            ctx,
                            command,
                            Kind.COMMAND,
                            "accepted",
                            actor,
                            {**gateway_fact, "journal_accepted": {"receipt": identity}},
                            authority=Authority.GATEWAY,
                        )
                    return
                if receipt["state"] in ("RUNNING", "VERIFYING", "SUCCEEDED"):
                    if command["state"] in ("DISPATCHED", "ACCEPTED"):
                        self._change(
                            repo,
                            ctx,
                            command,
                            Kind.COMMAND,
                            "execution_started",
                            actor,
                            {**gateway_fact, "journal_running": {"receipt": identity}},
                            authority=Authority.GATEWAY,
                        )
                    if task["state"] == "DISPATCHED":
                        self._change(
                            repo,
                            ctx,
                            task,
                            Kind.TASK,
                            "execution_started",
                            actor,
                            {"command_running": {"command": command_id}},
                        )
                if receipt["state"] == "RUNNING":
                    return
                if receipt["state"] not in ("SUCCEEDED", "VERIFYING"):
                    return
                if command["state"] != "VERIFYING":
                    self._change(
                        repo,
                        ctx,
                        command,
                        Kind.COMMAND,
                        "execution_finished",
                        actor,
                        {**gateway_fact, "execution_finished": {"receipt": identity}},
                        authority=Authority.GATEWAY,
                    )
            if receipt["state"] == "VERIFYING":
                return  # IV data is local only; Dataset COMMITTED is explicitly D05.
            if task["definition"]["success_condition"]["kind"] == "stable_window":
                observed = datetime.fromisoformat(receipt["observed_at"])
                require(observed <= repo.now(), "INVALID_RECEIPT_TIME", "Future receipt rejected")
                check_stable(
                    task["definition"]["success_condition"], receipt["result"]["samples"], observed
                )
                dataset_evidence = {
                    "skill_ref": task["definition"]["skill_ref"],
                    "reason": "stable_window skill has no dataset",
                }
            else:
                datasets = repo.find("datasets", {"command_id": command_id}, lock=True)
                proof = receipt["result"].get("dataset", {})
                require(
                    len(datasets) == 1
                    and datasets[0]["state"] == "COMMITTED"
                    and proof.get("dataset_id") == datasets[0]["id"]
                    and proof.get("checksum_sha256") == datasets[0]["checksum"],
                    "DATASET_NOT_COMMITTED",
                    "Verified committed acquisition required",
                )
                original = self.auth.open(
                    repo.get("gateway_receipts", datasets[0]["receipt_id"])["raw_receipt"]
                )
                require(
                    receipt["result"]["artifact"] == original["result"]["artifact"],
                    "DATA_SOURCE_MISMATCH",
                    "Completion result differs from stored acquisition",
                )
                dataset_evidence = {
                    "dataset_id": datasets[0]["id"],
                    "sha256": datasets[0]["checksum"],
                }
            self._change(
                repo,
                ctx,
                command,
                Kind.COMMAND,
                "complete",
                actor,
                {
                    "gateway_authenticated": {"gateway": receipt["gateway_id"]},
                    "success_verified": {"receipt": identity},
                    "result_durable": {"receipt": identity},
                    "datasets_committed": dataset_evidence,
                },
                authority=Authority.GATEWAY,
            )
            event = (
                "reconciled_success"
                if task["state"] == "NEEDS_RECONCILIATION"
                else "execution_finished"
            )
            facts = {"command_succeeded": {"command": command_id}}
            if reconcile:
                facts["reconciliation_complete"] = {"receipt": identity}
            self._change(
                repo,
                ctx,
                task,
                Kind.TASK,
                event,
                actor,
                facts,
                authority=Authority.RECONCILER if reconcile else Authority.ENGINE,
            )
            self._change(
                repo,
                ctx,
                task,
                Kind.TASK,
                "complete",
                actor,
                {
                    "command_succeeded": {"command": command_id},
                    "success_verified": {"receipt": identity},
                    "datasets_committed": dataset_evidence,
                },
            )
            self._settle_run(repo, ctx, actor)

    def _settle_run(self, repo, ctx, actor):
        run = ctx["run"]
        if not self._stops_confirmed(repo, ctx):
            return
        terminal = all(c["state"] in COMMAND_TERMINAL for c in ctx["commands"])
        succeeded = len(ctx["tasks"]) == len(run["task_identities"]) and all(
            t["state"] == "SUCCEEDED" for t in ctx["tasks"]
        )
        tasks_done = all(
            t["state"] in ("SUCCEEDED", "FAILED", "CANCELLED", "SKIPPED") for t in ctx["tasks"]
        )
        facts = {"children_quiescent": {"commands": [c["id"] for c in ctx["commands"]]}}
        cancelled = any(
            repo.find("stop_requests", {"command_id": c["id"]}) for c in ctx["commands"]
        )
        if terminal and tasks_done and succeeded:
            datasets = repo.find("datasets", {"run_id": run["id"]}, lock=True)
            required = {
                t["id"]
                for t in ctx["tasks"]
                if t["definition"]["success_condition"]["kind"] == "dataset_committed"
            }
            require(
                required <= {d["task_id"] for d in datasets if d["state"] == "COMMITTED"},
                "DATASET_NOT_COMMITTED",
                "All required datasets must remain committed",
            )
            complete = {
                **facts,
                "all_tasks_succeeded": {"tasks": [t["id"] for t in ctx["tasks"]]},
                "datasets_committed": {
                    "datasets": [d["id"] for d in datasets],
                    "non_data_skills": [
                        t["definition"]["skill_ref"]
                        for t in ctx["tasks"]
                        if t["id"] not in required
                    ],
                },
            }
            if run["state"] in ("PAUSE_REQUESTED", "CANCEL_REQUESTED"):
                self._change(repo, ctx, run, Kind.RUN, "completion_won_race", actor, complete)
            elif run["state"] == "RUNNING":
                self._change(
                    repo,
                    ctx,
                    run,
                    Kind.RUN,
                    "tasks_succeeded",
                    actor,
                    {k: v for k, v in complete.items() if k != "datasets_committed"},
                )
                self._change(repo, ctx, run, Kind.RUN, "complete", actor, complete)
            elif run["state"] == "NEEDS_RECONCILIATION" and cancelled:
                self._change(
                    repo,
                    ctx,
                    run,
                    Kind.RUN,
                    "reconciled_success",
                    actor,
                    {
                        **facts,
                        "all_tasks_succeeded": complete["all_tasks_succeeded"],
                        "reconciliation_complete": {"stops": "confirmed"},
                    },
                    authority=Authority.RECONCILER,
                )
                self._change(repo, ctx, run, Kind.RUN, "complete", actor, complete)
            elif run["state"] == "NEEDS_RECONCILIATION":
                self._change(
                    repo,
                    ctx,
                    run,
                    Kind.RUN,
                    "reconciled_pause",
                    actor,
                    {**facts, "reconciliation_complete": {"commands": "confirmed"}},
                    authority=Authority.RECONCILER,
                )
            repo.update("runs", run["id"], {"dispatch_blocked": True})
        elif terminal and tasks_done and run["state"] == "CANCEL_REQUESTED":
            self._change(
                repo,
                ctx,
                run,
                Kind.RUN,
                "cancel_confirmed",
                actor,
                {**facts, "cancellation_complete": {"tasks": "confirmed"}},
            )
        elif terminal and run["state"] == "NEEDS_RECONCILIATION":
            event = "reconciled_cancel" if cancelled and tasks_done else "reconciled_pause"
            evidence = {**facts, "reconciliation_complete": {"commands": "confirmed"}}
            if event == "reconciled_cancel":
                evidence["cancellation_complete"] = {"tasks": "confirmed"}
            self._change(
                repo, ctx, run, Kind.RUN, event, actor, evidence, authority=Authority.RECONCILER
            )
        elif run["state"] == "PAUSE_REQUESTED" and all(
            c["state"] in COMMAND_TERMINAL | {"NOT_DISPATCHED"} for c in ctx["commands"]
        ):
            self._change(
                repo,
                ctx,
                run,
                Kind.RUN,
                "pause_confirmed",
                actor,
                {**facts, "dispatch_disabled": {"run": run["id"]}},
            )

    def reconcile(self, actor, command_id, *, recover_gateway=False):
        with self.transaction() as repo:
            self._engine(repo, actor)
            command = repo.get("command_ledger", command_id)
            gateway = repo.get("instruments", command["instrument_id"])["gateway_id"]
        # Query only. Never fall back to accept/resend if the journal is absent.
        if recover_gateway:
            receipt = self.gateways[gateway].recover_command(
                self.auth.seal(
                    {"operation": "reconcile", "gateway_id": gateway, "command_id": command_id}
                )
            )
        else:
            receipt = self.gateways[gateway].query(command_id)
        self.ingest(actor, command_id, receipt, reconcile=True)

    def expire_leases(self, actor, run_id):
        with self.transaction() as repo:
            ctx = self._locked(repo, actor, run_id, authorize=False, active=False)
            count = 0
            for lease in ctx["leases"]:
                if (
                    lease["state"] in ("ACTIVE", "RELEASE_PENDING")
                    and repo.now() >= lease["expires_at"]
                ):
                    self._change(
                        repo,
                        ctx,
                        lease,
                        Kind.LEASE,
                        "expire",
                        actor,
                        {"expiry_reached": {"expires_at": lease["expires_at"].isoformat()}},
                        authority=Authority.TIMER,
                    )
                    count += 1
            # Claims are intentionally retained until authenticated quiescence reconciliation.
            return count

    def _gateway_reports(self, resources):
        reports = {}
        with self.transaction() as repo:
            gateway_ids = {repo.get("instruments", r)["gateway_id"] for r in resources}
        for gateway_id in gateway_ids:
            report = self.auth.open(self.gateways[gateway_id].challenge())
            require(report["gateway_id"] == gateway_id, "WRONG_GATEWAY", "Gateway report mismatch")
            require(
                all(c["state"] in COMMAND_TERMINAL for c in report["states"]),
                "RECONCILIATION_PENDING",
                "Gateway has unresolved commands",
            )
            reports[gateway_id] = report
        return reports

    def release(self, actor, run_id):
        with self.transaction() as repo:
            self._engine(repo, actor)
            initial = repo.get("runs", run_id)
            resources = repo.get("plan_revisions", initial["plan_revision_id"])["plan_json"][
                "proposal"
            ]["requested_resources"]
        reports = self._gateway_reports(resources)
        with self.transaction() as repo:
            ctx = self._locked(repo, actor, run_id, authorize=False, active=False)
            require(self._stops_confirmed(repo, ctx), "STOP_PENDING", "Stop confirmations required")
            require(ctx["run"]["dispatch_blocked"], "DISPATCH_ENABLED", "Freeze run before release")
            require(
                all(c["state"] in COMMAND_TERMINAL for c in ctx["commands"]),
                "RECONCILIATION_PENDING",
                "Every command must have a confirmed outcome",
            )
            for report in reports.values():
                age = (repo.now() - datetime.fromisoformat(report["observed_at"])).total_seconds()
                require(
                    0 <= age <= 2 and report["epoch"] == str(ctx["generation"]["epoch"]),
                    "STALE_REPORT",
                    "Fresh current-epoch gateway report required",
                )
            for lease in ctx["leases"]:
                claim = repo.claim(lease["resource_id"])
                if not claim or claim["lease_id"] != lease["id"]:
                    continue
                if lease["state"] == "ACTIVE":
                    self._change(
                        repo,
                        ctx,
                        lease,
                        Kind.LEASE,
                        "request_release",
                        actor,
                        {"dispatch_disabled": {"run": run_id}},
                    )
                if lease["state"] == "RELEASE_PENDING":
                    self._change(
                        repo,
                        ctx,
                        lease,
                        Kind.LEASE,
                        "release",
                        actor,
                        {
                            "device_quiescent": {"reports": reports},
                            "no_inflight_commands": {
                                "commands": [c["id"] for c in ctx["commands"]]
                            },
                        },
                    )
                require(
                    lease["state"] in ("RELEASED", "EXPIRED", "REVOKED"),
                    "LEASE_ACTIVE",
                    "Lease still owns resource",
                )
                repo.remove_claim(lease)
                repo.update(
                    "resource_controls",
                    lease["resource_id"],
                    {
                        "quarantined": False,
                        "reason": "reconciled_release",
                        "reconciliation_ref": new_id(),
                    },
                )

    def begin_recovery(self, actor):
        with self.transaction() as repo:
            self._engine(repo, actor)
            generation = repo.generation(exclusive=True)
            if generation["mode"] == "RECOVERING":
                return str(generation["epoch"])
            # Exclusive generation barrier serializes with every application writer.
            experiments = repo.find("experiments", {}, lock=True)
            repo.find("approvals", {}, lock=True)
            controls = repo.find("resource_controls", {}, lock=True)
            repo.find("leases", {}, lock=True)
            runs = repo.find("runs", {}, lock=True)
            epoch = str(uuid4())
            repo.update(
                "control_generation",
                "current",
                {"mode": "RECOVERING", "epoch": epoch, "version": generation["version"] + 1},
            )
            for control in controls:
                repo.update(
                    "resource_controls",
                    control["id"],
                    {"quarantined": True, "reason": "epoch_recovery"},
                )
            for run in runs:
                repo.update("runs", run["id"], {"dispatch_blocked": True})
            # Recovery barrier is global; each affected experiment gets a durable fact event.
            for experiment in experiments:
                self.base._event(
                    repo,
                    experiment,
                    kind="control",
                    identity=epoch + ":" + experiment["id"],
                    event="recovery_started",
                    actor=actor,
                    to_state="RECOVERING",
                )
            return epoch

    def _stops_confirmed(self, repo, ctx):
        return all(
            s["state"] == "CONFIRMED"
            for c in ctx["commands"]
            for s in repo.find("stop_requests", {"command_id": c["id"]})
        )

    def bind_gateway(self, actor, gateway_id):
        with self.transaction() as repo:
            self._engine(repo, actor)
            generation = repo.generation()
            require(
                generation["mode"] == "RECOVERING",
                "RECOVERY_REQUIRED",
                "Handshake only in recovery",
            )
            require(
                all(s["state"] == "CONFIRMED" for s in repo.find("stop_requests", {})),
                "STOP_PENDING",
                "Confirm outstanding stops before changing gateway epoch",
            )
            repo.get("gateways", gateway_id)
            epoch = str(generation["epoch"])
        challenge = self.auth.open(self.gateways[gateway_id].challenge())
        require(
            challenge["gateway_id"] == gateway_id, "WRONG_GATEWAY", "Challenge identity mismatch"
        )
        signed = self.auth.seal(
            {
                "operation": "bind_epoch",
                "gateway_id": gateway_id,
                "epoch": epoch,
                "nonce": challenge["nonce"],
            }
        )
        response = self.auth.open(self.gateways[gateway_id].bind_epoch(signed))
        require(
            response["gateway_id"] == gateway_id
            and response["epoch"] == epoch
            and response["nonce"] == challenge["nonce"]
            and response["quiescent"],
            "HANDSHAKE_INVALID",
            "Gateway recovery confirmation mismatch",
        )
        with self.transaction() as repo:
            self._engine(repo, actor)
            generation = repo.generation()
            require(
                str(generation["epoch"]) == epoch and generation["mode"] == "RECOVERING",
                "STALE_RECOVERY",
                "Recovery generation changed during handshake",
            )
            repo.update(
                "gateways", gateway_id, {"epoch": epoch, "reconciliation_ref": response["nonce"]}
            )
        return response

    def finish_recovery(self, actor):
        with self.transaction() as repo:
            self._engine(repo, actor)
            generation = repo.generation(exclusive=True)
            require(generation["mode"] == "RECOVERING", "NOT_RECOVERING", "Recovery not active")
            gateways = repo.find("gateways", {})
            require(
                gateways and all(g["epoch"] == generation["epoch"] for g in gateways),
                "GATEWAY_OFFLINE",
                "Every registered gateway must complete the new handshake",
            )
            experiments = repo.find("experiments", {}, lock=True)
            repo.find("approvals", {}, lock=True)
            controls = repo.find("resource_controls", {}, lock=True)
            leases = repo.find("leases", {}, lock=True)
            runs = repo.find("runs", {}, lock=True)
            commands = repo.find("command_ledger", {})
            require(
                all(c["state"] in COMMAND_TERMINAL for c in commands),
                "RECONCILIATION_PENDING",
                "All previous commands must be reconciled first",
            )
            require(
                all(s["state"] == "CONFIRMED" for s in repo.find("stop_requests", {})),
                "STOP_PENDING",
                "All stops must be confirmed before recovery completes",
            )
            by_experiment = {e["id"]: e for e in experiments}
            for run in runs:
                ctx = {
                    "run": run,
                    "experiment": by_experiment[run["experiment_id"]],
                    "controls": controls,
                }
                if run["state"] in ("RUNNING", "VERIFYING"):
                    self._change(
                        repo,
                        ctx,
                        run,
                        Kind.RUN,
                        "pause",
                        actor,
                        {"control_authorized": {"recovery_engine": actor}},
                        authority=Authority.OPERATOR,
                    )
                if run["state"] == "PAUSE_REQUESTED":
                    self._change(
                        repo,
                        ctx,
                        run,
                        Kind.RUN,
                        "pause_confirmed",
                        actor,
                        {
                            "children_quiescent": {"commands": "all confirmed"},
                            "dispatch_disabled": {"run": run["id"]},
                        },
                    )
                for lease in leases:
                    if lease["holder_run_id"] != run["id"]:
                        continue
                    if lease["state"] in ("ACTIVE", "RELEASE_PENDING"):
                        self._change(
                            repo,
                            ctx,
                            lease,
                            Kind.LEASE,
                            "revoke",
                            actor,
                            {"control_authorized": {"recovery_engine": actor}},
                            authority=Authority.OPERATOR,
                        )
                    repo.remove_claim(lease)
            for control in controls:
                repo.update(
                    "resource_controls",
                    control["id"],
                    {
                        "epoch": generation["epoch"],
                        "last_fencing_token": 0,
                        "quarantined": False,
                        "reason": "epoch_reconciled",
                        "reconciliation_ref": str(generation["epoch"]),
                    },
                )
            repo.update("control_generation", "current", {"mode": "ACTIVE"})

    def cancel_prepared_on_recovery(self, actor, run_id):
        """Retire an interrupted Run, only with transactional proof of no pending IO.

        Never infer nonexecution from an absent Gateway receipt. Attempted or
        unknown commands must first be reconciled, including dataset completion.
        This deliberately cancels the remaining Run instead of minting a new
        physical attempt under an old approval.
        """
        with self.transaction() as repo:
            ctx = self._locked(repo, actor, run_id, authorize=False, active=False)
            require(
                ctx["generation"]["mode"] == "RECOVERING",
                "RECOVERY_REQUIRED",
                "Prepared command retirement is restricted to startup recovery",
            )
            pending = [c for c in ctx["commands"] if c["state"] == "NOT_DISPATCHED"]
            if not pending:
                return 0
            require(
                all(c["state"] in COMMAND_TERMINAL | {"NOT_DISPATCHED"} for c in ctx["commands"])
                and self._stops_confirmed(repo, ctx),
                "RECONCILIATION_PENDING",
                "Attempted commands and stops must be reconciled first",
            )
            quiet_states = {"PENDING", "READY", "WAITING_RESOURCE"}
            terminal_tasks = {"SUCCEEDED", "FAILED", "CANCELLED", "SKIPPED"}
            require(
                all(t["state"] in quiet_states | terminal_tasks for t in ctx["tasks"]),
                "RECONCILIATION_PENDING",
                "Tasks must have no unresolved physical or dataset work",
            )
            for command in pending:
                delivery = repo.get("command_deliveries", command["id"], lock=True)
                require(
                    delivery["status"] == "PENDING" and delivery["delivery_attempt_id"] is None,
                    "DELIVERY_PROOF_INVALID",
                    "Prepared state alone is not proof of nonexecution",
                )
            policy = {
                "recovery_engine": actor,
                "policy": "startup_cancel_unsent_v1",
                "epoch": str(ctx["generation"]["epoch"]),
            }
            if ctx["run"]["state"] != "CANCEL_REQUESTED":
                self._change(
                    repo,
                    ctx,
                    ctx["run"],
                    Kind.RUN,
                    "cancel",
                    actor,
                    {"control_authorized": policy},
                    authority=Authority.OPERATOR,
                )
            for command in pending:
                self._change(
                    repo,
                    ctx,
                    command,
                    Kind.COMMAND,
                    "cancel",
                    actor,
                    {
                        "no_dispatch": {"command": command["id"], "delivery": "PENDING"},
                        "cancellation_authorized": policy,
                    },
                )
            for task in ctx["tasks"]:
                if task["state"] in quiet_states:
                    self._change(
                        repo,
                        ctx,
                        task,
                        Kind.TASK,
                        "cancel",
                        actor,
                        {
                            "no_dispatch": {"task": task["id"]},
                            "run_cancel_requested": {"run": run_id, **policy},
                        },
                    )
            self._settle_run(repo, ctx, actor)
            return len(pending)

    def renew(self, actor, run_id, *, duration_s=60):
        require(0 < duration_s <= 300, "INVALID_LEASE", "Finite renewal window required")
        with self.transaction() as repo:
            ctx = self._locked(repo, actor, run_id)
            leases = self._lease_facts(repo, ctx)
            now = repo.now()
            expiry = min(now + timedelta(seconds=duration_s), ctx["approval"]["expires_at"])
            require(
                all(expiry > lease["expires_at"] for lease in leases.values()),
                "INVALID_RENEWAL",
                "Renewal must extend every lease within approval limit",
            )
            for lease in leases.values():
                self._change(
                    repo,
                    ctx,
                    lease,
                    Kind.LEASE,
                    "renew",
                    actor,
                    {
                        "authorization_valid": {"approval": ctx["approval"]["id"]},
                        "epoch_current": {"epoch": str(ctx["generation"]["epoch"])},
                        "renewal_before_expiry": {"old_expiry": lease["expires_at"].isoformat()},
                        "renewal_window_valid": {"new_expiry": expiry.isoformat()},
                    },
                    updates={"expires_at": expiry},
                )
            return expiry

    def recover_inflight(self, actor):
        """Restart sweep closes dispatch gates; it never sends a prepared command."""
        with self.transaction() as repo:
            self._engine(repo, actor)
            commands = repo.find("command_ledger", {})
        uncertain = [
            c["id"]
            for c in commands
            if c["state"] in ("DISPATCHED", "ACCEPTED", "RUNNING", "VERIFYING", "CANCEL_REQUESTED")
        ]
        for command_id in uncertain:
            self.mark_unknown(actor, command_id)
        return uncertain
