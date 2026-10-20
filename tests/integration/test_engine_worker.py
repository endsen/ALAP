"""D12b.2 deterministic worker integration; physical actions remain counted."""

import psycopg
import pytest

from alap.adapters.postgres.engine_owner import PostgresEngineOwner
from alap.adapters.storage.hdf5 import Hdf5Store
from alap.application.control import ControlService
from alap.application.datasets import DatasetService
from alap.application.engine_worker import EngineWorker

from .conftest import rows
from .test_engine_recovery import owned_engine
from .test_execution import execution, prepare  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture
def worker(execution, tmp_path):  # noqa: F811
    with PostgresEngineOwner(execution[4][3]) as owner:
        engine = owned_engine(owner, execution[0])
        yield EngineWorker(
            engine, DatasetService(engine, Hdf5Store(tmp_path / "objects")), "engine"
        )


def test_worker_completes_dag_data_and_releases_claims(worker, execution):  # noqa: F811
    _, _, simulator, _, scenario = execution
    assert worker.tick()["mode"] == "ACTIVE"
    assert rows(scenario[3], "SELECT * FROM command_ledger") == []
    for _ in range(5):
        assert worker.tick()["problems"] == []
    commands = rows(scenario[3], "SELECT * FROM command_ledger")
    assert len(commands) == 3
    assert all(c["state"] == "SUCCEEDED" and simulator.action_count(c["id"]) == 1 for c in commands)
    assert rows(scenario[3], "SELECT state FROM runs")[0]["state"] == "SUCCEEDED"
    assert rows(scenario[3], "SELECT state FROM datasets")[0]["state"] == "COMMITTED"
    assert rows(scenario[3], "SELECT * FROM resource_claims") == []


def test_worker_waits_for_explicit_resume(worker, execution):  # noqa: F811
    _, _, simulator, run, scenario = execution
    worker.tick()
    worker.tick()
    control = ControlService(worker.engine, engine_actor="engine")
    assert control.pause("owner", run["id"]) == "PAUSED"
    for _ in range(2):
        assert worker.tick()["dispatched"] == []
    assert len(rows(scenario[3], "SELECT * FROM command_ledger")) == 1
    control.resume("owner", run["id"])
    for _ in range(4):
        worker.tick()
    assert rows(scenario[3], "SELECT state FROM runs")[0]["state"] == "SUCCEEDED"
    assert all(
        simulator.action_count(c["id"]) == 1
        for c in rows(scenario[3], "SELECT id FROM command_ledger")
    )


def test_expired_lease_freezes_without_further_action(worker, execution):  # noqa: F811
    _, _, _, _, scenario = execution
    worker.tick()
    worker.tick()
    with psycopg.connect(scenario[3]) as db:
        db.execute(
            "UPDATE leases SET expires_at=clock_timestamp()-interval '1 second',"
            "state_version=state_version+1 WHERE state='ACTIVE'"
        )
    report = worker.tick()
    assert report["dispatched"] == []
    assert report["problems"][0]["code"] == "LEASE_INVALID"
    assert all(r["state"] == "EXPIRED" for r in rows(scenario[3], "SELECT state FROM leases"))
    assert all(
        r["quarantined"] for r in rows(scenario[3], "SELECT quarantined FROM resource_controls")
    )
    assert len(rows(scenario[3], "SELECT * FROM command_ledger")) == 1


def test_worker_renews_before_next_task(worker, execution):  # noqa: F811
    dsn = execution[4][3]
    worker.tick()
    worker.tick()
    with psycopg.connect(dsn) as db:
        db.execute(
            "UPDATE leases SET expires_at=clock_timestamp()+interval '30 seconds',"
            "state_version=state_version+1 WHERE state='ACTIVE'"
        )
    assert len(worker.tick()["dispatched"]) == 1
    assert (
        len(rows(dsn, "SELECT event_id FROM outbox_events WHERE event_type='lease.renew.v1'")) == 3
    )


