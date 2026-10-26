"""Human-authorized simulation latch review; never dispatch, resume or clear central quarantine."""

import json
from datetime import timedelta
from uuid import uuid4

from alap.application.execution import COMMAND_TERMINAL
from alap.application.experiments import require


class EdgeMaintenanceService:
    def __init__(self, execution, store):
        self.execution, self.store = execution, store

    def authorize(self, actor):
        self.store.role(actor, {"admin"})
        with self.execution.transaction() as repo:
            principal = self.execution.base._principal(repo, actor)
            require(
                principal["kind"] == "user", "FORBIDDEN", "Human maintenance administrator required"
            )

    def port(self, gateway_id):
        with self.execution.transaction() as repo:
            self.execution.base._principal(repo, repo.get("gateways", gateway_id)["principal_id"])
        port = self.execution.gateways.get(gateway_id)
        require(
            port is not None and hasattr(port, "maintenance"),
            "SERVICE_UNAVAILABLE",
            "Maintenance transport not configured",
        )
        return port

    def snapshot(self, actor, gateway_id):
        self.authorize(actor)
        result = self.port(gateway_id).maintenance("edge_review", None)
        with self.execution.transaction() as repo:
            generation = repo.generation()
            result["central_mode"] = generation["mode"]
            result["central_epoch"] = str(generation["epoch"])
        return result

    def acknowledge(self, actor, gateway_id, review):
        self.authorize(actor)
        self.execution.base.catalog.validate("edge_ack", review)
        port = self.port(gateway_id)
        with self.execution.transaction() as repo:
            generation = repo.generation()
            require(
                generation["mode"] == "RECOVERING",
                "RECOVERY_REQUIRED",
                "Explicit Engine recovery barrier required",
            )
            require(
                all(c["state"] in COMMAND_TERMINAL for c in repo.find("command_ledger", {})),
                "EDGE_BUSY",
                "Reconcile central command outcomes first",
            )
            require(
                all(s["state"] == "CONFIRMED" for s in repo.find("stop_requests", {})),
                "EDGE_BUSY",
                "Confirm all outstanding stop requests first",
            )
            now = repo.now()
            value = {
                "actor": actor,
                "review_id": str(uuid4()),
                "central_epoch": str(generation["epoch"]),
                "review": review,
                "issued_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=10)).isoformat(),
            }
        # Persist intent before external effect. Inspect lost replies via GET; never auto-reissue.
        self.store.audit(
            actor,
            "edgeAcknowledgementIntent",
            json.dumps({"gateway_id": gateway_id, **value}, sort_keys=True),
        )
        self.authorize(actor)
        result = port.maintenance("edge_acknowledge", value)
        require(
            result.get("review_id") == value["review_id"]
            and result.get("gateway_id") == gateway_id
            and result.get("incident") == review["incident"]
            and result.get("mode") == "WAITING"
            and result.get("execution_resumed") is False,
            "EXECUTION_UNKNOWN",
            "Maintenance result binding mismatch; inspect monitor",
        )
        return result
