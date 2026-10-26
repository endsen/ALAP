"""Simulation foundation: local loss policy, durable latch and bounded recovery."""

import json

import pytest

from alap.adapters.gateway.edge import SimulationEdgeMonitor
from alap.domain.edge_policy import SimulationLossPolicy
from alap.domain.rules import DomainError

DEVICES = {"sim-smu": "zero_output", "sim-magnet": "hold", "sim-temp": "hold"}


@pytest.mark.parametrize("timeout", [True, 0, -1, float("nan"), float("inf"), 61])
def test_invalid_loss_deadlines(timeout):
    with pytest.raises(DomainError, match="EDGE_POLICY_INVALID"):
        SimulationLossPolicy("sim-v1", timeout, DEVICES)


def test_policy_cannot_apply_source_stop_to_magnet_or_mutate():
    devices = dict(DEVICES)
    policy = SimulationLossPolicy("sim-v1", 1, devices)
    devices["sim-magnet"] = "zero_output"
    assert policy.devices["sim-magnet"] == "hold"
    with pytest.raises(TypeError):
        policy.devices["sim-temp"] = "zero_output"
    with pytest.raises(DomainError, match="EDGE_POLICY_INVALID"):
        SimulationLossPolicy("sim-v1", 1, devices)


@pytest.fixture
def edge(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr("alap.adapters.gateway.edge.time.monotonic", lambda: now[0])
    monitor = SimulationEdgeMonitor(
        tmp_path / "edge.sqlite", SimulationLossPolicy("sim-v1", 1, DEVICES)
    )
    try:
        yield monitor, now
    finally:
        monitor.close()


def arm(monitor):
    generation = monitor.snapshot()["generation"]
    monitor.heartbeat(generation, 0)
    monitor.write_output(generation, "sim-smu", 0.0005)
    monitor.write_output(generation, "sim-magnet", 0.005)
    monitor.write_output(generation, "sim-temp", 296)
    return generation


@pytest.mark.parametrize("boundary", ["scan", "heartbeat", "write_output"])
def test_expiry_commits_latch_even_when_request_is_rejected(edge, boundary):
    monitor, now = edge
    generation = arm(monitor)
    now[0] = 100.5
    monitor.scan()
    now[0] = 101.0
    if boundary == "scan":
        monitor.scan()
    elif boundary == "heartbeat":
        with pytest.raises(DomainError, match="EDGE_LATCHED"):
            monitor.heartbeat(generation, 1)
    else:
        with pytest.raises(DomainError, match="EDGE_NOT_ARMED"):
            monitor.write_output(generation, "sim-smu", 0.0006)
    state = monitor.snapshot()
    assert state["mode"] == "TRIPPED"
    assert state["outputs"] == {"sim-smu": 0, "sim-temp": 296, "sim-magnet": 0.005}
    event = [e for e in state["events"] if e["kind"] == "loss_latched"]
    assert len(event) == 1
    detail = json.loads(event[0]["detail"])
    assert detail["reason"] == "heartbeat_expired" and detail["policy"]["version"] == "sim-v1"
    assert detail["before"]["sim-smu"] == 0.0005 and event[0]["recorded_at"]
    monitor.scan()
    assert monitor.snapshot()["events"] == state["events"]


def test_heartbeat_replay_and_old_generation_cannot_extend_deadline(edge):
    monitor, now = edge
    generation = arm(monitor)
    initial = monitor.snapshot()
    for gen, sequence in [(generation, 0), ("old", 1), (generation, True), (generation, 2**63)]:
        with pytest.raises(DomainError, match="EDGE_HEARTBEAT_INVALID"):
            monitor.heartbeat(gen, sequence)
        assert monitor.snapshot() == initial
    now[0] += 0.5
    monitor.scan()
    monitor.heartbeat(generation, 1)
    assert monitor.snapshot()["deadline"] == 101.5


def test_acknowledgement_does_not_restore_output_or_accept_old_pulses(edge):
    monitor, now = edge
    generation = arm(monitor)
    now[0] += 1
    monitor.scan()
    state = monitor.snapshot()
    with pytest.raises(DomainError, match="EDGE_ACK_INVALID"):
        monitor.acknowledge(generation, "wrong", operator="maintenance", reason="reviewed")
    with pytest.raises(DomainError, match="EDGE_LATCHED"):
        monitor.heartbeat(generation, 1)
    fresh = monitor.acknowledge(
        generation, state["incident"], operator="maintenance", reason="simulated outputs reviewed"
    )
    assert fresh != generation and monitor.snapshot()["mode"] == "WAITING"
    with pytest.raises(DomainError, match="EDGE_NOT_ARMED"):
        monitor.write_output(fresh, "sim-smu", 0.0005)
    with pytest.raises(DomainError, match="EDGE_HEARTBEAT_INVALID"):
        monitor.heartbeat(generation, 2)
    monitor.heartbeat(fresh, 0)
    assert monitor.snapshot()["outputs"]["sim-smu"] == 0


def test_clock_discontinuity_cannot_be_hidden_by_heartbeat(edge):
    monitor, now = edge
    generation = arm(monitor)
    now[0] -= 1
    with pytest.raises(DomainError, match="EDGE_LATCHED"):
        monitor.heartbeat(generation, 1)
    assert json.loads(monitor.snapshot()["events"][-1]["detail"])["reason"] == "clock_discontinuity"


def test_monitor_exclusivity_shutdown_and_policy_mismatch(edge):
    monitor, _ = edge
    arm(monitor)
    with pytest.raises(DomainError, match="EDGE_ALREADY_RUNNING"):
        SimulationEdgeMonitor(monitor.path, SimulationLossPolicy("sim-v1", 1, DEVICES))
    monitor.close()
    assert monitor.snapshot()["mode"] == "TRIPPED"
    with pytest.raises(DomainError, match="EDGE_MONITOR_CLOSED"):
        monitor.scan()
    with pytest.raises(DomainError, match="EDGE_POLICY_MISMATCH"):
        SimulationEdgeMonitor(monitor.path, SimulationLossPolicy("sim-v2", 1, DEVICES))
    reopened = SimulationEdgeMonitor(monitor.path, SimulationLossPolicy("sim-v1", 1, DEVICES))
    try:
        assert reopened.snapshot()["mode"] == "TRIPPED"
    finally:
        reopened.close()


def test_audit_failure_rolls_back_transition_and_can_be_retried(edge, monkeypatch):
    monitor, now = edge
    arm(monitor)
    now[0] += 1
    initial = monitor.snapshot()
    with monkeypatch.context() as patch:

        def fail(*args):
            raise OSError("audit storage failure")

        patch.setattr(SimulationEdgeMonitor, "_event", fail)
        with pytest.raises(OSError):
            monitor.scan()
    assert monitor.snapshot() == initial
    monitor.scan()
    assert monitor.snapshot()["mode"] == "TRIPPED"


@pytest.mark.parametrize(
    "device,value",
    [
        ("sim-smu", 0.002),
        ("sim-magnet", 1),
        ("sim-temp", 0),
        ("sim-smu", float("nan")),
        ("sim-smu", True),
        ("unknown", 0),
    ],
)
def test_output_limits_cannot_be_bypassed(edge, device, value):
    monitor, _ = edge
    generation = arm(monitor)
    initial = monitor.snapshot()
    with pytest.raises(DomainError, match="EDGE_OUTPUT_INVALID"):
        monitor.write_output(generation, device, value)
    assert monitor.snapshot() == initial


def test_monitor_cannot_repurpose_existing_device_database(tmp_path):
    import sqlite3

    path = tmp_path / "physical.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE devices(id TEXT)")
        db.execute("INSERT INTO devices VALUES ('existing')")
    with pytest.raises(DomainError, match="EDGE_STORE_INVALID"):
        SimulationEdgeMonitor(path, SimulationLossPolicy("sim-v1", 1, DEVICES))
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT * FROM devices").fetchall() == [("existing",)]
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [
            ("devices",)
        ]
