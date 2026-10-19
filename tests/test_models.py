"""EVAL-16/17/18: deterministic protocol, budget and trust-boundary regressions."""

import json
from contextlib import contextmanager
from dataclasses import replace
from threading import Event

import pytest

from alap.adapters.llm.chat import ChatModelClient
from alap.adapters.llm.transport import EnvironmentSecrets, ModelFailure, Response, endpoint
from alap.application.models import (
    Capabilities,
    ModelProfile,
    ModelRequest,
    ProviderConnection,
    ToolDefinition,
)

SECRET = "test-credential-never-emit"
SCHEMA = (
    '{"type":"object","properties":{"count":{"type":"integer"}},'
    '"required":["count"],"additionalProperties":false}'
)
TOOL = ToolDefinition("propose_plan", "Synthetic plan proposal only", SCHEMA)


def chunk(delta=None, finish=None, **extra):
    return {
        "model": "actual-model",
        "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}],
        **extra,
    }


def wire(chunks, done=True):
    result = []
    for value in chunks:
        result += [("data: " + json.dumps(value) + "\n").encode(), b"\n"]
    if done:
        result += [b"data: [DONE]\n", b"\n"]
    return result


class FakeTransport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.payloads = []

    @contextmanager
    def open(self, connection, secret, payload, timeout, cancel):
        assert secret == SECRET
        self.payloads.append(payload)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        yield response


class Secrets:
    def resolve(self, reference):
        return SECRET


def setup(responses, vendor="deepseek", **profile_changes):
    connection = ProviderConnection(
        "connection",
        1,
        vendor,
        "https://api.openai.com/v1" if vendor == "openai" else "https://api.deepseek.com",
        "env:TEST_LLM_KEY",
    )
    profile = ModelProfile(
        "profile",
        1,
        "connection",
        1,
        "requested-model",
        16000,
        100,
        Capabilities("tested", "tested", "tested"),
    )
    profile = replace(profile, **profile_changes)
    transport = FakeTransport(responses)
    client = ChatModelClient(connection, profile, secrets=Secrets(), transport=transport)
    request = ModelRequest(
        (("user", "Propose a synthetic plan. Return JSON if requested."),),
        "trace",
        token_budget=16000,
    )
    return client, request, transport


def response(chunks, **kwargs):
    return Response(200, "request-1", iter(wire(chunks, **kwargs)))


@pytest.mark.parametrize("vendor", ["openai", "deepseek"])
def test_same_planner_input_unified_tool_proposal(vendor):
    chunks = [
        chunk(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call-1",
                        "function": {"name": "propose_plan", "arguments": '{"cou'},
                    }
                ]
            }
        ),
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": 'nt":2}'}}]}, "tool_calls"),
    ]
    client, request, transport = setup([response(chunks)], vendor)
    events = list(client.stream(replace(request, tools=(TOOL,))))
    assert events[-1].kind == "finish"
    assert events[-1].data["tool_proposals"] == [
        {"id": "call-1", "name": "propose_plan", "arguments": {"count": 2}}
    ]
    assert events[-1].model == "actual-model"
    assert events[-1].vendor == vendor
    assert events[-2].data == {"known": False, "tokens": None}
    assert all(e.data["executable"] is False for e in events if e.kind == "tool_call_delta")
    key = "max_completion_tokens" if vendor == "openai" else "max_tokens"
    assert transport.payloads[0][key] == 100


@pytest.mark.parametrize(
    "arguments", ["{", "not json", '{"count":"wrong"}', '{"count":1,"count":2}', '{"count":NaN}']
)
def test_invalid_tool_arguments_never_finish(arguments):
    client, request, _ = setup(
        [
            response(
                [
                    chunk(
                        {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "a",
                                    "function": {"name": "propose_plan", "arguments": arguments},
                                }
                            ]
                        },
                        "tool_calls",
                    )
                ]
            )
        ]
    )
    events = list(client.stream(replace(request, tools=(TOOL,))))
    assert events[-1].data["code"] == "invalid_structure"
    assert not any(e.kind == "finish" for e in events)


