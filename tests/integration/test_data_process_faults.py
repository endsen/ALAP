"""Real filesystem faults while independent Engine/Gateway processes acquire data."""

import time

import pytest

from alap.adapters.storage.hdf5 import Hdf5Store
from alap.application.datasets import DatasetService
from alap.domain.rules import DomainError

from .conftest import rows
from .test_engine_process import processes, until  # noqa: F401
from .test_execution import execution  # noqa: F401
from .test_gateway_process import remote  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_storage_failure_recovers_without_reacquisition(processes, execution, tmp_path, damage):  # noqa: F811
    start, _, _, _ = processes
    engine, _, simulator, _, scenario = execution
    dsn = scenario[3]
    root, retained = tmp_path / "objects", tmp_path / "objects-retained"
    reader = DatasetService(engine, Hdf5Store(root))
    child, log = start()
    until(lambda: '"mode": "ACTIVE"' in log.read_text())
    # The first recovery tick never dispatches. Replace the empty storage directory
    # with a regular file before acquisition; no mocked put(), permissions or root assumption.
    root.rename(retained)
    root.write_bytes(b"storage path unavailable")
    try:
        until(lambda: "STORAGE_UNAVAILABLE" in log.read_text())
        dataset = rows(dsn, "SELECT * FROM datasets")[0]
        identity = dataset["id"]
        assert dataset["state"] == "STAGING" and dataset["manifest_json"] is None
        commands = rows(dsn, "SELECT id,state FROM command_ledger ORDER BY id")
        assert len(commands) == 3
        assert sorted(c["state"] for c in commands) == ["SUCCEEDED", "SUCCEEDED", "VERIFYING"]
        assert rows(dsn, "SELECT * FROM provenance_edges") == []
        with pytest.raises(DomainError, match="DATASET_NOT_COMMITTED"):
            reader.read("owner", identity)
        time.sleep(2.2)  # Multiple worker polls; not a duration/load acceptance test.
        assert rows(dsn, "SELECT id,state FROM command_ledger ORDER BY id") == commands
        assert rows(dsn, "SELECT state FROM datasets")[0]["state"] == "STAGING"
        assert all(simulator.action_count(c["id"]) == 1 for c in commands)
        assert child.poll() is None
    finally:
        root.unlink()
        retained.rename(root)
    until(lambda: rows(dsn, "SELECT state FROM runs")[0]["state"] == "SUCCEEDED")
    until(lambda: rows(dsn, "SELECT * FROM resource_claims") == [])
    manifest, content = reader.read("owner", identity)
    assert content[:8] == b"\x89HDF\r\n\x1a\n"
    assert rows(dsn, "SELECT state FROM datasets")[0]["state"] == "COMMITTED"
    assert len(rows(dsn, "SELECT * FROM provenance_edges")) == 1
    assert (
        len(rows(dsn, "SELECT * FROM outbox_events WHERE event_type='dataset.committed.v1'")) == 1
    )
    assert len(list(root.glob("*.h5"))) == 1
    assert not list(root.glob(".upload-*"))
    child.terminate()
    assert child.wait(timeout=10) == 0
    target = root / reader.store.key(identity)
    if damage == "missing":
        target.unlink()
    else:
        target.write_bytes(b"damaged after commit")
    try:
        with pytest.raises(DomainError, match="ARTIFACT_INVALID"):
            reader.read("owner", identity)
        # Failed reads neither repair a published file nor rewrite its authoritative manifest.
        assert rows(dsn, "SELECT manifest_json FROM datasets")[0]["manifest_json"] == manifest
        assert (
            not target.exists()
            if damage == "missing"
            else target.read_bytes() == b"damaged after commit"
        )
    finally:
        target.write_bytes(content)
    assert reader.read("owner", identity) == (manifest, content)
    restarted, restart_log = start()
    until(lambda: '"mode": "ACTIVE"' in restart_log.read_text())
    time.sleep(2.2)
    assert restarted.poll() is None
    assert len(rows(dsn, "SELECT * FROM command_ledger")) == 3
    assert all(simulator.action_count(c["id"]) == 1 for c in commands)
    assert rows(dsn, "SELECT state FROM runs")[0]["state"] == "SUCCEEDED"
