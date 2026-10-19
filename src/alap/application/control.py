"""Explicit run control and recoverable stop delivery, separate from normal command dispatch."""

import json

from alap.application.execution import COMMAND_TERMINAL
from alap.application.experiments import require
from alap.domain.lifecycle import Authority, Kind
from alap.domain.rules import DomainError

TASK_TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "SKIPPED"}


class ControlService:
    def __init__(self, execution, *, engine_actor):
        self.execution, self.base = execution, execution.base
        self.transaction, self.engine = execution.transaction, engine_actor

    def _locked(self, repo, actor, run_id, *, authorize=False, expected_version=None):
        self.base._principal(repo, actor)
        ctx = self.execution._locked(
            repo, self.engine, run_id, authorize=authorize, active=authorize
        )
        self.base._access(repo, actor, ctx["experiment"], "write", ctx["plan"]["plan_json"])
        if expected_version is not None:
            require(
                ctx["run"]["state_version"] == expected_version, "STATE_CONFLICT", "Run changed"
            )
        return ctx

    def _quiet(self, ctx):
        return all(c["state"] in COMMAND_TERMINAL | {"NOT_DISPATCHED"} for c in ctx["commands"])

    def pause(self, actor, run_id, *, expected_version=None):
        with self.transaction() as repo:
            ctx = self._locked(repo, actor, run_id, expected_version=expected_version)
            run = ctx["run"]
            if run["state"] in ("PAUSED", "PAUSE_REQUESTED"):
                return run["state"]
            facts = {"control_authorized": {"actor": actor}}
            if run["state"] in ("READY", "WAITING_RESOURCE"):
                require(self._quiet(ctx), "CHILDREN_ACTIVE", "Unresolved commands exist")
                facts["children_quiescent"] = {"commands": [c["id"] for c in ctx["commands"]]}
            self.execution._change(
                repo, ctx, run, Kind.RUN, "pause", actor, facts, authority=Authority.OPERATOR
            )
            if run["state"] == "PAUSE_REQUESTED" and self._quiet(ctx):
                self.execution._change(
                    repo,
                    ctx,
                    run,
                    Kind.RUN,
                    "pause_confirmed",
                    self.engine,
                    {
                        "children_quiescent": {"commands": [c["id"] for c in ctx["commands"]]},
                        "dispatch_disabled": {"run": run_id},
                    },
                )
            return run["state"]

    def resume(self, actor, run_id, *, expected_version=None):
        with self.transaction() as repo:
            ctx = self._locked(
                repo, actor, run_id, authorize=True, expected_version=expected_version
            )
            conditions = [
                c
                for t in ctx["tasks"]
                if t["state"] not in TASK_TERMINAL
                for c in t["definition"]["preconditions"]
            ]
        readbacks = self.execution._readbacks({"preconditions": conditions})
        with self.transaction() as repo:
            ctx = self._locked(
                repo, actor, run_id, authorize=True, expected_version=expected_version
            )
            require(
                self._quiet(ctx) and self.execution._stops_confirmed(repo, ctx),
                "CHILDREN_ACTIVE",
                "Resolve commands and stops before resume",
            )
            leases = self.execution._lease_facts(repo, ctx)
            fresh = self.execution._fresh(repo, readbacks)
            self.execution._change(
                repo,
                ctx,
                ctx["run"],
                Kind.RUN,
                "resume",
                actor,
                {
                    "control_authorized": {"actor": actor},
                    "authorization_valid": {"approval": ctx["approval"]["id"]},
                    "lease_valid": {"leases": [v["id"] for v in leases.values()]},
                    "preconditions_fresh": fresh,
                    "children_quiescent": {"commands": [c["id"] for c in ctx["commands"]]},
                },
                authority=Authority.OPERATOR,
            )
            if len(ctx["tasks"]) == len(ctx["run"]["task_identities"]) and all(
                t["state"] == "SUCCEEDED" for t in ctx["tasks"]
            ):
                self.execution._change(
                    repo,
                    ctx,
                    ctx["run"],
                    Kind.RUN,
                    "start",
                    self.engine,
                    {
                        "authorization_valid": {"approval": ctx["approval"]["id"]},
                        "lease_valid": {"leases": list(leases)},
                        "preconditions_fresh": fresh,
                        "run_dispatch_allowed": {"run": run_id},
                    },
                )
                self.execution._settle_run(repo, ctx, self.engine)
            return ctx["run"]["state"]

    def cancel(self, actor, run_id, *, expected_version=None):
        with self.transaction() as repo:
            ctx = self._locked(repo, actor, run_id, expected_version=expected_version)
            if ctx["run"]["state"] in ("CANCEL_REQUESTED", "CANCELLED"):
                return ctx["run"]["state"]
            # UNKNOWN remains explicit reconciliation; no assumed stop or resource release.
            self.execution._change(
                repo,
                ctx,
                ctx["run"],
                Kind.RUN,
                "cancel",
                actor,
                {"control_authorized": {"actor": actor}},
                authority=Authority.OPERATOR,
            )
            for command in ctx["commands"]:
                if command["state"] in COMMAND_TERMINAL:
                    continue
                facts = {"cancellation_authorized": {"actor": actor, "run": run_id}}
                if command["state"] == "NOT_DISPATCHED":
                    facts["no_dispatch"] = {"command": command["id"]}
                self.execution._change(
                    repo, ctx, command, Kind.COMMAND, "cancel", self.engine, facts
                )
            for task in ctx["tasks"]:
                if task["state"] in TASK_TERMINAL:
                    continue
                facts = {"run_cancel_requested": {"run": run_id}}
                if task["state"] in ("PENDING", "READY", "WAITING_RESOURCE"):
                    facts["no_dispatch"] = {"task": task["id"]}
                self.execution._change(repo, ctx, task, Kind.TASK, "cancel", self.engine, facts)
            self._settle(repo, ctx)
            return ctx["run"]["state"]

    def _settle(self, repo, ctx):
        self.execution._settle_run(repo, ctx, self.engine)

    def deliver_stop(self, stop_id):
        with self.transaction() as repo:
            self.execution._engine(repo, self.engine)
            stop = repo.get("stop_requests", stop_id)
            initial = repo.get("command_ledger", stop["command_id"])
            ctx = self.execution._locked(
                repo, self.engine, initial["run_id"], authorize=False, active=False
            )
            stop = repo.get("stop_requests", stop_id, lock=True)
            if stop["state"] == "CONFIRMED":
                # The first confirmation may have committed before its command projection did.
                signed = stop["result_json"]
            else:
                repo.update("stop_requests", stop_id, {"state": "REQUESTED"})
                signed = None
            task = next(t for t in ctx["tasks"] if t["id"] == initial["task_id"])
            gateway = repo.get("instruments", initial["instrument_id"])["gateway_id"]
            request = {
                "operation": "stop",
                "stop_id": stop_id,
                "gateway_id": gateway,
                "package": {
                    "command": json.loads(bytes(initial["payload_bytes"])),
                    "task": task["definition"],
                },
            }
        try:
            if signed is None:
                signed = self.execution.gateways[gateway].stop(self.execution.auth.seal(request))
            response = self.execution.auth.open(signed)
            require(
                response["stop_id"] == stop_id
                and response["command_id"] == initial["id"]
                and response["payload_hash"] == initial["payload_hash"]
                and response["gateway_id"] == gateway
                and response["epoch"] == str(initial["epoch"])
                and response["quiescent"] is True,
                "STOP_INVALID",
                "Stop confirmation is not bound to this command",
            )
            receipt = self.execution.auth.open(response["receipt"])
            require(
                receipt["command_id"] == initial["id"]
                and receipt["payload_hash"] == initial["payload_hash"]
                and receipt["epoch"] == str(initial["epoch"])
                and receipt["gateway_id"] == gateway,
                "STOP_INVALID",
                "Embedded outcome does not match stop",
            )
            with self.transaction() as repo:
                ctx = self.execution._locked(
                    repo, self.engine, initial["run_id"], authorize=False, active=False
                )
                stop = repo.get("stop_requests", stop_id, lock=True)
                if stop["state"] != "CONFIRMED":
                    repo.update(
                        "stop_requests", stop_id, {"state": "CONFIRMED", "result_json": signed}
                    )
                command = next(c for c in ctx["commands"] if c["id"] == initial["id"])
                task = next(t for t in ctx["tasks"] if t["id"] == initial["task_id"])
                if receipt["state"] == "CANCELLED" and command["state"] not in COMMAND_TERMINAL:
                    facts = {
                        "gateway_authenticated": {"gateway": gateway},
                        "safe_stop_confirmed": {"stop": stop_id},
                        "device_quiescent": {"stop": stop_id},
                        "result_durable": {"stop": stop_id},
                    }
                    for row, kind in (
                        (ctx["run"], Kind.RUN),
                        (task, Kind.TASK),
                        (command, Kind.COMMAND),
                    ):
                        if row["state"] == "UNKNOWN":
                            self.execution._change(
                                repo,
                                ctx,
                                row,
                                kind,
                                "begin_reconciliation",
                                self.engine,
                                {"dispatch_disabled": {"run": initial["run_id"]}},
                                authority=Authority.RECONCILER,
                            )
                    if command["state"] == "NEEDS_RECONCILIATION":
                        facts.pop("gateway_authenticated")
                        facts["reconciliation_complete"] = {"stop": stop_id}
                        self.execution._change(
                            repo,
                            ctx,
                            command,
                            Kind.COMMAND,
                            "reconciled_cancel",
                            self.engine,
                            facts,
                            authority=Authority.RECONCILER,
                        )
                    else:
                        self.execution._change(
                            repo,
                            ctx,
                            command,
                            Kind.COMMAND,
                            "cancel_confirmed",
                            self.engine,
                            facts,
                            authority=Authority.GATEWAY,
                        )
                    task_facts = {
                        "command_cancelled": {"command": command["id"]},
                        "device_quiescent": {"stop": stop_id},
                    }
                    if task["state"] == "NEEDS_RECONCILIATION":
                        self.execution._change(
                            repo,
                            ctx,
                            task,
                            Kind.TASK,
                            "reconciled_cancel",
                            self.engine,
                            {**task_facts, "reconciliation_complete": {"stop": stop_id}},
                            authority=Authority.RECONCILER,
                        )
                    else:
                        self.execution._change(
                            repo, ctx, task, Kind.TASK, "cancel_confirmed", self.engine, task_facts
                        )
                self._settle(repo, ctx)
            if receipt["state"] != "CANCELLED":
                self.execution.ingest(
                    self.engine,
                    initial["id"],
                    response["receipt"],
                    reconcile=command["state"] in ("UNKNOWN", "NEEDS_RECONCILIATION"),
                )
                with self.transaction() as repo:
                    ctx = self.execution._locked(
                        repo, self.engine, initial["run_id"], authorize=False, active=False
                    )
                    self._settle(repo, ctx)
        except ConnectionError, TimeoutError, DomainError:
            with self.transaction() as repo:
                ctx = self.execution._locked(
                    repo, self.engine, initial["run_id"], authorize=False, active=False
                )
                stop = repo.get("stop_requests", stop_id, lock=True)
                if stop["state"] != "CONFIRMED":
                    repo.update("stop_requests", stop_id, {"state": "UNKNOWN"})
            self.execution.mark_unknown(self.engine, initial["id"])
            raise
