"""Actual monitor/Gateway/Engine processes with bounded continuous IV acquisition."""

import json
import os
import secrets
import subprocess
import sys
import time

import psycopg
import pytest
from psycopg.conninfo import make_conninfo
from test_edge_process import monitor_process  # noqa: F401

from alap.adapters.gateway.auth import Authenticator

from .conftest import rows
from .test_engine_process import until
from .test_execution import execution  # noqa: F401
from .test_gateway_process import remote  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture
def supervised(remote, monitor_process, execution, tmp_path):  # noqa: F811
    store, monitor_start = monitor_process
    monitor_start()
    heartbeat_key = tmp_path / "heartbeat.key"
    heartbeat_key.write_bytes(secrets.token_bytes(32))
    heartbeat_key.chmod(0o600)
    maintenance_key = tmp_path / "maintenance.key"
    maintenance_key.write_bytes(secrets.token_bytes(32))
    maintenance_key.chmod(0o600)
    config = tmp_path / "gateway.json"
    settings = json.loads(config.read_text())
    settings["supervision"] = {
        "state_path": str(tmp_path / "edge.sqlite"),
        "heartbeat_key_file": str(heartbeat_key),
        "sample_interval_s": 0.2,
        "maintenance_key_file": str(maintenance_key),
    }
    config.write_text(json.dumps(settings))
    children = []
    with remote() as client:
        client.maintenance_auth = Authenticator(maintenance_key.read_bytes())
        base = execution[0].base
        engine_config = tmp_path / "engine.json"
        engine_config.write_text(
            json.dumps(
                {
                    "mode": "simulation",
                    "engine_actor": "engine",
                    "poll_s": 0.1,
                    "artifact_root": str(tmp_path / "objects"),
                    "execution_skills": base.skills,
                    "policy_versions": base.policy_versions,
                    "capability_versions": base.capability_versions,
                    "gateway_transport": {
                        "signing_key_file": str(tmp_path / "signing.key"),
                        "endpoints": {
                            "gw": {
                                "url": client.origin.geturl(),
                                "heartbeat_key_file": str(heartbeat_key),
                            }
                        },
                    },
                }
            )
        )

        def start():
            log_path = tmp_path / f"engine-{len(children)}.log"
            with log_path.open("wb") as log:
                child = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "alap.adapters.engine.server",
                        "--config",
                        str(engine_config),
                    ],
                    env={
                        **os.environ,
                        "ALAP_DATABASE_URL": make_conninfo(
                            execution[4][3], application_name="edge-" + tmp_path.name
                        ),
                    },
                    stdout=log,
                    stderr=log,
                )
            children.append(child)
            return child, log_path

        try:
            yield store, start, client, Authenticator(heartbeat_key.read_bytes())
        finally:
            for child in children:
                if child.poll() is None:
                    child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                    pytest.fail("Engine failed to stop")


def test_continuous_acquisition_supervised_and_complete(supervised, execution):  # noqa: F811
    store, start, _, _ = supervised
    child, log = start()
    dsn = execution[4][3]
    until(lambda: rows(dsn, "SELECT state FROM runs")[0]["state"] == "SUCCEEDED")
    assert child.poll() is None, log.read_text()
    state = store.snapshot()
    assert state["mode"] == "WAITING"
    assert state["sequence"] >= 5  # Acquisition exceeded loss deadline, sustained by real pulses.
    assert state["outputs"]["sim-smu"] == 0
    assert not any(event["kind"] == "loss_latched" for event in state["events"])
    assert rows(dsn, "SELECT state FROM datasets")[0]["state"] == "COMMITTED"
    commands = rows(dsn, "SELECT id FROM command_ledger")
    assert len(commands) == 3
    assert all(execution[2].action_count(row["id"]) == 1 for row in commands)


