"""Authorized but invalid telemetry over HTTP must block successor dispatch.

Only isolated test keys sign the modified observations. This is a sensor fault,
not a test of breaking transport authentication or production mTLS.
"""

import http.client
import json
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from .conftest import rows
from .test_engine_process import processes, until  # noqa: F401
from .test_execution import execution  # noqa: F401
from .test_gateway_process import remote  # noqa: F401

pytestmark = pytest.mark.postgres


@contextmanager
def observation_proxy(client, mode):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            self.connection.settimeout(10)
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            request = client.auth.open(json.loads(raw))
            upstream = http.client.HTTPConnection(
                client.origin.hostname, client.origin.port, timeout=10
            )
            try:
                upstream.request("POST", "/rpc", raw, {"Content-Type": "application/json"})
                response = upstream.getresponse()
                status, body = response.status, response.read()
            finally:
                upstream.close()
            if request["operation"] == "accept":
                self.server.accepts.append(request["body"])
            if request["operation"] == "telemetry" and not self.server.released.is_set():
                envelope = client.auth.open(json.loads(body))
                observed = client.auth.open(envelope["result"])
                changed = False
                for window in observed["windows"]:
                    condition, samples = window["condition"], window["samples"]
                    resource = "sim-magnet" if mode == "off_target" else "sim-temp"
                    if condition["resource_id"] != resource:
                        continue
                    changed = True
                    if mode == "stale":
                        for sample in samples:
                            sample["observed_at"] = (
                                datetime.fromisoformat(sample["observed_at"])
                                - timedelta(seconds=60)
                            ).isoformat()
                    elif mode == "unstable":
                        samples[1]["value"] = condition["target"] + condition["tolerance"] / 2
                    else:
                        assert condition["target"] == 0
                        for sample in samples:
                            sample["value"] = condition["tolerance"] * 2
                if changed:
                    self.server.faults += 1
                    envelope["result"] = client.auth.seal(observed)
                    body = json.dumps(client.auth.seal(envelope)).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.accepts, server.faults, server.released = [], 0, threading.Event()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


@pytest.mark.parametrize(
    "mode,code,admitted",
    [
        ("stale", "READBACK_STALE", 1),
        ("unstable", "READBACK_UNSTABLE", 1),
        ("off_target", "READBACK_INVALID", 2),
    ],
)
def test_invalid_telemetry_blocks_successors_until_fresh(
    processes,  # noqa: F811
    execution,  # noqa: F811
    tmp_path,
    mode,
    code,
    admitted,
):
    start, _, _, _ = processes
    engine, _, simulator, _, scenario = execution
    dsn = scenario[3]
    with observation_proxy(engine.gateways["gw"], mode) as proxy:
        path = tmp_path / "engine.json"
        config = json.loads(path.read_text())
        config["gateway_transport"]["endpoints"]["gw"]["url"] = (
            f"http://127.0.0.1:{proxy.server_port}"
        )
        path.write_text(json.dumps(config))
        child, log = start()
        try:
            until(lambda: code in log.read_text())
            until(lambda: proxy.faults >= 3)
            commands = rows(dsn, "SELECT id,state FROM command_ledger")
            assert len(commands) == admitted == len(proxy.accepts)
            assert all(c["state"] == "SUCCEEDED" for c in commands)
            assert all(simulator.action_count(c["id"]) == 1 for c in commands)
            assert rows(dsn, "SELECT * FROM datasets") == []
            pending = rows(dsn, "SELECT plan_task_id FROM tasks WHERE state<>'SUCCEEDED'")
            assert {r["plan_task_id"] for r in pending} == (
                {"iv"} if admitted == 2 else {"field", "iv"}
            )
            assert child.poll() is None
            proxy.released.set()
            until(lambda: rows(dsn, "SELECT state FROM runs")[0]["state"] == "SUCCEEDED")
            until(lambda: rows(dsn, "SELECT * FROM resource_claims") == [])
            commands = rows(dsn, "SELECT id,state FROM command_ledger")
            assert len(commands) == len(proxy.accepts) == 3
            assert all(c["state"] == "SUCCEEDED" for c in commands)
            assert all(simulator.action_count(c["id"]) == 1 for c in commands)
            assert rows(dsn, "SELECT state FROM datasets") == [{"state": "COMMITTED"}]
        finally:
            child.terminate()
            assert child.wait(timeout=10) == 0
