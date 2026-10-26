"""Atomic readback, monitor freshness, bounded review and audit persistence gates."""

# ruff: noqa: F811
from datetime import UTC, datetime, timedelta

import pytest
from test_edge_supervision import arm, edge  # noqa: F401

from alap.domain.rules import DomainError


def prepare(monitor, now):
    arm(monitor)
    now[0] += 1
    monitor.scan()
    state = monitor.snapshot()
    return state, {
        "expected_outputs": state["outputs"],
        "policy_version": "sim-v1",
        "expires_at": (datetime.now(UTC) + timedelta(seconds=10)).isoformat(),
    }


@pytest.mark.parametrize(
    "failure", ["monitor_stale", "clock_backwards", "nonzero_source", "expired", "audit_failure"]
)
def test_review_gate_is_atomic_and_never_clears_on_failure(edge, monkeypatch, failure):
    monitor, now = edge
    state, review = prepare(monitor, now)
    error = DomainError
    if failure == "monitor_stale":
        now[0] += 1
    elif failure == "clock_backwards":
        now[0] -= 1
    elif failure == "nonzero_source":
        with monitor.transaction() as db:
            db.execute("UPDATE edge_outputs SET value=0.0005 WHERE device='sim-smu'")
        review["expected_outputs"]["sim-smu"] = 0.0005
    elif failure == "expired":
        review["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    else:

        def fail(*args):
            raise OSError("Injected acknowledgement audit failure")

        monkeypatch.setattr(monitor, "_event", fail)
        error = OSError
    with pytest.raises(error):
        monitor.acknowledge(
            state["generation"], state["incident"], operator="owner", reason="review", review=review
        )
    after = monitor.snapshot()
    assert after["mode"] == "TRIPPED" and after["incident"] == state["incident"]
    assert after["generation"] == state["generation"]
    assert not any(e["kind"] == "acknowledged" for e in after["events"])