@pytest.mark.parametrize("fault", ["kill", "database_owner_loss"])
def test_engine_kill_interrupts_actual_scan_and_restart_only_reconciles(
    supervised,
    execution,  # noqa: F811
    tmp_path,
    fault,  # noqa: F811
):
    store, start, client, auth = supervised
    child, log = start()
    dsn = execution[4][3]
    until(lambda: store.snapshot()["outputs"]["sim-smu"] != 0)
    command = rows(dsn, "SELECT id FROM command_ledger WHERE instrument_id='sim-smu'")[0]["id"]
    # /rpc is busy with accept; independently authenticated monitoring remains available.
    with pytest.raises(ConnectionError):
        client._call("edge_status", {"command_id": command}, path="/supervision")
    status = client._call(
        "edge_status", {"command_id": command}, path="/supervision", authenticator=auth
    )
    assert status["mode"] == "ARMED"
    if fault == "kill":
        child.kill()
        child.wait(timeout=10)
    else:
        with psycopg.connect(dsn, autocommit=True) as db:
            victims = db.execute(
                "SELECT pid FROM pg_stat_activity WHERE application_name=%s",
                ("edge-" + tmp_path.name,),
            ).fetchall()
            assert len(victims) == 1
            assert db.execute("SELECT pg_terminate_backend(%s)", victims[0]).fetchone()[0]
        assert child.wait(timeout=10) == 1
        assert "ENGINE_OWNERSHIP_LOST" in log.read_text()
    until(lambda: store.snapshot()["mode"] == "TRIPPED")

    def result_persisted():
        with execution[2].connect() as db:
            return db.execute(
                "SELECT 1 FROM actions WHERE command_id=? AND result IS NOT NULL", (command,)
            ).fetchone()

    until(result_persisted)
    result = execution[2].durable_result(command)
    assert result["kind"] == "edge_interrupted"
    assert result["artifact"] is None and result["samples"] == []
    assert result["partial_points"] > 0
    assert store.snapshot()["outputs"]["sim-smu"] == 0
    restarted, log = start()
    until(
        lambda: (
            rows(dsn, "SELECT state FROM command_ledger WHERE id=%s", (command,))[0]["state"]
            == "FAILED_CONFIRMED"
        )
    )
    until(lambda: "EDGE_LATCHED" in log.read_text())
    assert rows(dsn, "SELECT state FROM runs")[0]["state"] == "PAUSED"
    assert (
        rows(dsn, "SELECT state FROM tasks WHERE definition->>'resource_id'='sim-smu'")[0]["state"]
        == "FAILED"
    )
    assert rows(dsn, "SELECT * FROM datasets") == []
    assert rows(dsn, "SELECT mode FROM control_generation")[0]["mode"] == "RECOVERING"
    assert execution[2].action_count(command) == 1
    time.sleep(0.3)
    assert restarted.poll() is None
    assert store.snapshot()["mode"] == "TRIPPED"
    assert execution[2].action_count(command) == 1


def test_wrong_engine_heartbeat_key_interrupts_and_centrally_pauses(
    supervised,
    execution,  # noqa: F811
    tmp_path,  # noqa: F811
):
    store, start, _, _ = supervised
    config = tmp_path / "engine.json"
    value = json.loads(config.read_text())
    wrong = tmp_path / "wrong-heartbeat.key"
    wrong.write_bytes(secrets.token_bytes(32))
    value["gateway_transport"]["endpoints"]["gw"]["heartbeat_key_file"] = str(wrong)
    config.write_text(json.dumps(value))
    child, log = start()
    dsn = execution[4][3]
    until(lambda: rows(dsn, "SELECT state FROM runs")[0]["state"] == "PAUSED")
    assert child.poll() is None, log.read_text()
    assert store.snapshot()["mode"] == "TRIPPED"
    assert store.snapshot()["outputs"]["sim-smu"] == 0
    assert (
        rows(dsn, "SELECT state FROM command_ledger WHERE instrument_id='sim-smu'")[0]["state"]
        == "FAILED_CONFIRMED"
    )
    assert rows(dsn, "SELECT * FROM datasets") == []


def test_gateway_kill_preserves_partial_action_for_explicit_recovery(
    supervised,
    execution,  # noqa: F811
    remote,  # noqa: F811
):
    store, start, _, _ = supervised
    child, _ = start()
    dsn = execution[4][3]
    until(lambda: store.snapshot()["outputs"]["sim-smu"] != 0)
    command = rows(dsn, "SELECT id FROM command_ledger WHERE instrument_id='sim-smu'")[0]["id"]
    child.kill()
    child.wait(timeout=10)
    remote.process.kill()
    remote.process.wait(timeout=10)
    until(lambda: store.snapshot()["mode"] == "TRIPPED")
    assert store.snapshot()["outputs"]["sim-smu"] == 0
    service = execution[0]
    service.mark_unknown("engine", command)
    with remote():
        service.reconcile("engine", command, recover_gateway=True)
        assert rows(dsn, "SELECT state FROM runs")[0]["state"] == "PAUSED"
        assert (
            rows(dsn, "SELECT state FROM command_ledger WHERE id=%s", (command,))[0]["state"]
            == "FAILED_CONFIRMED"
        )
        assert rows(dsn, "SELECT * FROM datasets") == []
        result = execution[2].durable_result(command)
        assert result["kind"] == "edge_interrupted" and result["partial_points"] is None
        service.reconcile("engine", command, recover_gateway=True)
        assert execution[2].action_count(command) == 1
