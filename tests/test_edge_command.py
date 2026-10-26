"""Command-bound supervision rejects stale authority without resurrecting outputs."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from test_edge_supervision import edge  # noqa: F401

from alap.adapters.gateway.supervised import CommandEdgeStore
from alap.domain.rules import DomainError


def command(deadline=30):
    return {
        "command_id": str(uuid4()),
        "control_epoch": str(uuid4()),
        "deadline_at": (datetime.now(UTC) + timedelta(seconds=deadline)).isoformat(),
    }


def pulse(cmd, generation, sequence=0):
    now = datetime.now(UTC)
    return {
        "command_id": cmd["command_id"],
        "epoch": cmd["control_epoch"],
        "generation": generation,
        "sequence": sequence,
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=1)).isoformat(),
    }


@pytest.mark.parametrize("field", ["command_id", "epoch", "generation", "expires_at", "sequence"])
def test_command_pulse_identity_and_freshness(edge, field):  # noqa: F811
    monitor, now = edge
    store = CommandEdgeStore(monitor.path)
    cmd = command()
    generation = store.begin(cmd)
    valid = pulse(cmd, generation)
    store.pulse(valid)
    invalid = pulse(cmd, generation, 1)
    invalid[field] = {"expires_at": valid["issued_at"], "sequence": 0}.get(field, str(uuid4()))
    with pytest.raises(DomainError, match="EDGE_HEARTBEAT_INVALID"):
        store.pulse(invalid)
    assert store.snapshot()["sequence"] == 0
    store.finish(cmd["command_id"], generation)
    with pytest.raises(DomainError, match="EDGE_HEARTBEAT_INVALID"):
        store.pulse(pulse(cmd, generation, 2))
    assert store.snapshot()["mode"] == "WAITING"


def test_deadline_cannot_be_extended_by_fresh_pulses(edge):  # noqa: F811
    monitor, now = edge
    store = CommandEdgeStore(monitor.path)
    cmd = command()
    generation = store.begin(cmd)
    store.write_output(generation, "sim-smu", 0.0005)
    with store.transaction() as db:
        db.execute(
            "UPDATE edge_command SET deadline_utc=?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),),
        )
    with pytest.raises(DomainError, match="EDGE_LATCHED"):
        store.pulse(pulse(cmd, generation))
    state = store.snapshot()
    assert state["mode"] == "TRIPPED" and state["outputs"]["sim-smu"] == 0
    with pytest.raises(DomainError, match="EDGE_BUSY"):
        store.acknowledge(
            state["generation"], state["incident"], operator="maintainer", reason="review"
        )
    store.finish(cmd["command_id"], generation)
    store.acknowledge(
        state["generation"], state["incident"], operator="maintainer", reason="review"
    )
    assert store.snapshot()["mode"] == "WAITING"