def test_storage_failure_retries_publication_not_acquisition(worker, execution, monkeypatch):  # noqa: F811
    _, _, simulator, _, scenario = execution
    for _ in range(4):
        worker.tick()
    with monkeypatch.context() as patch:

        def disk_full(*args):
            raise OSError("Injected disk full")

        patch.setattr(worker.datasets.store, "put", disk_full)
        report = worker.tick()
        assert report["problems"][0]["code"] == "STORAGE_UNAVAILABLE"
        assert rows(scenario[3], "SELECT state FROM datasets")[0]["state"] == "STAGING"
    worker.tick()
    assert rows(scenario[3], "SELECT state FROM runs")[0]["state"] == "SUCCEEDED"
    assert all(
        simulator.action_count(c["id"]) == 1
        for c in rows(scenario[3], "SELECT id FROM command_ledger")
    )


def test_shutdown_between_prepare_and_dispatch_is_never_sent(worker, execution, monkeypatch):  # noqa: F811
    worker.tick()
    stopped = False
    original = worker.engine.prepare

    def prepare_then_stop(*args):
        nonlocal stopped
        command = original(*args)
        stopped = True
        return command

    worker.stopping = lambda: stopped
    monkeypatch.setattr(worker.engine, "prepare", prepare_then_stop)
    assert worker.tick()["dispatched"] == []
    command = rows(execution[4][3], "SELECT * FROM command_ledger")[0]
    assert command["state"] == "NOT_DISPATCHED"
    assert execution[2].action_count(command["id"]) == 0
    assert worker.tick()["mode"] == "STOPPING"


def test_startup_publishes_pending_acquisition_without_reexecuting(worker, execution):  # noqa: F811
    engine, _, simulator, run, scenario = execution
    temperature = prepare(execution)
    engine.dispatch("engine", temperature)
    field = engine.prepare("engine", run["id"], "field")
    engine.dispatch("engine", field)
    iv = engine.prepare("engine", run["id"], "iv")
    engine.dispatch("engine", iv)
    assert worker.tick()["mode"] == "RECOVERING"
    assert worker.tick()["mode"] == "ACTIVE"
    assert rows(scenario[3], "SELECT state FROM datasets")[0]["state"] == "COMMITTED"
    assert simulator.action_count(iv) == 1


def test_worker_delivers_existing_cancel_without_executing_command(worker, execution):  # noqa: F811
    engine, _, simulator, run, scenario = execution
    command = prepare(execution)
    with pytest.raises(ConnectionError):
        engine.dispatch("engine", command, crash_after_commit=True)
    ControlService(engine, engine_actor="engine").cancel("owner", run["id"])
    for _ in range(3):
        worker.tick()
    assert rows(scenario[3], "SELECT state FROM stop_requests")[0]["state"] == "CONFIRMED"
    assert rows(scenario[3], "SELECT state FROM runs")[0]["state"] == "CANCELLED"
    assert simulator.action_count(command) == 0


def test_revoked_approval_confirms_quiescent_pause_without_new_dispatch(worker, execution):  # noqa: F811
    engine, _, _, _, scenario = execution
    worker.tick()
    worker.tick()
    experiment = rows(scenario[3], "SELECT * FROM experiments")[0]
    approval = rows(scenario[3], "SELECT * FROM approvals")[0]
    engine.base.decide_approval(
        "approver",
        experiment_id=experiment["id"],
        approval_id=approval["id"],
        event="revoke",
        expected_revision=experiment["revision"],
        expected_version=approval["state_version"],
        key="worker-revoke",
    )
    assert worker.tick()["dispatched"] == []
    assert rows(scenario[3], "SELECT state FROM runs")[0]["state"] == "PAUSED"
    assert len(rows(scenario[3], "SELECT * FROM command_ledger")) == 1


def test_competing_runs_wait_then_complete_without_overlapping_claims(worker, execution):  # noqa: F811
    engine, _, simulator, _, scenario = execution
    experiment = rows(scenario[3], "SELECT * FROM experiments")[0]
    approval = rows(scenario[3], "SELECT * FROM approvals")[0]
    engine.base.start_run(
        "owner",
        experiment_id=experiment["id"],
        approval_id=approval["id"],
        expected_revision=experiment["revision"],
        key="second-worker-run",
    )
    for _ in range(12):
        worker.tick()
        claims = rows(scenario[3], "SELECT * FROM resource_claims")
        assert len({c["holder_run_id"] for c in claims}) <= 1
    assert all(r["state"] == "SUCCEEDED" for r in rows(scenario[3], "SELECT state FROM runs"))
    commands = rows(scenario[3], "SELECT id FROM command_ledger")
    assert len(commands) == 6
    assert all(simulator.action_count(c["id"]) == 1 for c in commands)
