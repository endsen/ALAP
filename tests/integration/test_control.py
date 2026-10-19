"""Run control races against durable simulator command and stop records."""

import json

import pytest

from alap.application.control import ControlService
from alap.domain.rules import DomainError

from .conftest import rows
from .test_execution import execution, prepare  # noqa: F401

pytestmark = pytest.mark.postgres


def controller(case):
    return ControlService(case[0], engine_actor="engine")


def pending_packet(case, command):
    service, _, _, _, scenario = case
    row = rows(scenario[3], "SELECT * FROM command_ledger WHERE id=%s", (command,))[0]
    task = rows(scenario[3], "SELECT definition FROM tasks WHERE id=%s", (row["task_id"],))[0][
        "definition"
    ]
    return service.auth.seal({"command": json.loads(bytes(row["payload_bytes"])), "task": task})


def stop_id(case):
    return rows(case[4][3], "SELECT id FROM stop_requests")[0]["id"]


def run_state(case):
    return rows(case[4][3], "SELECT state FROM runs WHERE id=%s", (case[3]["id"],))[0]["state"]


def test_pause_at_boundary_resume_preserves_prepared_command(execution):  # noqa: F811
    engine, _, simulator, run, _ = execution
    command = prepare(execution)
    control = controller(execution)
    assert control.pause("owner", run["id"]) == "PAUSED"
    with pytest.raises(DomainError, match="DISPATCH_BLOCKED"):
        engine.dispatch("engine", command)
    assert simulator.action_count(command) == 0
    assert control.resume("owner", run["id"]) == "READY"
    assert engine.prepare("engine", run["id"], "temperature") == command
    engine.dispatch("engine", command)
    assert simulator.action_count(command) == 1


def test_pause_waits_for_inflight_task(execution):  # noqa: F811
    engine, gateway, _, run, _ = execution
    command = prepare(execution)
    with pytest.raises(ConnectionError):
        engine.dispatch("engine", command, crash_after_commit=True)
    control = controller(execution)
    assert control.pause("owner", run["id"]) == "PAUSE_REQUESTED"
    engine.ingest("engine", command, gateway.accept(pending_packet(execution, command)))
    assert run_state(execution) == "PAUSED"


def test_cancel_unsent_does_not_contact_gateway(execution):  # noqa: F811
    engine, _, simulator, run, scenario = execution
    command = prepare(execution)
    assert controller(execution).cancel("owner", run["id"]) == "CANCELLED"
    assert rows(scenario[3], "SELECT * FROM stop_requests") == []
    assert simulator.action_count(command) == 0
    with pytest.raises(DomainError):
        engine.dispatch("engine", command)
    engine.release("engine", run["id"])


def test_stop_before_packet_durably_blocks_late_execution(execution):  # noqa: F811
    engine, gateway, simulator, run, _ = execution
    command = prepare(execution)
    with pytest.raises(ConnectionError):
        engine.dispatch("engine", command, crash_after_commit=True)
    packet = pending_packet(execution, command)
    control = controller(execution)
    assert control.cancel("owner", run["id"]) == "CANCEL_REQUESTED"
    control.deliver_stop(stop_id(execution))
    assert run_state(execution) == "CANCELLED"
    assert gateway.auth.open(gateway.accept(packet))["state"] == "CANCELLED"
    assert simulator.action_count(command) == 0
    control.deliver_stop(stop_id(execution))
    engine.release("engine", run["id"])


def test_lost_stop_ack_keeps_unknown_and_quarantine_until_replayed_confirmation(
    execution,  # noqa: F811
    monkeypatch,
):
    engine, gateway, simulator, run, scenario = execution
    command = prepare(execution)
    with pytest.raises(ConnectionError):
        engine.dispatch("engine", command, crash_after_commit=True)
    control = controller(execution)
    control.cancel("owner", run["id"])
    original = gateway.stop

    def lost(request):
        original(request)
        raise ConnectionError("stop ACK lost")

    with monkeypatch.context() as patch:
        patch.setattr(gateway, "stop", lost)
        with pytest.raises(ConnectionError):
            control.deliver_stop(stop_id(execution))
    assert run_state(execution) == "UNKNOWN"
    assert rows(scenario[3], "SELECT state FROM stop_requests")[0]["state"] == "UNKNOWN"
    with pytest.raises(DomainError, match="STOP_PENDING"):
        engine.release("engine", run["id"])
    control.deliver_stop(stop_id(execution))
    assert run_state(execution) == "CANCELLED"
    assert simulator.action_count(command) == 0
    engine.release("engine", run["id"])


@pytest.mark.parametrize("execution", ["single"], indirect=True)
def test_completion_wins_cancel_race(execution):  # noqa: F811
    engine, gateway, simulator, run, _ = execution
    command = prepare(execution)
    with pytest.raises(ConnectionError):
        engine.dispatch("engine", command, crash_after_commit=True)
    gateway.accept(pending_packet(execution, command))
    control = controller(execution)
    control.cancel("owner", run["id"])
    control.deliver_stop(stop_id(execution))
    assert run_state(execution) == "SUCCEEDED"
    assert simulator.action_count(command) == 1


