"""Kill a real Engine at deterministic filesystem publication boundaries."""

import subprocess
import sys
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


@pytest.mark.parametrize("boundary", ["temporary_fsync", "directory_fsync"])
def test_killed_upload_recovers_without_reacquisition(
    processes,  # noqa: F811
    execution,  # noqa: F811
    tmp_path,
    boundary,
):
    start, argv, env, _ = processes
    engine, _, simulator, _, scenario = execution
    dsn = scenario[3]
    root = tmp_path / "objects"
    marker = tmp_path / "upload-blocked"
    # Test-only launcher: retain the real HDF5 writes/link, pause immediately before
    # the selected fsync. No product hook, fake put(), or fabricated storage error.
    launcher = tmp_path / "interrupt_upload.py"
    launcher.write_text(
        "import os, pathlib, runpy, sys, time\n"
        f"root = pathlib.Path({str(root)!r})\n"
        f"marker = pathlib.Path({str(marker)!r})\n"
        f"boundary = {boundary!r}\n"
        "original = os.fsync\n"
        "def checkpoint(fd):\n"
        "    path = pathlib.Path(os.readlink(f'/proc/self/fd/{fd}'))\n"
        "    selected = (path == root if boundary == 'directory_fsync' else\n"
        "                path.parent == root and path.name.startswith('.upload-'))\n"
        "    if selected:\n"
        "        marker.write_text(str(path))\n"
        "        while True: time.sleep(0.1)\n"
        "    return original(fd)\n"
        "os.fsync = checkpoint\n"
        "sys.argv = ['engine', *sys.argv[1:]]\n"
        "runpy.run_module('alap.adapters.engine.server', run_name='__main__')\n"
    )
    reader = DatasetService(engine, Hdf5Store(root))
    with (tmp_path / "interrupted-engine.log").open("wb") as log:
        child = subprocess.Popen(
            [sys.executable, str(launcher), *argv[3:]], env=env, stdout=log, stderr=log
        )
    try:
        until(marker.exists)
        dataset = rows(dsn, "SELECT * FROM datasets")[0]
        identity = dataset["id"]
        assert dataset["state"] == "STAGING" and dataset["manifest_json"] is None
        commands = rows(dsn, "SELECT id,state FROM command_ledger ORDER BY id")
        assert len(commands) == 3
        assert sorted(c["state"] for c in commands) == ["SUCCEEDED", "SUCCEEDED", "VERIFYING"]
        temporary = list(root.glob(".upload-*"))
        assert len(temporary) == 1 and temporary[0].stat().st_size > 0
        assert len(list(root.glob("*.h5"))) == (boundary == "directory_fsync")
        target = root / reader.store.key(identity)
        original_inode = target.stat().st_ino if target.exists() else None
        assert rows(dsn, "SELECT * FROM provenance_edges") == []
        assert (
            rows(dsn, "SELECT * FROM outbox_events WHERE event_type='dataset.committed.v1'") == []
        )
        with pytest.raises(DomainError, match="DATASET_NOT_COMMITTED"):
            reader.read("owner", identity)
        child.kill()
        assert child.wait(timeout=10) == -9
        assert rows(dsn, "SELECT state FROM datasets")[0]["state"] == "STAGING"
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=10)
    restarted, _ = start()
    until(lambda: rows(dsn, "SELECT state FROM datasets")[0]["state"] == "COMMITTED")
    until(lambda: rows(dsn, "SELECT * FROM resource_claims") == [])
    manifest, content = reader.read("owner", identity)
    assert content[:8] == b"\x89HDF\r\n\x1a\n"
    assert manifest["dataset_id"] == identity
    assert len(rows(dsn, "SELECT * FROM datasets")) == 1
    assert len(rows(dsn, "SELECT * FROM provenance_edges")) == 1
    assert (
        len(rows(dsn, "SELECT * FROM outbox_events WHERE event_type='dataset.committed.v1'")) == 1
    )
    time.sleep(2.2)
    assert restarted.poll() is None
    assert len(rows(dsn, "SELECT * FROM command_ledger")) == 3
    assert all(simulator.action_count(c["id"]) == 1 for c in commands)
    assert all(c["state"] == "SUCCEEDED" for c in rows(dsn, "SELECT state FROM command_ledger"))
    assert len(list(root.glob("*.h5"))) == 1
    if original_inode is not None:
        assert target.stat().st_ino == original_inode  # Existing object is never replaced.
    # SIGKILL bypasses finally: the orphan remains unreferenced, never published.
    # Its garbage collection is a separate operational gap, not claimed here.
    assert list(root.glob(".upload-*")) == temporary
