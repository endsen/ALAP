"""Dedicated maintenance RPC. API identity/grants are checked at the central boundary."""

import json
import time
from datetime import UTC, datetime
from uuid import UUID

from alap.adapters.gateway.journal import TERMINAL
from alap.domain.rules import DomainError


class GatewayMaintenance:
    def __init__(self, gateway):
        self.gateway = gateway
        self.edge = gateway.simulator.edge

    def snapshot(self):
        with self.edge.transaction() as db:
            state = dict(db.execute("SELECT * FROM edge_state WHERE id=1").fetchone())
            outputs = dict(db.execute("SELECT device,value FROM edge_outputs"))
            ack = db.execute(
                "SELECT * FROM edge_events WHERE kind='acknowledged' ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            acknowledged = dict(ack) if ack else None
        with self.gateway.connect() as db:
            epoch = db.execute("SELECT epoch FROM config").fetchone()[0]
        policy = json.loads(state["policy"])
        return {
            "gateway_id": self.gateway.identity,
            "gateway_epoch": epoch,
            "mode": state["mode"],
            "generation": state["generation"],
            "incident": state["incident"],
            "policy_version": policy["version"],
            "outputs": outputs,
            "monitor_fresh": 0 <= time.monotonic() - state["last_scan"] < policy["timeout_s"],
            "observed_at": datetime.now(UTC).isoformat(),
            "last_acknowledgement": acknowledged,
        }

    def acknowledge(self, value):
        if set(value) != {
            "review",
            "issued_at",
            "expires_at",
            "actor",
            "review_id",
            "central_epoch",
        }:
            raise ValueError("Unexpected maintenance authorization fields")
        UUID(value["review_id"])
        UUID(value["central_epoch"])
        self.gateway.catalog.validate("edge_ack", value["review"])
        issued, expiry = (datetime.fromisoformat(value[k]) for k in ("issued_at", "expires_at"))
        if (
            not issued <= datetime.now(UTC) < expiry
            or not 0 < (expiry - issued).total_seconds() <= 10
        ):
            raise DomainError(
                "EDGE_REVIEW_EXPIRED", "Fresh bounded maintenance authorization required"
            )
        # Also serialize against handshake/command admission; never wait behind active acquisition.
        if not self.gateway._operation.acquire(blocking=False):
            raise DomainError("EDGE_BUSY", "Gateway operation in progress")
        try:
            with self.gateway.connect() as db:
                if (
                    db.execute("SELECT epoch FROM config").fetchone()[0]
                    != value["review"]["gateway_epoch"]
                ):
                    raise DomainError("EDGE_REVIEW_STALE", "Gateway epoch changed")
                if any(r[0] not in TERMINAL for r in db.execute("SELECT state FROM commands")):
                    raise DomainError("EDGE_BUSY", "Every Gateway command must be reconciled")
            review = value["review"]
            generation = self.edge.acknowledge(
                review["generation"],
                review["incident"],
                operator=value["actor"],
                reason=review["reason"],
                review={
                    **review,
                    "review_id": value["review_id"],
                    "central_epoch": value["central_epoch"],
                    "expires_at": value["expires_at"],
                },
            )
            return {
                "gateway_id": self.gateway.identity,
                "review_id": value["review_id"],
                "incident": review["incident"],
                "generation": generation,
                "mode": "WAITING",
                "execution_resumed": False,
            }
        finally:
            self.gateway._operation.release()
