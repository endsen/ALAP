"""Deterministic polling worker; no model calls, approvals, or command retries."""

import math
from datetime import timedelta

from alap.application.control import ControlService
from alap.application.engine_recovery import EngineRecovery
from alap.application.execution import COMMAND_TERMINAL
from alap.domain.rules import DomainError

RUN_TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}


class EngineWorker:
    def __init__(self, execution, datasets, actor, *, lease_s=300, stopping=lambda: False):
        if not math.isfinite(lease_s) or not 0 < lease_s <= 300:
            raise ValueError("Lease duration must be finite, positive and at most 300 seconds")
        self.engine, self.datasets, self.actor = execution, datasets, actor
        self.control = ControlService(execution, engine_actor=actor)
        self.recovery = EngineRecovery(execution, actor)
        self.lease_s, self.stopping = lease_s, stopping

    def _attempt(self, report, kind, identity, action):
        if self.stopping():
            return False
        try:
            action()
            return True
        except DomainError as exc:
            if exc.code == "ENGINE_OWNERSHIP_LOST":
                raise
            report["problems"].append({kind: identity, "code": exc.code})
        except ConnectionError, TimeoutError:
            report["problems"].append({kind: identity, "code": "GATEWAY_UNAVAILABLE"})
        except OSError:
            report["problems"].append({kind: identity, "code": "STORAGE_UNAVAILABLE"})
        return False

    def _snapshot(self, table):
        with self.engine.transaction() as repo:
            self.engine._engine(repo, self.actor)
            return repo.find(table, {})

    def _publish(self, command):
        with self.engine.transaction() as repo:
            receipts = repo.find("gateway_receipts", {"command_id": command["id"]})
            receipts = [r for r in receipts if r["raw_receipt"]["payload"]["state"] == "VERIFYING"]
        if not receipts:
            raise DomainError("ACQUISITION_RECEIPT_MISSING", "No durable acquisition receipt")
        receipt = max(receipts, key=lambda row: row["receipt_seq"])
        identity = self.datasets.stage(self.actor, command["id"], receipt["id"])
        self.datasets.commit(self.actor, identity)
        self.datasets.finalize(self.actor, identity)

    def _maintenance(self, report, *, recovering):
        commands = {c["id"]: c for c in self._snapshot("command_ledger")}
        for stop in self._snapshot("stop_requests"):
            # A committed confirmation may still need its central projection.
            if (
                stop["state"] != "CONFIRMED"
                or commands[stop["command_id"]]["state"] not in COMMAND_TERMINAL
            ):
                self._attempt(
                    report, "stop_id", stop["id"], lambda s=stop: self.control.deliver_stop(s["id"])
                )
        if not recovering:
            for command in self._snapshot("command_ledger"):
                if command["state"] not in COMMAND_TERMINAL | {"NOT_DISPATCHED", "VERIFYING"}:
                    self._attempt(
                        report,
                        "command_id",
                        command["id"],
                        lambda c=command: self.engine.reconcile(self.actor, c["id"]),
                    )
        for command in self._snapshot("command_ledger"):
            if command["state"] == "VERIFYING":
                self._attempt(
                    report, "command_id", command["id"], lambda c=command: self._publish(c)
                )

    def _advance_run(self, run_id, report):
        engine, actor = self.engine, self.actor
        with engine.transaction() as repo:
            run = repo.get("runs", run_id)
            leases = repo.find("leases", {"holder_run_id": run_id})
            claimed = [
                lease
                for lease in leases
                if (claim := repo.claim(lease["resource_id"])) and claim["lease_id"] == lease["id"]
            ]
        if run["state"] in {"PAUSE_REQUESTED", "CANCEL_REQUESTED"}:
            with engine.transaction() as repo:
                ctx = engine._locked(repo, actor, run_id, authorize=False, active=False)
                engine._settle_run(repo, ctx, actor)
                run = ctx["run"]
        if run["state"] in RUN_TERMINAL:
            if claimed:
                engine.release(actor, run_id)
            return
        if run["state"] not in {"READY", "WAITING_RESOURCE", "RUNNING", "PAUSED"}:
            return
        if claimed:
            engine.expire_leases(actor, run_id)
        if run["state"] in {"READY", "WAITING_RESOURCE"}:
            engine.materialize(actor, run_id)
        if run["state"] in {"READY", "WAITING_RESOURCE", "PAUSED"}:
            if not engine.acquire(actor, run_id, duration_s=self.lease_s):
                return
        with engine.transaction() as repo:
            ctx = engine._locked(repo, actor, run_id)
            leases = engine._lease_facts(repo, ctx)
            expiry = min(lease["expires_at"] for lease in leases.values())
            renew_to = min(
                repo.now() + timedelta(seconds=self.lease_s), ctx["approval"]["expires_at"]
            )
            renew = expiry < repo.now() + timedelta(seconds=self.lease_s / 2) and all(
                renew_to > lease["expires_at"] for lease in leases.values()
            )
            tasks = ctx["tasks"]
            current = ctx["run"]
        if renew:
            engine.renew(actor, run_id, duration_s=self.lease_s)
        # Retain/reacquire valid paused leases for an explicit user resume; never resume here.
        if current["state"] == "PAUSED":
            return
        if current["state"] == "RUNNING" and current["dispatch_blocked"]:
            raise DomainError("DISPATCH_BLOCKED", "Run is frozen")
        completed = {t["plan_task_id"] for t in tasks if t["state"] == "SUCCEEDED"}
        eligible = [
            t
            for t in tasks
            if t["state"] in {"PENDING", "READY"}
            and set(t["definition"]["depends_on"]) <= completed
        ]
        if not eligible or self.stopping():
            return
        task = min(eligible, key=lambda t: t["plan_task_id"])
        command = engine.prepare(actor, run_id, task["plan_task_id"])
        if self.stopping():
            return  # The next owner retires this proven-unsent command during recovery.
        engine.dispatch(actor, command)
        report["dispatched"].append(command)

    def tick(self):
        report = {"mode": "STOPPING", "dispatched": [], "problems": []}
        if self.stopping():
            return report
        if not self.recovery.started:
            self.recovery.begin()
        with self.engine.transaction() as repo:
            self.engine._engine(repo, self.actor)
            recovering = repo.generation()["mode"] == "RECOVERING"
        self._maintenance(report, recovering=recovering)
        if self.stopping():
            return report
        if recovering:
            recovery = self.recovery.advance()
            report.update({"mode": recovery["mode"], "recovery": recovery})
            return report  # No new physical action in the same pass that opens the gate.
        report["mode"] = "ACTIVE"
        for run in self._snapshot("runs"):
            self._attempt(
                report, "run_id", run["id"], lambda r=run: self._advance_run(r["id"], report)
            )
        return report
