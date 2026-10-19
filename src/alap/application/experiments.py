"""D03 experiment/plan/approval use cases. No dispatch or fabricated hardware evidence."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from alap.application.ports import Repository, Transaction
from alap.contracts import ContractCatalog
from alap.domain.lifecycle import (
    RULE_INDEX,
    STATE_TYPES,
    Actor,
    ApprovalState,
    Authority,
    Effect,
    Evidence,
    Kind,
    Record,
    transition,
)
from alap.domain.rules import DomainError, freeze_revision


def new_id():
    return str(uuid4())


def digest(value):
    return freeze_revision(value).plan_hash


def require(condition, code, message):
    if not condition:
        raise DomainError(code, message)


class ExperimentService:
    def __init__(
        self,
        transaction: Transaction,
        catalog: ContractCatalog,
        *,
        skills: dict,
        policy_versions: dict,
        capability_versions: dict,
    ):
        self.transaction = transaction
        self.catalog = catalog
        # Trusted configuration snapshot, never supplied by an HTTP/LLM request.
        self.skills = deepcopy(skills)
        self.policy_versions = deepcopy(policy_versions)
        self.capability_versions = deepcopy(capability_versions)

    def _principal(self, repo, actor):
        principal = repo.get("principals", actor)
        require(principal["disabled_at"] is None, "FORBIDDEN", "Principal is disabled")
        return principal

    def _access(self, repo, actor, experiment, action, plan=None):
        principal = self._principal(repo, actor)
        membership = repo.membership(experiment["id"], actor)
        require(
            membership is not None and membership["revoked_at"] is None,
            "FORBIDDEN",
            "Experiment membership required",
        )
        roles = {
            "read": {"observer", "operator", "approver", "owner"},
            "write": {"operator", "owner"},
            "approve": {"approver", "owner"},
        }
        require(membership["role"] in roles[action], "FORBIDDEN", "Role cannot perform action")
        if action == "approve":
            require(principal["kind"] == "user", "FORBIDDEN", "Human approver required")
        if plan is not None:
            scope = membership["scope"]
            resources = set(plan["proposal"]["requested_resources"])
            require(
                resources <= set(scope.get("resources", [])),
                "FORBIDDEN",
                "Resources exceed explicit membership scope",
            )
            require(
                plan["proposal"]["risk_level"] in scope.get("risk_levels", []),
                "FORBIDDEN",
                "Risk exceeds explicit membership scope",
            )

    def _locked_approval(self, repo, experiment_id, approval_id):
        parent = repo.get("approvals", approval_id)
        require(parent["experiment_id"] == experiment_id, "PLAN_MISMATCH", "Wrong experiment")
        return repo.get("approvals", approval_id, lock=True)

    def _version(self, experiment, expected):
        require(
            type(expected) is int and experiment["revision"] == expected,
            "STATE_CONFLICT",
            "Reload experiment snapshot revision",
        )

    def _scope(self, plan):
        return {
            "plan_hash": plan["plan_hash"],
            "plan_revision_id": plan["id"],
            "resources": plan["plan_json"]["proposal"]["requested_resources"],
            "risk_level": plan["plan_json"]["proposal"]["risk_level"],
        }

    def _approval_integrity(self, approval, plan):
        scope = self._scope(plan)
        binding = digest(
            {
                "scope": scope,
                "expires_at": approval["expires_at"].astimezone(UTC).isoformat(),
            }
        )
        require(
            approval["scope_json"] == scope and approval["binding_hash"] == binding,
            "APPROVAL_MISMATCH",
            "Approval scope or binding differs from immutable plan",
        )

    def _current(self, repo, experiment, plan):
        plans = repo.plans(experiment["id"])
        require(plans and plans[0]["id"] == plan["id"], "PLAN_STALE", "Plan is superseded")
        value = json.loads(bytes(plan["canonical_bytes"]))
        resources = value["proposal"]["requested_resources"]
        for key, trusted in [
            ("policy_versions", self.policy_versions),
            ("capability_versions", self.capability_versions),
        ]:
            require(
                value[key] == {r: trusted.get(r) for r in resources},
                "PLAN_STALE",
                "Policy or capability version changed",
            )
        # Recheck skill contract and byte integrity using the original planning snapshot.
        snapshot = self.catalog.validate_revision(
            value, snapshot_version=plan["snapshot_version"], skills=self.skills
        )
        require(
            snapshot.plan_hash == plan["plan_hash"]
            and snapshot.canonical_bytes == bytes(plan["canonical_bytes"]),
            "PLAN_CORRUPT",
            "Persisted canonical plan is inconsistent",
        )

    def _event(
        self,
        repo: Repository,
        experiment,
        *,
        kind,
        identity,
        event,
        actor,
        old_version=-1,
        new_version=0,
        from_state=None,
        to_state,
        evidence_ids=(),
        effects=(),
        now=None,
    ):
        now = now or repo.now()
        experiment["revision"] += 1
        experiment["event_cursor"] += 1
        repo.update(
            "experiments",
            experiment["id"],
            {
                "revision": experiment["revision"],
                "event_cursor": experiment["event_cursor"],
            },
        )
        trace = new_id()
        repo.insert(
            "transition_audit",
            {
                "id": new_id(),
                "experiment_id": experiment["id"],
                "kind": kind,
                "subject_id": identity,
                "from_state": from_state,
                "to_state": to_state,
                "old_version": old_version,
                "new_version": new_version,
                "event": event,
                "actor_id": actor,
                "evidence_ids": list(evidence_ids),
                "effects": sorted(str(effect) for effect in effects),
                "trace_id": trace,
                "occurred_at": now,
            },
        )
        public_event = "succeeded" if kind == "task" and str(to_state) == "SUCCEEDED" else event
        envelope = {
            "event_id": new_id(),
            "experiment_id": experiment["id"],
            "experiment_seq": experiment["event_cursor"],
            "aggregate_id": identity,
            "aggregate_seq": new_version,
            "event_type": f"{kind}.{public_event}.v1",
            "schema_version": "2.0",
            "producer": "alap-application",
            "trace_id": trace,
            "payload": {
                "state": str(to_state),
                "evidence_ids": list(evidence_ids),
                "effects": sorted(str(effect) for effect in effects),
                "trace_id": trace,
            },
            "occurred_at": now.isoformat(),
        }
        self.catalog.validate("event", envelope)
        repo.insert("outbox_events", {**envelope, "aggregate_type": kind, "occurred_at": now})

    def _execute(
        self,
        actor,
        operation,
        scope,
        key,
        request,
        action,
        *,
        experiment_id=None,
        permission="write",
    ):
        require(
            isinstance(key, str) and bool(key.strip()), "INVALID_KEY", "Idempotency key required"
        )
        request_hash = digest(request)
        with self.transaction() as repo:
            self._principal(repo, actor)
            repo.generation()
            experiment = None
            if experiment_id:
                experiment = repo.get("experiments", experiment_id, lock=True)
                self._access(repo, actor, experiment, permission)
            response = repo.claim_request(actor, operation, scope, key, request_hash)
            if response is not None:
                return response
            response = action(repo, experiment)
            repo.complete_request(actor, operation, scope, key, response)
            return response

    def create_experiment(self, actor, *, experiment_id, sample_id, key, title="", objective=""):
        def action(repo, _):
            sample = repo.get("samples", sample_id, lock=True)
            require(sample["owner_id"] == actor, "FORBIDDEN", "Sample owner permission required")
            experiment = {
                "id": experiment_id,
                "sample_id": sample_id,
                "owner_id": actor,
                "revision": 0,
                "event_cursor": 0,
                "state": "DRAFT",
                "title": title,
                "objective": objective,
            }
            repo.insert("experiments", experiment)
            # Membership provisioning is an explicit identity administration concern.
            # Creation records owner membership via the repository's dedicated provision method.
            repo.add_owner(experiment_id, actor)
            self._event(
                repo,
                experiment,
                kind="experiment",
                identity=experiment_id,
                event="created",
                actor=actor,
                to_state="DRAFT",
            )
            return {"id": experiment_id, "revision": experiment["revision"]}

        return self._execute(
            actor,
            "create_experiment",
            sample_id,
            key,
            {
                "experiment_id": experiment_id,
                "sample_id": sample_id,
                "title": title,
                "objective": objective,
            },
            action,
        )

    def save_plan(self, actor, *, experiment_id, revision, expected_revision, key):
        revision = deepcopy(revision)
        self.catalog.validate("plan_revision", revision)

        def action(repo, experiment):
            self._version(experiment, expected_revision)
            self._access(repo, actor, experiment, "write", revision)
            require(
                revision["proposal"]["experiment_id"] == experiment_id,
                "PLAN_MISMATCH",
                "Plan belongs to another experiment",
            )
            plans = repo.plans(experiment_id)
            next_revision = plans[0]["revision"] + 1 if plans else 1
            require(
                revision["revision"] == next_revision, "STATE_CONFLICT", "Plan revision is not next"
            )
            snapshot = self.catalog.validate_revision(
                revision, snapshot_version=experiment["revision"], skills=self.skills
            )
            resources = revision["proposal"]["requested_resources"]
            for field, current in [
                ("policy_versions", self.policy_versions),
                ("capability_versions", self.capability_versions),
            ]:
                require(
                    revision[field] == {r: current.get(r) for r in resources},
                    "PLAN_STALE",
                    "Plan uses stale policy/capability",
                )
            approvals = repo.approvals(experiment_id)
            repo.insert(
                "plan_revisions",
                {
                    "id": revision["plan_revision_id"],
                    "experiment_id": experiment_id,
                    "revision": next_revision,
                    "snapshot_version": expected_revision,
                    "canonical_bytes": snapshot.canonical_bytes,
                    "plan_json": revision,
                    "plan_hash": snapshot.plan_hash,
                    "created_by": actor,
                },
            )
            repo.update("experiments", experiment_id, {"state": "PLANNED"})
            self._event(
                repo,
                experiment,
                kind="plan",
                identity=revision["plan_revision_id"],
                event="created",
                actor=actor,
                to_state="VALIDATED",
            )
            # All approvals locked before any related Run locks.
            for approval in approvals:
                if approval["state"] in ("PENDING", "APPROVED"):
                    self._approval_transition(
                        repo, experiment, approval, "supersede", actor, Authority.ENGINE, repo.now()
                    )
            return {
                "id": revision["plan_revision_id"],
                "plan_hash": snapshot.plan_hash,
                "revision": experiment["revision"],
            }

        return self._execute(
            actor,
            "save_plan",
            experiment_id,
            key,
            {"plan": revision, "expected_revision": expected_revision},
            action,
            experiment_id=experiment_id,
        )

    def request_approval(
        self, actor, *, experiment_id, plan_id, plan_hash, expires_at, expected_revision, key
    ):
        require(
            isinstance(expires_at, datetime) and expires_at.utcoffset() is not None,
            "INVALID_CLOCK",
            "Timezone-aware expiry required",
        )

        def action(repo, experiment):
            self._version(experiment, expected_revision)
            plan = repo.get("plan_revisions", plan_id)
            require(
                plan["experiment_id"] == experiment_id and plan["plan_hash"] == plan_hash,
                "PLAN_MISMATCH",
                "Exact plan and hash required",
            )
            self._access(repo, actor, experiment, "write", plan["plan_json"])
            self._current(repo, experiment, plan)
            now = repo.now()
            require(expires_at > now, "APPROVAL_EXPIRED", "Approval deadline must be in the future")
            scope = self._scope(plan)
            binding = digest({"scope": scope, "expires_at": expires_at.astimezone(UTC).isoformat()})
            identity = new_id()
            repo.insert(
                "approvals",
                {
                    "id": identity,
                    "experiment_id": experiment_id,
                    "plan_revision_id": plan_id,
                    "plan_hash": plan_hash,
                    "scope_json": scope,
                    "binding_hash": binding,
                    "state": "PENDING",
                    "state_version": 0,
                    "requested_by": actor,
                    "expires_at": expires_at,
                },
            )
            self._event(
                repo,
                experiment,
                kind="approval",
                identity=identity,
                event="requested",
                actor=actor,
                to_state="PENDING",
                now=now,
            )
            return {
                "id": identity,
                "state": "PENDING",
                "state_version": 0,
                "revision": experiment["revision"],
            }

        return self._execute(
            actor,
            "request_approval",
            experiment_id,
            key,
            {
                "plan_id": plan_id,
                "plan_hash": plan_hash,
                "expires_at": expires_at.astimezone(UTC).isoformat(),
                "expected_revision": expected_revision,
            },
            action,
            experiment_id=experiment_id,
        )

    def _decision(self, repo, experiment, row, kind, event, actor, authority, now, facts):
        state_type = STATE_TYPES[kind]
        record = Record(
            kind, row["id"], state_type(row["state"]), row["state_version"], row["binding_hash"]
        )
        evidence = tuple(
            Evidence(
                fact,
                new_id(),
                kind,
                row["id"],
                record.version,
                record.binding_hash,
                now,
                now + timedelta(seconds=1),
            )
            for fact in sorted(facts)
        )
        decision = transition(
            record,
            event,
            expected_version=record.version,
            actor=Actor(actor, authority),
            evidence=evidence,
            now=now,
        )
        for item in evidence:
            repo.insert(
                "evidence_records",
                {
                    "id": item.evidence_id,
                    "experiment_id": experiment["id"],
                    "subject_kind": kind,
                    "subject_id": row["id"],
                    "subject_version": record.version,
                    "binding_hash": record.binding_hash,
                    "fact": item.fact,
                    "source": {
                        "adapter": "d03_locked_use_case",
                        "experiment_revision": experiment["revision"],
                        "event": event,
                        "actor_id": actor,
                        "checked": facts[item.fact],
                    },
                    "valid_from": item.valid_from,
                    "valid_until": item.valid_until,
                    "verified_by": actor,
                    "verified_at": now,
                },
            )
        return decision

    def _approval_transition(self, repo, experiment, approval, event, actor, authority, now):
        plan = repo.get("plan_revisions", approval["plan_revision_id"])
        self._approval_integrity(approval, plan)
        facts = {}
        if event in ("approve", "reject", "revoke"):
            self._access(repo, actor, experiment, "approve", plan["plan_json"])
            membership = repo.membership(experiment["id"], actor)
            facts["approval_authorized"] = {
                "actor_id": actor,
                "membership_version": membership["version"],
                "scope": membership["scope"],
                "plan_hash": approval["plan_hash"],
            }
        if event == "approve":
            self._current(repo, experiment, plan)
            require(now < approval["expires_at"], "APPROVAL_EXPIRED", "Approval expired")
            now = repo.now()
            require(now < approval["expires_at"], "APPROVAL_EXPIRED", "Approval expired")
            facts["approval_window_valid"] = {"expires_at": approval["expires_at"].isoformat()}
            facts["plan_current"] = {"plan_id": plan["id"], "plan_hash": plan["plan_hash"]}
        if event == "supersede":
            current = repo.plans(experiment["id"])[0]
            require(current["id"] != plan["id"], "PLAN_CURRENT", "Plan has not changed")
            facts["plan_changed"] = {"previous": plan["id"], "current": current["id"]}
        if event == "expire":
            require(now >= approval["expires_at"], "NOT_EXPIRED", "Expiry not reached")
            facts["expiry_reached"] = {"expires_at": approval["expires_at"].isoformat()}
        decision = self._decision(
            repo, experiment, approval, Kind.APPROVAL, event, actor, authority, now, facts
        )
        values = {"state": decision.current.state, "state_version": decision.current.version}
        if event in ("approve", "reject", "revoke"):
            values["decided_by"] = actor
        repo.update("approvals", approval["id"], values)
        if Effect.FREEZE_DISPATCH in decision.effects:
            for run in repo.runs(experiment["id"]):
                if run["approval_id"] != approval["id"]:
                    continue
                if run["state"] in (
                    "SUCCEEDED",
                    "FAILED",
                    "CANCELLED",
                    "UNKNOWN",
                    "NEEDS_RECONCILIATION",
                    "CANCEL_REQUESTED",
                ):
                    repo.update("runs", run["id"], {"dispatch_blocked": True})
                    continue
                facts = {
                    "authorization_invalid": {
                        "approval_id": approval["id"],
                        "state": decision.current.state,
                        "version": decision.current.version,
                    }
                }
                if run["state"] in ("READY", "WAITING_RESOURCE", "PAUSED"):
                    commands = repo.find("command_ledger", {"run_id": run["id"]})
                    require(
                        all(
                            c["state"]
                            in (
                                "NOT_DISPATCHED",
                                "SUCCEEDED",
                                "CANCELLED",
                                "FAILED_CONFIRMED",
                                "REJECTED_BEFORE_EXECUTE",
                            )
                            for c in commands
                        ),
                        "RECONCILIATION_REQUIRED",
                        "Cannot assert quiescence of in-flight commands",
                    )
                    facts["children_quiescent"] = {
                        "commands": [c["id"] for c in commands],
                        "run_state": run["state"],
                    }
                run_decision = self._decision(
                    repo,
                    experiment,
                    run,
                    Kind.RUN,
                    "authorization_lost",
                    actor,
                    Authority.ENGINE,
                    now,
                    facts,
                )
                repo.update(
                    "runs",
                    run["id"],
                    {
                        "state": run_decision.current.state,
                        "state_version": run_decision.current.version,
                        "dispatch_blocked": True,
                    },
                )
                self._event(
                    repo,
                    experiment,
                    kind="run",
                    identity=run["id"],
                    event="authorization_lost",
                    actor=actor,
                    old_version=run["state_version"],
                    new_version=run_decision.current.version,
                    from_state=run["state"],
                    to_state=run_decision.current.state,
                    evidence_ids=run_decision.evidence_ids,
                    effects=run_decision.effects,
                    now=now,
                )
        self._event(
            repo,
            experiment,
            kind="approval",
            identity=approval["id"],
            event=event,
            actor=actor,
            old_version=approval["state_version"],
            new_version=decision.current.version,
            from_state=approval["state"],
            to_state=decision.current.state,
            evidence_ids=decision.evidence_ids,
            effects=decision.effects,
            now=now,
        )
        return decision

    def decide_approval(
        self, actor, *, experiment_id, approval_id, event, expected_revision, expected_version, key
    ):
        require(
            event in ("approve", "reject", "revoke"),
            "INVALID_ACTION",
            "Unsupported approval action",
        )

        def action(repo, experiment):
            self._version(experiment, expected_revision)
            approval = self._locked_approval(repo, experiment_id, approval_id)
            require(
                type(expected_version) is int and approval["state_version"] == expected_version,
                "STATE_CONFLICT",
                "Approval changed",
            )
            plan = repo.get("plan_revisions", approval["plan_revision_id"])
            self._access(repo, actor, experiment, "approve", plan["plan_json"])
            require(
                (Kind.APPROVAL, ApprovalState(approval["state"]), event) in RULE_INDEX,
                "ILLEGAL_TRANSITION",
                "Approval action not allowed from current state",
            )
            now = repo.now()
            if event == "approve":
                self._current(repo, experiment, plan)
                require(now < approval["expires_at"], "APPROVAL_EXPIRED", "Approval expired")
            decision = self._approval_transition(
                repo, experiment, approval, event, actor, Authority.APPROVER, now
            )
            return {
                "id": approval_id,
                "state": decision.current.state,
                "state_version": decision.current.version,
                "revision": experiment["revision"],
            }

        return self._execute(
            actor,
            f"approval_{event}",
            experiment_id,
            key,
            {
                "approval_id": approval_id,
                "expected_revision": expected_revision,
                "expected_version": expected_version,
            },
            action,
            experiment_id=experiment_id,
            permission="approve",
        )

    def expire_approvals(self, actor, *, experiment_id):
        # Explicit trusted timer principal, not caller-supplied authority/evidence booleans.
        with self.transaction() as repo:
            principal = self._principal(repo, actor)
            require(
                principal["kind"] == "service" and principal["issuer"] == "alap-timer",
                "FORBIDDEN",
                "Provisioned timer service required",
            )
            repo.generation()
            experiment = repo.get("experiments", experiment_id, lock=True)
            approvals = repo.approvals(experiment_id)
            now = repo.now()
            count = 0
            for approval in approvals:
                if approval["state"] in ("PENDING", "APPROVED") and now >= approval["expires_at"]:
                    self._approval_transition(
                        repo, experiment, approval, "expire", actor, Authority.TIMER, now
                    )
                    count += 1
            return count

    def start_run(self, actor, *, experiment_id, approval_id, expected_revision, key):
        def action(repo, experiment):
            self._version(experiment, expected_revision)
            approval = self._locked_approval(repo, experiment_id, approval_id)
            plan = repo.get("plan_revisions", approval["plan_revision_id"])
            self._access(repo, actor, experiment, "write", plan["plan_json"])
            self._current(repo, experiment, plan)
            self._approval_integrity(approval, plan)
            require(approval["state"] == "APPROVED", "APPROVAL_INVALID", "Approved plan required")
            require(repo.now() < approval["expires_at"], "APPROVAL_EXPIRED", "Approval expired")
            # IDs fixed at creation; task tables and execution are D04.
            tasks = [
                {"id": new_id(), "plan_task_id": task["id"], "attempt_no": 1}
                for task in plan["plan_json"]["proposal"]["tasks"]
            ]
            identity = new_id()
            repo.insert(
                "runs",
                {
                    "id": identity,
                    "experiment_id": experiment_id,
                    "plan_revision_id": plan["id"],
                    "approval_id": approval_id,
                    "plan_hash": plan["plan_hash"],
                    "state": "READY",
                    "state_version": 0,
                    "dispatch_blocked": True,
                    "binding_hash": plan["plan_hash"],
                    "task_identities": tasks,
                    "created_by": actor,
                },
            )
            self._event(
                repo,
                experiment,
                kind="run",
                identity=identity,
                event="created",
                actor=actor,
                to_state="READY",
            )
            return {"id": identity, "state": "READY", "revision": experiment["revision"]}

        return self._execute(
            actor,
            "start_run",
            experiment_id,
            key,
            {"approval_id": approval_id, "expected_revision": expected_revision},
            action,
            experiment_id=experiment_id,
        )

    def read_snapshot(self, actor, experiment_id, snapshot_transaction: Transaction):
        with snapshot_transaction() as repo:
            experiment = repo.get("experiments", experiment_id)
            self._access(repo, actor, experiment, "read")
            # Canonical bytes are internal persistence; snapshots expose validated JSON only.
            plans = [json.loads(bytes(p["canonical_bytes"])) for p in repo.plans(experiment_id)]
            return {
                "experiment": experiment,
                "plans": plans,
                "plan_summaries": [
                    {"id": p["id"], "plan_hash": p["plan_hash"], "revision": p["revision"]}
                    for p in repo.plans(experiment_id)
                ],
                "events": repo.events(experiment_id),
                "event_cursor": experiment["event_cursor"],
                "approvals": repo.approvals(experiment_id),
                "runs": repo.runs(experiment_id),
                "tasks": repo.find("tasks", {"experiment_id": experiment_id}),
                "commands": [
                    {k: c[k] for k in ("id", "run_id", "task_id", "state", "state_version")}
                    for c in repo.find("command_ledger", {"experiment_id": experiment_id})
                ],
                "datasets": [
                    {
                        "id": d["id"],
                        "state": d["state"],
                        "state_version": d["state_version"],
                        "manifest": d["manifest_json"] if d["state"] == "COMMITTED" else None,
                    }
                    for d in repo.find("datasets", {"experiment_id": experiment_id})
                ],
            }
