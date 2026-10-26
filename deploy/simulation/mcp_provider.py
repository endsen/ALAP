"""Loopback-only read MCP fixture; runs in the dedicated worker network namespace."""

import json
import time
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from alap.adapters.mcp.http import PROTOCOL

SPEC = {
    "name": "lookup",
    "description": "Untrusted local fixture",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "experiment_id": {"type": "string"},
            "instrument_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["experiment_id", "instrument_ids"],
        "additionalProperties": False,
    },
    "outputSchema": {
        "type": "object",
        "properties": {"value": {"type": "integer"}},
        "required": ["value"],
        "additionalProperties": False,
    },
    "annotations": {"readOnlyHint": True},
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert self.path == "/mcp" and self.headers["MCP-Protocol-Version"] == PROTOCOL
        method = request["method"]
        if method != "initialize":
            assert self.headers["MCP-Session-Id"] == "local-drill"
        if method == "notifications/initialized":
            self.send_response(202)
            self.end_headers()
            return
        if method == "initialize":
            result = {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "local-drill", "version": "1"},
            }
        elif method == "tools/list":
            spec = deepcopy(SPEC)
            if Path("/control/mcp-drift").exists():
                spec["outputSchema"]["properties"]["value"]["type"] = "string"
            result = {"tools": [spec]}
        elif method == "tools/call":
            assert request["params"]["name"] == "lookup"
            args = request["params"]["arguments"]
            assert args["experiment_id"].startswith("EXP-AGENT-")
            assert set(args["instrument_ids"]) == {"sim-temp", "sim-magnet", "sim-smu"}
            with (Path("/control") / (args["experiment_id"] + ".mcp-calls")).open("a") as log:
                log.write(json.dumps(args) + "\n")
            control = Path("/control")
            exp = args["experiment_id"]
            if (control / (exp + ".mcp-hold")).exists():
                (control / (exp + ".mcp-started")).touch()
                deadline = time.monotonic() + 50
                while not (control / (exp + ".mcp-release")).exists():
                    if time.monotonic() >= deadline:
                        raise TimeoutError("MCP fixture release deadline")
                    time.sleep(0.05)
            result = {"isError": False, "structuredContent": {"value": 3}, "content": []}
        else:
            raise AssertionError(method)
        body = json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("MCP-Session-Id", "local-drill")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8877), Handler)
    print("offline-mcp-ready", flush=True)
    server.serve_forever()