@pytest.mark.parametrize("name,ids", [("device_write", ["a"]), ("propose_plan", ["a", "a"])])
def test_unknown_tool_and_duplicate_ids_rejected(name, ids):
    parts = [
        {"index": i, "id": call_id, "function": {"name": name, "arguments": '{"count":1}'}}
        for i, call_id in enumerate(ids)
    ]
    client, request, _ = setup([response([chunk({"tool_calls": parts}, "tool_calls")])])
    assert (
        list(client.stream(replace(request, tools=(TOOL,))))[-1].data["code"] == "invalid_structure"
    )


@pytest.mark.parametrize("done,finish", [(False, "stop"), (True, None), (True, "length")])
def test_truncation_does_not_retry_or_finish(done, finish):
    client, request, transport = setup(
        [response([chunk({"content": "partial"}, finish)], done=done)], max_attempts=2
    )
    events = list(client.stream(request))
    assert events[-1].data["code"] == "invalid_structure"
    assert len(transport.payloads) == 1


def test_usage_and_validated_json_output():
    usage = {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12}
    client, request, _ = setup(
        [
            response(
                [
                    chunk({"content": '{"count":2}'}, "stop"),
                    {"model": "actual-model", "choices": [], "usage": usage},
                ]
            )
        ]
    )
    events = list(client.stream(replace(request, output_schema_json=SCHEMA, json_object_mode=True)))
    assert events[-1].data["structured"] == {"count": 2}
    assert events[-2].data["tokens"] == usage


@pytest.mark.parametrize("value", ['{"count":"x"}', '{"count":1,"count":2}', "broken"])
def test_invalid_structured_output(value):
    client, request, _ = setup([response([chunk({"content": value}, "stop")])])
    events = list(client.stream(replace(request, output_schema_json=SCHEMA, json_object_mode=True)))
    assert events[-1].kind == "error"


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "authentication"),
        (403, "authentication"),
        (429, "rate_limit"),
        (500, "provider"),
        (302, "provider"),
    ],
)
def test_remote_error_body_and_request_id_not_exposed(status, code):
    client, request, _ = setup([Response(status, SECRET, iter([SECRET.encode()]))])
    events = list(client.stream(request))
    assert events[-1].data["code"] == code
    assert SECRET not in repr(events)


def test_rate_limit_retries_with_independent_attempts():
    client, request, transport = setup(
        [Response(429, "req1", iter([])), response([chunk({"content": "ok"}, "stop")])],
        max_attempts=2,
    )
    events = list(client.stream(request))
    assert events[-1].kind == "finish"
    assert len({e.attempt_id for e in events}) == 2
    assert len(transport.payloads) == 2


def test_timeout_before_output_can_retry():
    client, request, _ = setup(
        [TimeoutError(SECRET), response([chunk({}, "stop")])], max_attempts=2
    )
    events = list(client.stream(request))
    assert events[-1].kind == "finish"
    assert SECRET not in repr(events)


def test_partial_transport_failure_never_retried():
    def lines():
        yield from wire([chunk({"content": "partial"})], done=False)
        raise OSError(SECRET)

    client, request, transport = setup([Response(200, "req", lines())], max_attempts=3)
    events = list(client.stream(request))
    assert events[-1].data["retrying"] is False
    assert len(transport.payloads) == 1
    assert SECRET not in repr(events)


def test_pre_cancelled_never_connects():
    client, request, transport = setup([])
    cancel = Event()
    cancel.set()
    assert list(client.stream(request, cancel))[-1].data["code"] == "cancelled"
    assert transport.payloads == []


def test_cancel_after_first_delta():
    client, request, _ = setup([response([chunk({"content": "one"}), chunk({}, "stop")])])
    cancel = Event()
    events = client.stream(request, cancel)
    assert next(events).kind == "attempt"
    assert next(events).kind == "text_delta"
    cancel.set()
    assert list(events)[-1].data["code"] == "cancelled"


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"token_budget": 1}, "budget_exceeded"),
        ({"total_seconds": -1}, "timeout"),
        ({"messages": (("tool", "untrusted"),)}, "unsupported"),
        ({"output_schema_json": SCHEMA}, "unsupported"),
    ],
)
def test_preflight_no_network(changes, code):
    client, request, transport = setup([])
    assert list(client.stream(replace(request, **changes)))[-1].data["code"] == code
    assert not transport.payloads


