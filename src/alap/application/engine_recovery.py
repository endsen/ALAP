"""Startup recovery gate. No dispatch, implicit stop, or automatic Run resume."""

from alap.application.execution import COMMAND_TERMINAL
from alap.domain.rules import DomainError


class EngineRecovery:
    def __init__(self, execution, actor):
        self.execution, self.actor = execution, actor
        self.started = False

    def begin(self):
        epoch = self.execution.begin_recovery(self.actor)
        self.execution.recover_inflight(self.actor)
        self.started = True
        return epoch

    def advance(self):
        """A bounded pass; unresolved outcomes leave the global gate closed.

        Query can reconcile a durable receipt, but missing journal entries never
        trigger accept/recover/stop. Acquisition publication and explicit Gateway
        recovery are separate use cases; their pending states remain visible.
        """
        if not self.started:
            raise DomainError("RECOVERY_REQUIRED", "Begin startup recovery first")
        engine, actor = self.execution, self.actor
        with engine.transaction() as repo:
            engine._engine(repo, actor)
            generation = repo.generation()
            if generation["mode"] != "RECOVERING":
                raise DomainError("NOT_RECOVERING", "Startup gate is no longer active")
            commands = repo.find("command_ledger", {})
        problems = []
        for command in commands:
            if command["state"] in {"UNKNOWN", "NEEDS_RECONCILIATION"}:
                try:
                    engine.reconcile(actor, command["id"])
                except (DomainError, ConnectionError, TimeoutError) as exc:
                    if isinstance(exc, DomainError) and exc.code == "ENGINE_OWNERSHIP_LOST":
                        raise
                    problems.append(
                        {
                            "command_id": command["id"],
                            "code": getattr(exc, "code", "GATEWAY_UNAVAILABLE"),
                        }
                    )
        for run_id in sorted({c["run_id"] for c in commands if c["state"] == "NOT_DISPATCHED"}):
            try:
                engine.cancel_prepared_on_recovery(actor, run_id)
            except DomainError as exc:
                if exc.code == "ENGINE_OWNERSHIP_LOST":
                    raise
                problems.append({"run_id": run_id, "code": exc.code})
        with engine.transaction() as repo:
            unresolved = [
                {"command_id": c["id"], "state": c["state"]}
                for c in repo.find("command_ledger", {})
                if c["state"] not in COMMAND_TERMINAL
            ]
            stops = [s["id"] for s in repo.find("stop_requests", {}) if s["state"] != "CONFIRMED"]
            gateways = repo.find("gateways", {})
        if unresolved or stops or problems:
            return {
                "mode": "RECOVERING",
                "commands": unresolved,
                "stops": stops,
                "problems": problems,
            }
        for gateway in gateways:
            if gateway["id"] not in engine.gateways:
                problems.append({"gateway_id": gateway["id"], "code": "GATEWAY_NOT_CONFIGURED"})
                continue
            try:
                engine.bind_gateway(actor, gateway["id"])
            except (DomainError, ConnectionError, TimeoutError) as exc:
                if isinstance(exc, DomainError) and exc.code == "ENGINE_OWNERSHIP_LOST":
                    raise
                problems.append(
                    {
                        "gateway_id": gateway["id"],
                        "code": getattr(exc, "code", "GATEWAY_UNAVAILABLE"),
                    }
                )
        if not gateways:
            problems.append({"code": "NO_REGISTERED_GATEWAY"})
        if problems:
            return {"mode": "RECOVERING", "commands": [], "stops": [], "problems": problems}
        engine.finish_recovery(actor)
        return {"mode": "ACTIVE", "commands": [], "stops": [], "problems": []}
