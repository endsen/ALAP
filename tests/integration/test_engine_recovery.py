"""D12b ownership loss and startup recovery against real PostgreSQL."""

import subprocess
import sys

import psycopg
import pytest

from alap.adapters.postgres.engine_owner import OwnedGateway, PostgresEngineOwner
from alap.application.engine_recovery import EngineRecovery
from alap.application.execution import ExecutionService
from alap.application.experiments import ExperimentService
from alap.domain.rules import DomainError

from .conftest import rows
from .test_execution import execution, prepare  # noqa: F401

pytestmark = pytest.mark.postgres


def owned_engine(owner, original):
    base = original.base
    foundation = ExperimentService(
        owner.transaction,
        base.catalog,
        skills=base.skills,
        policy_versions=base.policy_versions,
        capability_versions=base.capability_versions,
    )
    return ExecutionService(
        foundation,
        authenticator=original.auth,
        gateways={
            identity: OwnedGateway(owner, port) for identity, port in original.gateways.items()
        },
    )


def test_ownership_excludes_another_process_and_releases(database):
    dsn = database[0]
    script = """
import sys
from alap.adapters.postgres.engine_owner import PostgresEngineOwner
from alap.domain.rules import DomainError
try:
    with PostgresEngineOwner(sys.stdin.read()):
        raise AssertionError('Second process obtained ownership')
except DomainError as error:
    assert error.code == 'ENGINE_ALREADY_RUNNING'
"""
    with PostgresEngineOwner(dsn) as owner:
        owner.check()
        result = subprocess.run(
            [sys.executable, "-c", script], input=dsn, text=True, capture_output=True, timeout=10
        )
        assert result.returncode == 0, result.stderr
    with pytest.raises(DomainError, match="OWNERSHIP_LOST"):
        owner.check()
    with pytest.raises(DomainError, match="OWNER_CLOSED"):
        with owner:
            pass
    with PostgresEngineOwner(dsn) as replacement:
        replacement.check()


def test_ownership_transaction_rolls_back_without_losing_lock(database):
    with PostgresEngineOwner(database[0]) as owner:
        with pytest.raises(RuntimeError):
            with owner.transaction() as repo:
                repo.connection.execute(
                    "INSERT INTO principals VALUES ('rollback','test','rollback','service',NULL)"
                )
                raise RuntimeError("Injected application failure")
        owner.check()
        assert rows(database[0], "SELECT id FROM principals WHERE id='rollback'") == []
        with pytest.raises(DomainError, match="ENGINE_ALREADY_RUNNING"):
            with PostgresEngineOwner(database[0]):
                pass


@pytest.mark.parametrize(
    "method,args",
    [
        ("challenge", ()),
        ("accept", ({},)),
        ("query", ("command",)),
        ("confirm_dataset", ({},)),
        ("stop", ({},)),
        ("recover_command", ({},)),
        ("telemetry", ({},)),
        ("bind_epoch", ({},)),
    ],
)
def test_database_connection_loss_blocks_every_gateway_operation(database, method, args):
    calls = []

    class Spy:
        def __getattr__(self, name):
            return lambda *args: calls.append(name)

    dsn = database[0]
    with PostgresEngineOwner(dsn) as owner:
        with owner.transaction() as repo:
            pid = repo.connection.info.backend_pid
        port = OwnedGateway(owner, Spy())
        with psycopg.connect(dsn, autocommit=True) as db:
            assert db.execute("SELECT pg_terminate_backend(%s)", (pid,)).fetchone()[0]
        with pytest.raises(DomainError, match="ENGINE_OWNERSHIP_LOST"):
            getattr(port, method)(*args)
        with pytest.raises(DomainError, match="ENGINE_OWNERSHIP_LOST"):
            with owner.transaction():
                pass
        assert calls == []
        with PostgresEngineOwner(dsn) as replacement:
            replacement.check()
        # A replacement must never revive the previous owner's connection.
        with pytest.raises(DomainError, match="ENGINE_OWNERSHIP_LOST"):
            owner.check()


def test_prepared_command_is_cancelled_without_network_execution(execution):  # noqa: F811
    original, _, simulator, run, scenario = execution
    command = prepare(execution)
    with PostgresEngineOwner(scenario[3]) as owner:
        engine = owned_engine(owner, original)
        with pytest.raises(DomainError, match="RECOVERY_REQUIRED"):
            engine.cancel_prepared_on_recovery("engine", run["id"])
        recovery = EngineRecovery(engine, "engine")
        recovery.begin()
        assert recovery.advance()["mode"] == "ACTIVE"
    assert rows(scenario[3], "SELECT state FROM runs")[0]["state"] == "CANCELLED"
    assert rows(scenario[3], "SELECT state FROM command_ledger")[0]["state"] == "CANCELLED"
    assert all(t["state"] == "CANCELLED" for t in rows(scenario[3], "SELECT state FROM tasks"))
    assert rows(scenario[3], "SELECT status FROM command_deliveries")[0]["status"] == "PENDING"
    assert simulator.action_count(command) == 0
    assert rows(scenario[3], "SELECT * FROM resource_claims") == []
    with PostgresEngineOwner(scenario[3]) as owner:
        recovery = EngineRecovery(owned_engine(owner, original), "engine")
        recovery.begin()
        assert recovery.advance()["mode"] == "ACTIVE"
    assert simulator.action_count(command) == 0