def test_control_permissions_and_revoked_resume(execution):  # noqa: F811
    engine, _, _, run, scenario = execution
    prepare(execution)
    control = controller(execution)
    with pytest.raises(DomainError, match="FORBIDDEN"):
        control.cancel("observer", run["id"])
    control.pause("owner", run["id"])
    approval = rows(scenario[3], "SELECT id FROM approvals")[0]["id"]
    engine.base.decide_approval(
        "approver",
        experiment_id="EXP-SIM-001",
        approval_id=approval,
        expected_revision=rows(scenario[3], "SELECT revision FROM experiments")[0]["revision"],
        key="revoke-control",
        event="revoke",
        expected_version=rows(scenario[3], "SELECT state_version FROM approvals")[0][
            "state_version"
        ],
    )
    with pytest.raises(DomainError, match="APPROVAL_INVALID"):
        control.resume("owner", run["id"])


def test_pending_stop_blocks_epoch_handshake(execution):  # noqa: F811
    engine, _, _, run, _ = execution
    command = prepare(execution)
    with pytest.raises(ConnectionError):
        engine.dispatch("engine", command, crash_after_commit=True)
    control = controller(execution)
    control.cancel("owner", run["id"])
    engine.begin_recovery("engine")
    with pytest.raises(DomainError, match="STOP_PENDING"):
        engine.bind_gateway("engine", "gw")
    control.deliver_stop(stop_id(execution))
    engine.bind_gateway("engine", "gw")
    engine.finish_recovery("engine")


def test_stop_effects_rollback_when_audit_fails(execution, monkeypatch):  # noqa: F811
    from alap.adapters.postgres.repository import PostgresRepository

    engine, _, _, run, scenario = execution
    command = prepare(execution)
    with pytest.raises(ConnectionError):
        engine.dispatch("engine", command, crash_after_commit=True)
    original = PostgresRepository.insert

    def fail(repo, table, value):
        if table == "transition_audit" and value["event"] == "cancel":
            raise RuntimeError("audit interrupted")
        return original(repo, table, value)

    monkeypatch.setattr(PostgresRepository, "insert", fail)
    with pytest.raises(RuntimeError):
        controller(execution).cancel("owner", run["id"])
    assert rows(scenario[3], "SELECT * FROM stop_requests") == []
    assert run_state(execution) == "RUNNING"


def test_stopped_command_tombstone_survives_gateway_restart(execution):  # noqa: F811
    from alap.adapters.gateway.journal import Gateway

    engine, gateway, simulator, run, _ = execution
    command = prepare(execution)
    with pytest.raises(ConnectionError):
        engine.dispatch("engine", command, crash_after_commit=True)
    packet = pending_packet(execution, command)
    control = controller(execution)
    control.cancel("owner", run["id"])
    control.deliver_stop(stop_id(execution))
    gateway.close()
    restarted = Gateway(
        "gw",
        gateway.path,
        authenticator=gateway.auth,
        catalog=gateway.catalog,
        simulator=simulator,
        skills=gateway.skills,
        policy_versions=gateway.policies,
        capability_versions=gateway.capabilities,
    )
    engine.gateways["gw"] = restarted
    assert restarted.auth.open(restarted.accept(packet))["state"] == "CANCELLED"
    assert simulator.action_count(command) == 0


def test_mismatched_stop_ack_cannot_confirm_or_release(execution, monkeypatch):  # noqa: F811
    engine, gateway, _, run, scenario = execution
    command = prepare(execution)
    with pytest.raises(ConnectionError):
        engine.dispatch("engine", command, crash_after_commit=True)
    control = controller(execution)
    control.cancel("owner", run["id"])
    original = gateway.stop

    def corrupt(request):
        response = gateway.auth.open(original(request))
        response["command_id"] = "another-command"
        return gateway.auth.seal(response)

    monkeypatch.setattr(gateway, "stop", corrupt)
    with pytest.raises(DomainError, match="STOP_INVALID"):
        control.deliver_stop(stop_id(execution))
    assert rows(scenario[3], "SELECT state FROM stop_requests")[0]["state"] == "UNKNOWN"
    assert run_state(execution) == "UNKNOWN"


def test_cancel_before_task_materialization_is_not_success(execution):  # noqa: F811
    engine, _, _, _, scenario = execution
    approval = rows(scenario[3], "SELECT id FROM approvals")[0]["id"]
    revision = rows(scenario[3], "SELECT revision FROM experiments")[0]["revision"]
    run = engine.base.start_run(
        "owner",
        experiment_id="EXP-SIM-001",
        approval_id=approval,
        expected_revision=revision,
        key="unmaterialized",
    )
    assert controller(execution).cancel("owner", run["id"]) == "CANCELLED"
    with pytest.raises(DomainError, match="RUN_NOT_READY"):
        engine.materialize("engine", run["id"])
