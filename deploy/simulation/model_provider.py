"""Offline TLS/SSE provider for D12d.2. No database, tools, or external network calls."""

import json
import ssl
import time
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def response_chunks(payload, host, path, proposal):
    vendor = {"api.openai.com": "openai", "api.deepseek.com": "deepseek"}[host]
    limit = "max_completion_tokens" if vendor == "openai" else "max_tokens"
    other = "max_tokens" if vendor == "openai" else "max_completion_tokens"
    assert path == ("/v1/chat/completions" if vendor == "openai" else "/chat/completions")
    assert payload[limit] == 4096 and other not in payload
    assert payload["stream"] is True and payload["stream_options"] == {"include_usage": True}
    assert payload["model"] == "offline-" + vendor
    tools = {t["function"]["name"] for t in payload["tools"]}
    assert tools == {"read_snapshot", "propose_plan"}
    messages = payload["messages"]
    snapshots = [
        json.loads(m["content"].removeprefix("Authoritative scoped snapshot: "))
        for m in messages
        if m.get("content", "").startswith("Authoritative scoped snapshot: ")
    ]
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot["experiment_id"].startswith("EXP-AGENT-")
    assert not snapshot["unknown_commands"]
    # A real first tool round trip must precede the proposal; no fixture writes a plan.
    results = [m for m in messages if m["role"] == "tool"]
    if results:
        assert len(results) == 1 and results[0]["tool_call_id"] == "offline-read"
        assert messages[-2]["tool_calls"][0]["function"]["name"] == "read_snapshot"
        args = deepcopy(proposal)
        for key in ("proposal_id", "experiment_id", "source_agent_run_id"):
            args.pop(key, None)
        args["based_on_snapshot_version"] = snapshot["snapshot_version"]
        args["evidence_dataset_ids"] = []
        for task in args["tasks"]:
            for condition in task["preconditions"] + [task["success_condition"]]:
                if condition["kind"] == "stable_window":
                    condition["min_duration_s"] = 0.1
        name, call_id = "propose_plan", "offline-propose"
    else:
        args, name, call_id = {}, "read_snapshot", "offline-read"
    raw = json.dumps(args, ensure_ascii=False)
    # Split arguments across SSE chunks to exercise actual accumulation/validation.
    for index, part in enumerate((raw[: len(raw) // 2], raw[len(raw) // 2 :])):
        call = {"index": 0, "function": {"arguments": part}}
        if index == 0:
            call.update(id=call_id, type="function")
            call["function"]["name"] = name
        yield {
            "model": payload["model"],
            "choices": [{"index": 0, "delta": {"tool_calls": [call]}, "finish_reason": None}],
        }
    yield {
        "model": payload["model"],
        "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
    }
    yield {
        "model": payload["model"],
        "choices": [],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


def fault_chunks(chunks, mode):
    chunks = deepcopy(chunks)
    if mode == "unknown_tool":
        chunks[0]["choices"][0]["delta"]["tool_calls"][0]["function"]["name"] = "execute_device"
    if mode == "missing_usage":
        chunks = [chunk for chunk in chunks if "usage" not in chunk]
    if mode == "truncated":
        return chunks[:1], False
    return chunks, True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Never log credentials, goals, or complete model messages.

    def do_POST(self):
        self.connection.settimeout(15)
        try:
            assert self.headers.get("Authorization") == "Bearer offline-d12d2-only"
            length = int(self.headers["Content-Length"])
            assert 0 < length <= 262144
            payload = json.loads(self.rfile.read(length))
            chunks = list(
                response_chunks(payload, self.headers["Host"], self.path, self.server.proposal)
            )
        except AssertionError, ValueError, KeyError, TypeError:
            self.send_error(400, "Offline protocol check failed")
            return
        goals = [
            m.get("content", "")
            for m in payload["messages"]
            if m.get("content", "").startswith("D12D3:")
        ]
        mode = goals[0].splitlines()[0].removeprefix("D12D3:") if goals else "normal"
        if goals:
            snapshot = next(
                m["content"]
                for m in payload["messages"]
                if m.get("content", "").startswith("Authoritative scoped snapshot: ")
            )
            exp = json.loads(snapshot.split(": ", 1)[1])["experiment_id"]
            assert exp.replace("-", "").isalnum() and exp.startswith("EXP-AGENT-")
            control = Path("/control")
            with (control / (exp + ".requests")).open("a") as log:
                log.write(mode + "\n")
            if mode == "revoke_skill" and any(m["role"] == "tool" for m in payload["messages"]):
                (control / (exp + ".waiting")).touch()
                deadline = time.monotonic() + 20
                while not (control / (exp + ".release")).exists():
                    if time.monotonic() > deadline:
                        self.send_error(504, "Drill barrier timeout")
                        return
                    time.sleep(0.05)
        if mode == "rate_limit":
            self.send_error(429, "Offline rate limit")
            return
        chunks, done = fault_chunks(chunks, mode)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("x-request-id", "offline-d12d2")
        self.end_headers()
        for chunk in chunks:
            self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            self.wfile.flush()
        if done:
            self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        print(json.dumps({"model": payload["model"], "accepted": True}), flush=True)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 443), Handler)
    server.proposal = json.loads(Path("/app/contracts/examples/plan_revision.json").read_text())[
        "proposal"
    ]
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain("/drill/provider.crt", "/drill/provider.key")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print("offline-provider-ready", flush=True)
    server.serve_forever()
