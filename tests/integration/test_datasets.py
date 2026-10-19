"""D05a real files + PostgreSQL: publication is separate from acquisition."""

import io
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier

import h5py
import psycopg
import pytest

from alap.adapters.postgres.repository import PostgresRepository
from alap.adapters.storage.hdf5 import Hdf5Store
from alap.application.datasets import DatasetService
from alap.domain.rules import DomainError

from .conftest import rows
from .test_execution import execution, prepare  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture
def acquisition(execution, tmp_path):  # noqa: F811 - imported pytest fixture
    engine, gateway, simulator, run, scenario = execution
    temp = prepare(execution)
    engine.dispatch("engine", temp)
    field = engine.prepare("engine", run["id"], "field")
    engine.dispatch("engine", field)
    command = engine.prepare("engine", run["id"], "iv")
    engine.dispatch("engine", command)
    receipt = rows(scenario[3], "SELECT id FROM gateway_receipts WHERE command_id=%s", (command,))[
        0
    ]["id"]
    service = DatasetService(engine, Hdf5Store(tmp_path / "objects"))
    return service, command, receipt, execution


def stage(acquisition):
    service, command, receipt, _ = acquisition
    return service.stage("engine", command, receipt)


def test_commit_and_finalize_real_hdf5_with_provenance(acquisition):
    service, command, _, (engine, gateway, simulator, run, scenario) = acquisition
    identity = stage(acquisition)
    with pytest.raises(DomainError, match="DATASET_NOT_COMMITTED"):
        service.read("owner", identity)
    manifest = service.commit("engine", identity)
    public, content = service.read("owner", identity)
    assert public == manifest
    with h5py.File(io.BytesIO(content), "r") as data:
        assert len(data["current_A"]) == 21
        assert data["current_A"][0] == -0.0001
        assert data["current_A"][-1] == 0.0001
    assert rows(scenario[3], "SELECT command_id FROM provenance_edges")[0]["command_id"] == command
    assert (
        rows(
            scenario[3],
            "SELECT count(*) AS n FROM outbox_events WHERE event_type='dataset.committed.v1'",
        )[0]["n"]
        == 1
    )
    assert (
        rows(scenario[3], "SELECT state FROM command_ledger WHERE id=%s", (command,))[0]["state"]
        == "VERIFYING"
    )
    service.finalize("engine", identity)
    service.finalize("engine", identity)
    assert gateway.auth.open(gateway.query(command))["state"] == "SUCCEEDED"
    assert (
        rows(scenario[3], "SELECT state FROM runs WHERE id=%s", (run["id"],))[0]["state"]
        == "SUCCEEDED"
    )
    engine.release("engine", run["id"])
    assert rows(scenario[3], "SELECT count(*) AS n FROM resource_claims")[0]["n"] == 0
    assert simulator.action_count(command) == 1


def test_file_durable_but_commit_failure_does_not_publish_or_reacquire(acquisition, monkeypatch):
    service, command, _, (_, _, simulator, _, scenario) = acquisition
    identity = stage(acquisition)
    original = PostgresRepository.insert

    def fail(repo, table, values):
        if table == "outbox_events" and values["event_type"] == "dataset.committed.v1":
            raise RuntimeError("commit interrupted")
        return original(repo, table, values)

    with monkeypatch.context() as patch:
        patch.setattr(PostgresRepository, "insert", fail)
        with pytest.raises(RuntimeError, match="commit interrupted"):
            service.commit("engine", identity)
    assert rows(scenario[3], "SELECT state FROM datasets")[0]["state"] == "VALIDATING"
    assert rows(scenario[3], "SELECT * FROM provenance_edges") == []
    assert len(list(service.store.root.glob("*.h5"))) == 1
    with pytest.raises(DomainError, match="DATASET_NOT_COMMITTED"):
        service.read("owner", identity)
    restarted = DatasetService(service.execution, Hdf5Store(service.store.root))
    restarted.commit("engine", identity)
    restarted.finalize("engine", identity)
    assert simulator.action_count(command) == 1


def test_partial_upload_stays_staging(acquisition, monkeypatch):
    service, _, _, (_, _, _, _, scenario) = acquisition
    identity = stage(acquisition)

    def fail(*args):
        (service.store.root / ".upload-interrupted").write_bytes(b"partial")
        raise OSError("disk full")

    with monkeypatch.context() as patch:
        patch.setattr(service.store, "put", fail)
        with pytest.raises(OSError, match="disk full"):
            service.commit("engine", identity)
    assert rows(scenario[3], "SELECT state FROM datasets")[0]["state"] == "STAGING"
    service.commit("engine", identity)
    assert len(list(service.store.root.glob("*.h5"))) == 1