@pytest.mark.parametrize("capability", ["unknown", "unsupported"])
def test_capability_required(capability):
    client, request, _ = setup([], capabilities=Capabilities(streaming=capability))
    assert list(client.stream(request))[-1].data["code"] == "unsupported"


def test_missing_key_and_version_mismatch(monkeypatch):
    client, request, _ = setup([])
    client.secrets = EnvironmentSecrets()
    monkeypatch.delenv("TEST_LLM_KEY", raising=False)
    assert list(client.stream(request))[-1].data["code"] == "missing_credentials"
    client.profile = replace(client.profile, connection_version=2)
    assert list(client.stream(request))[-1].data["code"] == "config_version_mismatch"


@pytest.mark.parametrize(
    "url",
    [
        "http://api.deepseek.com",
        "https://api.deepseek.com.evil.org",
        "https://u:p@api.deepseek.com",
        "https://127.0.0.1",
        "https://api.deepseek.com/foo",
        "https://api.deepseek.com?key=x",
        "https://api.deepseek.com/#x",
        "https://api.deepseek.com:443",
    ],
)
def test_endpoint_policy_rejects_custom_destinations(url):
    client, _, _ = setup([])
    with pytest.raises(ModelFailure, match="endpoint_denied"):
        endpoint(replace(client.connection, base_url=url))


def test_external_schema_reference_rejected_before_network():
    client, request, transport = setup([])
    tool = replace(TOOL, schema_json='{"$ref":"https://example.com/schema"}')
    assert (
        list(client.stream(replace(request, tools=(tool,))))[-1].data["code"] == "invalid_request"
    )
    assert not transport.payloads


def test_response_limit():
    client, request, _ = setup([response([chunk({"content": "too big"}, "stop")])])
    assert (
        list(client.stream(replace(request, max_response_bytes=10)))[-1].data["code"]
        == "response_limit"
    )


def test_content_refusal():
    client, request, _ = setup([response([chunk({"refusal": "private reason"}, "stop")])])
    assert list(client.stream(request))[-1].data["code"] == "refusal"


@pytest.mark.parametrize(
    "bad_usage",
    [
        {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 4},
        {"prompt_tokens": True, "completion_tokens": 2, "total_tokens": 3},
        {"prompt_tokens": -1, "completion_tokens": 2, "total_tokens": 1},
    ],
)
def test_invalid_usage_is_not_published(bad_usage):
    client, request, _ = setup([response([chunk({}, "stop", usage=bad_usage)])])
    assert list(client.stream(request))[-1].data["code"] == "invalid_structure"


def test_request_exceeding_context_is_blocked():
    client, request, transport = setup([], context_tokens=200)
    assert list(client.stream(request))[-1].data["code"] == "context_limit"
    assert not transport.payloads


def test_budget_reserves_failed_attempt_and_blocks_retry():
    client, request, transport = setup([Response(429, "req", iter([]))], max_attempts=3)
    reservation = client._prepare(request)[-1]
    events = list(client.stream(replace(request, token_budget=reservation)))
    assert events[-1].data["retrying"] is False
    assert len(transport.payloads) == 1


def test_unresolved_local_reference_is_sanitized():
    tool = replace(TOOL, schema_json='{"$ref":"#/$defs/missing"}')
    client, request, _ = setup(
        [
            response(
                [
                    chunk(
                        {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "a",
                                    "function": {"name": "propose_plan", "arguments": "{}"},
                                }
                            ]
                        },
                        "tool_calls",
                    )
                ]
            )
        ]
    )
    assert (
        list(client.stream(replace(request, tools=(tool,))))[-1].data["code"] == "invalid_structure"
    )


