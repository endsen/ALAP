"""Real process timing for the isolated output model, not Gateway/device acceptance."""

import json
import signal
import subprocess
import sys
import time

import pytest

from alap.adapters.gateway.edge import SimulationEdgeStore
from alap.domain.rules import DomainError


def until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result := predicate():
            return result
        time.sleep(0.02)
    pytest.fail("Independent monitor did not reach the expected boundary")


@pytest.fixture
def monitor_process(tmp_path):
    path = tmp_path / "edge.sqlite"
    config = tmp_path / "edge.json"
    config.write_text(
        json.dumps(
            {
                "mode": "simulation",
                "state_path": str(path),
                "loss_policy": {
                    "version": "sim-test-v1",
                    "timeout_s": 0.8,
                    "devices": {"sim-smu": "zero_output", "sim-temp": "hold", "sim-magnet": "hold"},
                },
            }
        )
    )
    children = []
    store = SimulationEdgeStore(path)

    def start():
        log_path = tmp_path / f"monitor-{len(children)}.log"
        with log_path.open("wb") as log:
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "alap.adapters.gateway.edge_server",
                    "--config",
                    str(config),
                ],
                stdout=log,
                stderr=log,
            )
        children.append(child)
        until(lambda: "edge_monitor_ready" in log_path.read_text() or child.poll() is not None)
        assert child.poll() is None, log_path.read_text()
        return child

    try:
        yield store, start
    finally:
        for child in children:
            if child.poll() is None:
                child.send_signal(signal.SIGCONT)
                child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
                pytest.fail("Monitor failed graceful shutdown")


def active(store):
    generation = store.snapshot()["generation"]
    store.heartbeat(generation, 0)
    store.write_output(generation, "sim-smu", 0.0005)
    store.write_output(generation, "sim-temp", 297)
    store.write_output(generation, "sim-magnet", 0.005)
    return generation


def assert_tripped(store):
    state = store.snapshot()
    assert state["mode"] == "TRIPPED"
    assert state["outputs"] == {"sim-smu": 0, "sim-temp": 297, "sim-magnet": 0.005}
    return state


def test_live_pulses_then_silence_latch_without_controller_calls(monitor_process):
    store, start = monitor_process
    child = start()
    generation = active(store)
    # Keep alive longer than the configured deadline, then cease all control calls.
    for sequence in range(1, 7):
        time.sleep(0.2)
        store.heartbeat(generation, sequence)
        assert store.snapshot()["outputs"]["sim-smu"] == 0.0005
    until(lambda: store.snapshot()["mode"] == "TRIPPED")
    state = assert_tripped(store)
    loss = [e for e in state["events"] if e["kind"] == "loss_latched"]
    assert len(loss) == 1
    assert json.loads(loss[0]["detail"])["reason"] == "heartbeat_expired"
    with pytest.raises(DomainError, match="EDGE_LATCHED"):
        store.heartbeat(generation, 7)
    assert child.poll() is None


def test_monitor_stall_cannot_be_masked_by_controller_pulses(monitor_process):
    store, start = monitor_process
    child = start()
    generation = active(store)
    child.send_signal(signal.SIGSTOP)
    try:
        time.sleep(1)
        with pytest.raises(DomainError, match="EDGE_LATCHED"):
            store.heartbeat(generation, 1)
        state = assert_tripped(store)
        assert json.loads(state["events"][-1]["detail"])["reason"] == "monitor_unavailable"
    finally:
        child.send_signal(signal.SIGCONT)


def test_killed_monitor_restart_keeps_latch_and_requires_explicit_rearm(monitor_process):
    store, start = monitor_process
    child = start()
    generation = active(store)
    child.kill()
    assert child.wait(timeout=10) == -9
    # No claim that a dead software monitor itself turns output off.
    start()
    state = assert_tripped(store)
    assert state["generation"] != generation
    assert json.loads(state["events"][-1]["detail"])["reason"] == "monitor_restarted"
    with pytest.raises(DomainError, match="EDGE_HEARTBEAT_INVALID"):
        store.heartbeat(generation, 1)
    with pytest.raises(DomainError, match="EDGE_LATCHED"):
        store.heartbeat(state["generation"], 1)
    fresh = store.acknowledge(
        state["generation"], state["incident"], operator="local-test", reason="reviewed simulator"
    )
    assert store.snapshot()["mode"] == "WAITING"
    with pytest.raises(DomainError, match="EDGE_NOT_ARMED"):
        store.write_output(fresh, "sim-smu", 0.0005)
    store.heartbeat(fresh, 0)
    assert store.snapshot()["outputs"]["sim-smu"] == 0
    store.write_output(fresh, "sim-smu", 0.0002)
    assert store.snapshot()["outputs"]["sim-smu"] == 0.0002