def test_attempted_without_gateway_journal_blocks_recovery(execution):  # noqa: F811
    original, _, simulator, _, scenario = execution
    command = prepare(execution)
    with pytest.raises(ConnectionError):
        original.dispatch("engine", command, crash_after_commit=True)
    with PostgresEngineOwner(scenario[3]) as owner:
        recovery = EngineRecovery(owned_engine(owner, original), "engine")
        recovery.begin()
        for _ in range(2):
            result = recovery.advance()
            assert result["mode"] == "RECOVERING"
            assert result["problems"][0]["code"] == "JOURNAL_MISSING"
    assert rows(scenario[3], "SELECT state FROM command_ledger")[0]["state"] == "UNKNOWN"
    assert simulator.action_count(command) == 0


@pytest.mark.parametrize("execution", ["parallel"], indirect=True)
def test_uncertain_parallel_command_prevents_cancelling_prepared_run(execution):  # noqa: F811
    engine, _, simulator, run, scenario = execution
    unsent = prepare(execution)
    attempted = engine.prepare("engine", run["id"], "field")
    with pytest.raises(ConnectionError):
        engine.dispatch("engine", attempted, crash_after_commit=True)
    recovery = EngineRecovery(engine, "engine")
    recovery.begin()
    result = recovery.advance()
    assert result["mode"] == "RECOVERING"
    states = {c["id"]: c["state"] for c in rows(scenario[3], "SELECT id,state FROM command_ledger")}
    assert states == {unsent: "NOT_DISPATCHED", attempted: "UNKNOWN"}
    assert simulator.action_count(unsent) == simulator.action_count(attempted) == 0


def test_durable_lost_ack_reconciles_but_does_not_resume(execution, monkeypatch):  # noqa: F811
    engine, gateway, simulator, _, scenario = execution
    command = prepare(execution)
    original = gateway.accept
    with monkeypatch.context() as patch:
        patch.setattr(gateway, "accept", lambda signed: original(signed, crash_at="after_result"))
        with pytest.raises(ConnectionError):
            engine.dispatch("engine", command)
    recovery = EngineRecovery(engine, "engine")
    recovery.begin()
    assert recovery.advance()["mode"] == "ACTIVE"
    assert rows(scenario[3], "SELECT state FROM runs")[0]["state"] == "PAUSED"
    assert simulator.action_count(command) == 1


def test_delivery_evidence_conflict_cannot_be_treated_as_unsent(execution):  # noqa: F811
    engine, _, simulator, run, scenario = execution
    command = prepare(execution)
    with psycopg.connect(scenario[3]) as db:
        db.execute("UPDATE command_deliveries SET status='ATTEMPTED' WHERE id=%s", (command,))
    engine.begin_recovery("engine")
    with pytest.raises(DomainError, match="DELIVERY_PROOF_INVALID"):
        engine.cancel_prepared_on_recovery("engine", run["id"])
    assert rows(scenario[3], "SELECT state FROM command_ledger")[0]["state"] == "NOT_DISPATCHED"
    assert rows(scenario[3], "SELECT state FROM runs")[0]["state"] == "RUNNING"
    assert simulator.action_count(command) == 0


def test_dataset_verification_keeps_startup_gate_closed(execution):  # noqa: F811
    engine, _, simulator, run, scenario = execution
    temperature = prepare(execution)
    engine.dispatch("engine", temperature)
    field = engine.prepare("engine", run["id"], "field")
    engine.dispatch("engine", field)
    iv = engine.prepare("engine", run["id"], "iv")
    engine.dispatch("engine", iv)
    recovery = EngineRecovery(engine, "engine")
    recovery.begin()
    result = recovery.advance()
    assert result["mode"] == "RECOVERING"
    assert result["commands"] == [{"command_id": iv, "state": "VERIFYING"}]
    assert rows(scenario[3], "SELECT mode FROM control_generation")[0]["mode"] == "RECOVERING"
    assert simulator.action_count(iv) == 1


def test_recovery_does_not_open_without_configured_gateway(execution):  # noqa: F811
    engine, gateway, _, _, scenario = execution
    recovery = EngineRecovery(engine, "engine")
    recovery.begin()
    engine.gateways = {}
    try:
        result = recovery.advance()
        assert result["mode"] == "RECOVERING"
        assert result["problems"] == [{"gateway_id": "gw", "code": "GATEWAY_NOT_CONFIGURED"}]
        assert rows(scenario[3], "SELECT mode FROM control_generation")[0]["mode"] == "RECOVERING"
    finally:
        engine.gateways = {"gw": gateway}


def test_recovery_rejects_non_engine_principal(execution):  # noqa: F811
    engine, _, _, run, scenario = execution
    command = prepare(execution)
    engine.begin_recovery("engine")
    with pytest.raises(DomainError, match="FORBIDDEN"):
        engine.cancel_prepared_on_recovery("owner", run["id"])
    assert (
        rows(scenario[3], "SELECT state FROM command_ledger WHERE id=%s", (command,))[0]["state"]
        == "NOT_DISPATCHED"
    )
