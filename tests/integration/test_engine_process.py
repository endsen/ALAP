"""Two real services: deterministic engine process -> HTTP Gateway process."""

import json
import os
import subprocess
import sys
import time
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from .conftest import rows
from .test_execution import execution  # noqa: F401
from .test_gateway_process import remote  # noqa: F401

pytestmark = pytest.mark.postgres


def until(predicate, *, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.02)
    pytest.fail("Engine process condition did not become true within deadline")


@pytest.fixture
def processes(remote, execution, tmp_path):  # noqa: F811
    base = execution[0].base
    dsn = execution[4][3]
    name = "alap-engine-test-" + uuid4().hex
    with remote() as client:
        config = tmp_path / "engine.json"
        config.write_text(
            json.dumps(
                {
                    "mode": "simulation",
                    "engine_actor": "engine",
                    "poll_s": 1,
                    "artifact_root": str(tmp_path / "objects"),
                    "execution_skills": base.skills,
                    "policy_versions": base.policy_versions,
                    "capability_versions": base.capability_versions,
                    "gateway_transport": {
                        "signing_key_file": str(tmp_path / "signing.key"),
                        "endpoints": {"gw": {"url": client.origin.geturl()}},
                    },
                }
            )
        )
        argv = [sys.executable, "-m", "alap.adapters.engine.server", "--config", str(config)]
        env = {**os.environ, "ALAP_DATABASE_URL": make_conninfo(dsn, application_name=name)}
        children = []

        def start():
            log_path = tmp_path / f"engine-{len(children)}.log"
            with log_path.open("wb") as log:
                process = subprocess.Popen(argv, env=env, stdout=log, stderr=log)
            children.append(process)
            return process, log_path

        try:
            yield start, argv, env, name
        finally:
            for process in children:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    pytest.fail("Engine did not stop gracefully")


def test_engine_and_gateway_processes_finish_and_restart_without_replay(processes, execution):  # noqa: F811
    start, argv, env, _ = processes
    dsn = execution[4][3]
    process, log = start()
    until(lambda: rows(dsn, "SELECT state FROM runs")[0]["state"] == "SUCCEEDED")
    until(lambda: rows(dsn, "SELECT * FROM resource_claims") == [])
    contender = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=10)
    assert contender.returncode == 1
    assert "ENGINE_ALREADY_RUNNING" in contender.stderr
    process.terminate()
    assert process.wait(timeout=10) == 0
    assert "engine_stopped" in log.read_text()
    restarted, log = start()
    until(lambda: '"mode": "ACTIVE"' in log.read_text())
    assert restarted.poll() is None
    commands = rows(dsn, "SELECT id FROM command_ledger")
    assert len(commands) == 3
    assert all(execution[2].action_count(c["id"]) == 1 for c in commands)
    assert rows(dsn, "SELECT state FROM datasets")[0]["state"] == "COMMITTED"


def test_kill_engine_after_first_action_restart_pauses_run(processes, execution):  # noqa: F811
    start, _, _, _ = processes
    dsn = execution[4][3]
    process, _ = start()
    until(lambda: rows(dsn, "SELECT id FROM command_ledger WHERE state='SUCCEEDED'"))
    process.kill()
    process.wait(timeout=10)
    restarted, log = start()
    until(lambda: '"mode": "ACTIVE"' in log.read_text())
    assert rows(dsn, "SELECT state FROM runs")[0]["state"] == "PAUSED"
    # Observe multiple polls after startup: the process may reacquire leases but never resumes.
    time.sleep(2.2)
    assert restarted.poll() is None
    commands = rows(dsn, "SELECT id FROM command_ledger")
    assert len(commands) == 1
    assert execution[2].action_count(commands[0]["id"]) == 1


def test_database_ownership_loss_terminates_actual_engine(processes, execution):  # noqa: F811
    start, _, _, name = processes
    process, log = start()
    until(lambda: '"mode": "ACTIVE"' in log.read_text())
    with psycopg.connect(execution[4][3], autocommit=True) as db:
        identities = db.execute(
            "SELECT pid FROM pg_stat_activity WHERE application_name=%s", (name,)
        ).fetchall()
        assert len(identities) == 1
        assert db.execute("SELECT pg_terminate_backend(%s)", identities[0]).fetchone()[0]
    assert process.wait(timeout=10) == 1
    assert "ENGINE_OWNERSHIP_LOST" in log.read_text()
    assert rows(execution[4][3], "SELECT * FROM command_ledger") == []