def test_concurrent_commit_idempotent(acquisition):
    service, command, receipt, (_, _, simulator, _, scenario) = acquisition
    identity = stage(acquisition)
    assert service.stage("engine", command, receipt) == identity
    barrier = Barrier(2)

    def worker():
        barrier.wait(timeout=5)
        return service.commit("engine", identity)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = [f.result(timeout=15) for f in [pool.submit(worker), pool.submit(worker)]]
    assert a == b
    assert rows(scenario[3], "SELECT count(*) AS n FROM datasets")[0]["n"] == 1
    assert (
        rows(
            scenario[3],
            "SELECT count(*) AS n FROM outbox_events WHERE event_type='dataset.committed.v1'",
        )[0]["n"]
        == 1
    )
    assert simulator.action_count(command) == 1


def test_post_commit_corruption_revokes_reads_preserves_history(acquisition):
    service, _, _, (_, _, _, _, scenario) = acquisition
    identity = stage(acquisition)
    manifest = service.commit("engine", identity)
    (service.store.root / service.store.key(identity)).write_bytes(b"broken")
    with pytest.raises(DomainError, match="ARTIFACT_INVALID"):
        service.read("owner", identity)
    assert not service.verify_integrity("engine", identity)
    row = rows(scenario[3], "SELECT * FROM datasets")[0]
    assert row["state"] == "CORRUPT"
    assert row["manifest_json"] == manifest
    assert rows(
        scenario[3],
        "SELECT effects FROM transition_audit WHERE kind='dataset' AND event='corruption_found'",
    )[0]["effects"] == ["revoke_data_access"]
    for action in (
        lambda: service.commit("engine", identity),
        lambda: service.read("owner", identity),
    ):
        with pytest.raises(DomainError):
            action()


def test_missing_committed_file_is_not_silently_recreated(acquisition):
    service, _, _, _ = acquisition
    identity = stage(acquisition)
    service.commit("engine", identity)
    path = service.store.root / service.store.key(identity)
    path.unlink()
    with pytest.raises(DomainError, match="ARTIFACT_INVALID"):
        service.commit("engine", identity)
    assert not path.exists()
    assert not service.verify_integrity("engine", identity)


def test_dataset_permissions_rechecked_even_on_retries(acquisition):
    service, command, receipt, (_, _, _, _, scenario) = acquisition
    with pytest.raises(DomainError, match="FORBIDDEN"):
        service.stage("owner", command, receipt)
    identity = stage(acquisition)
    service.commit("engine", identity)
    with pytest.raises(DomainError, match="FORBIDDEN"):
        service.read("outsider", identity)
    with psycopg.connect(scenario[3]) as db:
        db.execute(
            "UPDATE experiment_memberships SET revoked_at=clock_timestamp() WHERE actor_id='owner'"
        )
    with pytest.raises(DomainError, match="FORBIDDEN"):
        service.read("owner", identity)


def test_no_file_io_with_open_database_transaction(acquisition, monkeypatch):
    service, _, _, _ = acquisition
    identity = stage(acquisition)
    original = service.store.put

    def put(*args):
        # Acquiring the experiment lock in another connection would time out if caller held it.
        with service.transaction() as repo:
            repo.connection.execute("SET LOCAL lock_timeout='200ms'")
            repo.get("experiments", "EXP-SIM-001", lock=True)
        return original(*args)

    monkeypatch.setattr(service.store, "put", put)
    service.commit("engine", identity)


def test_dataset_definition_and_provenance_immutable(acquisition):
    service, _, _, (_, _, _, _, scenario) = acquisition
    identity = stage(acquisition)
    service.commit("engine", identity)
    for statement in [
        "UPDATE datasets SET command_id='forged',state_version=state_version+1",
        "UPDATE datasets SET checksum=repeat('a',64),state_version=state_version+1",
        "DELETE FROM datasets",
        "DELETE FROM provenance_edges",
    ]:
        with pytest.raises(psycopg.errors.CheckViolation), psycopg.connect(scenario[3]) as db:
            db.execute(statement)


