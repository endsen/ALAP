"""D12: an independent Gateway owns persistent state across process restarts."""

import json
import secrets
import socket
import subprocess
import sys
import time
from contextlib import contextmanager

import pytest

from alap.adapters.gateway.auth import Authenticator
from alap.adapters.gateway.transport import HTTPGateway
from alap.adapters.storage.hdf5 import Hdf5Store
from alap.application.datasets import DatasetService
from alap.domain.rules import DomainError

from .conftest import rows
from .test_execution import execution, prepare  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture
def remote(execution, tmp_path):  # noqa: F811
    engine, gateway, simulator, run, scenario = execution
    gateway.close()
    key = secrets.token_bytes(32)
    key_file = tmp_path / "signing.key"
    key_file.write_bytes(key)
    key_file.chmod(0o600)
    engine.auth = Authenticator(key)
    config = tmp_path / "gateway.json"
    config.write_text(
        json.dumps(
            {
                "mode": "simulation",
                "gateway_id": "gw",
                "signing_key_file": str(key_file),
                "journal_path": str(gateway.path),
                "physical_path": str(simulator.path),
                "execution_skills": gateway.skills,
                "policy_versions": gateway.policies,
                "capability_versions": gateway.capabilities,
            }
        )
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    client = HTTPGateway("gw", f"http://127.0.0.1:{port}", engine.auth, timeout=5)
    engine.gateways = {"gw": client}

    @contextmanager
    def running():
        with (tmp_path / "gateway.log").open("ab") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "alap.adapters.gateway.server",
                    "--config",
                    str(config),
                    "--port",
                    str(port),
                ],
                stdout=log,
                stderr=log,
            )
            try:
                # Allow bounded cold-start time under shared CI/host load. This only
                # polls a read-only readiness challenge; it never retries device commands.
                deadline = time.monotonic() + 30
                while True:
                    assert process.poll() is None, (tmp_path / "gateway.log").read_text()
                    try:
                        client.challenge()
                        break
                    except ConnectionError:
                        if time.monotonic() > deadline:
                            pytest.fail(
                                "Gateway readiness timed out after 30 seconds; "
                                f"returncode={process.poll()}; "
                                f"log={(tmp_path / 'gateway.log').read_text()}"
                            )
                        time.sleep(0.05)
                yield client
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    pytest.fail("Gateway failed to stop within deadline")

    return running


def test_remote_three_devices_commit_and_restart(remote, execution, tmp_path):  # noqa: F811
    engine, _, simulator, run, scenario = execution
    with remote() as client:
        temperature = prepare(execution)
        engine.dispatch("engine", temperature)
        field = engine.prepare("engine", run["id"], "field")
        engine.dispatch("engine", field)
        iv = engine.prepare("engine", run["id"], "iv")
        engine.dispatch("engine", iv)
        receipt = rows(scenario[3], "SELECT id FROM gateway_receipts WHERE command_id=%s", (iv,))[
            0
        ]["id"]
        datasets = DatasetService(engine, Hdf5Store(tmp_path / "objects"))
        identity = datasets.stage("engine", iv, receipt)
        datasets.commit("engine", identity)
        datasets.finalize("engine", identity)
        assert engine.auth.open(client.query(iv))["state"] == "SUCCEEDED"
    with remote() as client:
        assert engine.auth.open(client.query(iv))["state"] == "SUCCEEDED"
        datasets.finalize("engine", identity)
        engine.release("engine", run["id"])
    assert rows(scenario[3], "SELECT state FROM runs")[0]["state"] == "SUCCEEDED"
    assert all(simulator.action_count(c) == 1 for c in (temperature, field, iv))


def test_lost_network_ack_reconcile_after_process_restart(remote, execution, monkeypatch):  # noqa: F811
    engine, _, simulator, _, scenario = execution
    with remote() as client:
        command = prepare(execution)
        accept = client.accept

        def lost_ack(signed):
            accept(signed)
            raise ConnectionError("Fault injected after server execution, before central receipt")

        with monkeypatch.context() as patch:
            patch.setattr(client, "accept", lost_ack)
            with pytest.raises(ConnectionError):
                engine.dispatch("engine", command)
        assert rows(scenario[3], "SELECT state FROM runs")[0]["state"] == "UNKNOWN"
    with remote():
        engine.reconcile("engine", command)
        assert rows(scenario[3], "SELECT state FROM runs")[0]["state"] == "PAUSED"
        with pytest.raises(DomainError):
            engine.dispatch("engine", command)
    assert simulator.action_count(command) == 1