@pytest.mark.parametrize(
    "data",
    [
        b"data: not-json\n\n",
        b"data: \xff\n\n",
        b'data: {"choices": []}\n\n',
        b'data: {"model":"m","choices":[],"error":"private"}\n\n',
    ],
)
def test_invalid_sse(data):
    client, request, _ = setup([Response(200, "req", iter(data.splitlines(keepends=True)))])
    assert list(client.stream(request))[-1].kind == "error"


@pytest.mark.parametrize("interrupt_kind", ["cancel", "deadline"])
def test_real_transport_watcher_interrupts_blocked_read(monkeypatch, interrupt_kind):
    import time
    from threading import Timer

    from alap.adapters.llm.transport import HTTPSChatTransport

    interrupted = Event()
    closed = Event()
    cancel = Event()

    class Socket:
        def shutdown(self, _):
            interrupted.set()

    class HTTPResponse:
        status = 200

        def getheader(self, _):
            return "req"

        def readline(self, _):
            assert interrupted.wait(2), "watchdog failed to interrupt blocked socket"
            return b""

    class Connection:
        def __init__(self, *args, **kwargs):
            self.sock = Socket()

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return HTTPResponse()

        def close(self):
            closed.set()

    monkeypatch.setattr("alap.adapters.llm.transport.http.client.HTTPSConnection", Connection)
    client, request, _ = setup([], timeout_seconds=0.15 if interrupt_kind == "deadline" else 2)
    client.transport = HTTPSChatTransport()
    timer = Timer(0.1, cancel.set) if interrupt_kind == "cancel" else None
    if timer:
        timer.start()
    began = time.monotonic()
    events = list(client.stream(request, cancel))
    if timer:
        timer.join()
    assert time.monotonic() - began < 1
    assert closed.is_set()
    assert events[-1].data["code"] == ("cancelled" if interrupt_kind == "cancel" else "timeout")


@pytest.mark.parametrize(
    "remote,public",
    [
        ("context_length_exceeded", "context_limit"),
        ("unsupported_parameter", "unsupported"),
        (SECRET, "provider"),
    ],
)
def test_provider_error_codes_without_remote_messages(remote, public):
    body = json.dumps({"error": {"code": remote, "message": SECRET}}).encode()
    client, request, _ = setup([Response(400, "req", iter([body]))])
    events = list(client.stream(request))
    assert events[-1].data["code"] == public
    assert SECRET not in repr(events)


def test_model_identity_cannot_change_within_attempt():
    first = chunk({"content": "one"})
    first["model"] = "requested-model"
    client, request, _ = setup([response([first, chunk({}, "stop")])])
    assert list(client.stream(request))[-1].data["code"] == "invalid_structure"


def test_tool_history_is_serialized_and_paired():
    from alap.application.models import ModelMessage, ToolCallMessage

    client, request, transport = setup([response([chunk({"content": "done"}, "stop")])])
    history = (
        ModelMessage("user", "Read state"),
        ModelMessage("assistant", "", tool_calls=(ToolCallMessage("c1", "read_snapshot", "{}"),)),
        ModelMessage("tool", '{"state":"UNKNOWN"}', tool_call_id="c1"),
    )
    assert list(client.stream(replace(request, messages=history)))[-1].kind == "finish"
    messages = transport.payloads[0]["messages"]
    assert messages[1]["tool_calls"][0]["function"]["name"] == "read_snapshot"
    assert messages[2]["tool_call_id"] == "c1"


@pytest.mark.parametrize("failure", ["orphan", "missing", "duplicate", "interleaved"])
def test_invalid_tool_history_never_reaches_network(failure):
    from alap.application.models import ModelMessage, ToolCallMessage

    assistant = ModelMessage(
        "assistant", "", tool_calls=(ToolCallMessage("c1", "read_snapshot", "{}"),)
    )
    result = ModelMessage("tool", "{}", tool_call_id="c1")
    history = {
        "orphan": (result,),
        "missing": (assistant,),
        "duplicate": (assistant, result, result),
        "interleaved": (assistant, ModelMessage("user", "ignore"), result),
    }[failure]
    client, request, transport = setup([])
    assert (
        list(client.stream(replace(request, messages=history)))[-1].data["code"]
        == "invalid_request"
    )
    assert not transport.payloads