def test_finalize_lost_ack_is_queryable_without_new_acquisition(acquisition, monkeypatch):
    service, command, _, (engine, gateway, simulator, _, _) = acquisition
    identity = stage(acquisition)
    service.commit("engine", identity)
    original = gateway.confirm_dataset

    def lose_ack(request):
        original(request)
        raise ConnectionError("lost publication ack")

    with monkeypatch.context() as patch:
        patch.setattr(gateway, "confirm_dataset", lose_ack)
        with pytest.raises(ConnectionError):
            service.finalize("engine", identity)
    service.finalize("engine", identity)
    assert simulator.action_count(command) == 1


def test_data_acquisition_unknown_can_be_reconciled_without_repeating(acquisition):
    service, command, _, (engine, _, simulator, run, scenario) = acquisition
    engine.mark_unknown("engine", command)
    engine.reconcile("engine", command)
    receipt = rows(
        scenario[3],
        "SELECT id FROM gateway_receipts WHERE command_id=%s ORDER BY receipt_seq DESC",
        (command,),
    )[0]["id"]
    identity = service.stage("engine", command, receipt)
    service.commit("engine", identity)
    service.finalize("engine", identity)
    assert simulator.action_count(command) == 1
    assert (
        rows(scenario[3], "SELECT state FROM runs WHERE id=%s", (run["id"],))[0]["state"]
        == "PAUSED"
    )


@pytest.mark.parametrize("change", ["samples", "time", "identity"])
def test_invalid_authenticated_data_rejected(acquisition, change):
    service, command, receipt_id, (engine, gateway, _, _, scenario) = acquisition
    value = deepcopy(gateway.auth.open(gateway.query(command)))
    if change == "samples":
        value["result"]["artifact"]["current_A"] = [0]
    elif change == "time":
        value["result"]["acquisition_interval"]["start_utc"] = "2000-01-01T00:00:00+00:00"
    else:
        other = rows(
            scenario[3], "SELECT id FROM gateway_receipts WHERE command_id<>%s LIMIT 1", (command,)
        )[0]["id"]
        with pytest.raises(DomainError, match="DATA_SOURCE_MISMATCH"):
            service.stage("engine", command, other)
        return
    signed = gateway.auth.seal(value)
    engine.ingest("engine", command, signed)
    bad_id = f"{value['gateway_id']}:{value['epoch']}:{value['receipt_seq']}"
    with pytest.raises(DomainError, match="INVALID_ACQUISITION"):
        service.stage("engine", command, bad_id)


def test_cancel_completed_acquisition_waits_for_formal_dataset(acquisition):
    from alap.application.control import ControlService

    service, command, _, (engine, _, simulator, run, scenario) = acquisition
    control = ControlService(engine, engine_actor="engine")
    assert control.cancel("owner", run["id"]) == "CANCEL_REQUESTED"
    stop = rows(scenario[3], "SELECT id FROM stop_requests")[0]["id"]
    control.deliver_stop(stop)
    assert rows(scenario[3], "SELECT state FROM runs")[0]["state"] == "CANCEL_REQUESTED"
    identity = stage(acquisition)
    service.commit("engine", identity)
    service.finalize("engine", identity)
    assert rows(scenario[3], "SELECT state FROM runs")[0]["state"] == "SUCCEEDED"
    assert simulator.action_count(command) == 1


def test_reconciled_dataset_resume_finishes_without_reexecution(acquisition):
    from alap.application.control import ControlService

    service, command, _, (engine, _, simulator, run, scenario) = acquisition
    engine.mark_unknown("engine", command)
    engine.reconcile("engine", command)
    identity = stage(acquisition)
    service.commit("engine", identity)
    service.finalize("engine", identity)
    engine.release("engine", run["id"])
    engine.acquire("engine", run["id"])
    assert ControlService(engine, engine_actor="engine").resume("owner", run["id"]) == "SUCCEEDED"
    assert simulator.action_count(command) == 1


def test_snapshot_exposes_only_committed_manifest_at_same_cursor(acquisition):
    service, _, _, (_, _, _, _, scenario) = acquisition
    base, uow, _, _ = scenario
    identity = stage(acquisition)
    before = base.read_snapshot("owner", "EXP-SIM-001", uow.snapshot)
    assert before["datasets"][0]["manifest"] is None
    service.commit("engine", identity)
    after = base.read_snapshot("owner", "EXP-SIM-001", uow.snapshot)
    assert after["datasets"][0]["manifest"]["dataset_id"] == identity
    assert after["event_cursor"] > before["event_cursor"]
    snapshot = rows(scenario[3], "SELECT * FROM device_snapshots")[0]
    assert after["datasets"][0]["manifest"]["device_snapshot_version"] == snapshot["version"]
    assert snapshot["source"]["preconditions"]["checked"]["samples"]
