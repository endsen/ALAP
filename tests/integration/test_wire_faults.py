"""D12d.3 socket faults between independent Engine and Gateway processes.

The proxy cuts a TCP response, never patches a production transport or state machine.
Loopback HTTP is an explicit local simulation boundary; deployed mTLS is a separate gate.
"""

import http.client
import json
import socket
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from .conftest import rows
from .test_engine_process import processes, until  # noqa: F401
from .test_execution import execution  # noqa: F401
from .test_gateway_process import remote  # noqa: F401

pytestmark = pytest.mark.postgres


@contextmanager
def cut_proxy(client, after_execution):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            self.connection.settimeout(10)
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            rpc = client.auth.open(json.loads(raw))
            accept = rpc["operation"] == "accept"
            if accept:
                self.server.accepts.append(rpc["body"])
            cut = accept and len(self.server.accepts) == 1
            if not cut or after_execution:
                upstream = http.client.HTTPConnection(
                    client.origin.hostname, client.origin.port, timeout=10
                )
                try:
                    upstream.request("POST", "/rpc", raw, {"Content-Type": "application/json"})
                    response = upstream.getresponse()
                    status, body = response.status, response.read()
                finally:
                    upstream.close()
            if cut:
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                self.close_connection = True
                self.server.cut.set()
                return
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.accepts, server.cut = [], threading.Event()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


@pytest.mark.parametrize("after_execution", [False, True], ids=["before-forward", "lost-response"])
def test_actual_socket_cut_freezes_and_restart_never_replays(
    processes,  # noqa: F811
    execution,  # noqa: F811
    tmp_path,
    after_execution,
):
    start, _, _, _ = processes
    engine, _, simulator, _, scenario = execution
    dsn = scenario[3]
    client = engine.gateways["gw"]
    with cut_proxy(client, after_execution) as proxy:
        path = tmp_path / "engine.json"
        config = json.loads(path.read_text())
        config["gateway_transport"]["endpoints"]["gw"]["url"] = (
            f"http://127.0.0.1:{proxy.server_port}"
        )
        path.write_text(json.dumps(config))
        child, _ = start()
        assert proxy.cut.wait(20), "Fault was not admitted"
        until(lambda: rows(dsn, "SELECT state FROM runs")[0]["state"] == "UNKNOWN")
        commands = rows(dsn, "SELECT id,state FROM command_ledger")
        assert len(commands) == 1 and commands[0]["state"] == "UNKNOWN"
        identity = commands[0]["id"]
        assert simulator.action_count(identity) == int(after_execution)
        assert rows(dsn, "SELECT * FROM datasets") == []
        time.sleep(2.2)  # Observe more than two scheduling ticks, not a long-duration test.
        assert len(proxy.accepts) == 1
        if after_execution:
            # Re-delivery through the real Gateway RPC returns the durable result only.
            result = engine.auth.open(client.accept(proxy.accepts[0]))
            assert result["state"] == "SUCCEEDED"
            assert simulator.action_count(identity) == 1
        child.kill()
        child.wait(timeout=10)
        restarted, log = start()
        if after_execution:
            until(lambda: rows(dsn, "SELECT state FROM runs")[0]["state"] == "PAUSED")
            until(lambda: '"mode": "ACTIVE"' in log.read_text())
        else:
            until(lambda: "RECOVERING" in log.read_text())
            assert rows(dsn, "SELECT state FROM command_ledger")[0]["state"] == "UNKNOWN"
        time.sleep(2.2)
        assert restarted.poll() is None
        assert len(proxy.accepts) == 1
        assert len(rows(dsn, "SELECT id FROM command_ledger")) == 1
        assert simulator.action_count(identity) == int(after_execution)
        # Stop the worker before removing its network endpoint.
        restarted.terminate()
        assert restarted.wait(timeout=10) == 0
