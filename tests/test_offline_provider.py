"""Deployment provider requires bounded, scoped requests and a complete tool exchange."""

import json
from pathlib import Path

import pytest

from deploy.simulation.model_provider import response_chunks

PROPOSAL = json.loads(Path("contracts/examples/plan_revision.json").read_text())["proposal"]


def request(vendor):
    return {
        "model": "offline-" + vendor,
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_completion_tokens" if vendor == "openai" else "max_tokens": 4096,
        "messages": [
            {
                "role": "user",
                "content": "Authoritative scoped snapshot: "
                + json.dumps(
                    {
                        "experiment_id": "EXP-AGENT-test",
                        "snapshot_version": 7,
                        "unknown_commands": [],
                    }
                ),
            }
        ],
        "tools": [{"function": {"name": name}} for name in ("read_snapshot", "propose_plan")],
    }


def calls(payload, vendor):
    return list(
        response_chunks(
            payload,
            "api." + vendor + ".com",
            ("/v1" if vendor == "openai" else "") + "/chat/completions",
            PROPOSAL,
        )
    )


@pytest.mark.parametrize("vendor", ["openai", "deepseek"])
def test_fragmented_proposal_after_tool_exchange(vendor):
    payload = request(vendor)
    first = calls(payload, vendor)
    tool = first[0]["choices"][0]["delta"]["tool_calls"][0]
    assert tool["function"]["name"] == "read_snapshot"
    payload["messages"] += [
        {
            "role": "assistant",
            "tool_calls": [{"id": tool["id"], "function": {"name": "read_snapshot"}}],
        },
        {"role": "tool", "tool_call_id": tool["id"], "content": "{}"},
    ]
    second = calls(payload, vendor)
    parts = [c["choices"][0]["delta"]["tool_calls"][0] for c in second[:2]]
    assert parts[0]["function"]["name"] == "propose_plan"
    proposal = json.loads("".join(p["function"]["arguments"] for p in parts))
    assert proposal["based_on_snapshot_version"] == 7
    assert "proposal_id" not in proposal and "experiment_id" not in proposal
    assert len(proposal["tasks"]) == 3
    assert second[-2]["choices"][0]["finish_reason"] == "tool_calls"
    assert second[-1]["usage"]["total_tokens"] == 150


@pytest.mark.parametrize("change", ["limit", "physical_tool", "unknown", "unscoped", "orphan"])
def test_rejects_invalid_boundary(change):
    payload = request("openai")
    if change == "limit":
        payload["max_tokens"] = payload.pop("max_completion_tokens")
    elif change == "physical_tool":
        payload["tools"].append({"function": {"name": "execute_device"}})
    elif change in {"unknown", "unscoped"}:
        raw = payload["messages"][0]
        snapshot = json.loads(raw["content"].split(": ", 1)[1])
        snapshot["unknown_commands"] = ["unsafe"] if change == "unknown" else []
        if change == "unscoped":
            snapshot["experiment_id"] = "EXP-REAL"
        raw["content"] = "Authoritative scoped snapshot: " + json.dumps(snapshot)
    else:
        payload["messages"].append({"role": "tool", "tool_call_id": "orphan"})
    with pytest.raises((AssertionError, KeyError)):
        calls(payload, "openai")


@pytest.mark.parametrize("vendor", ["openai", "deepseek"])
@pytest.mark.parametrize("mode", ["knowledge_control", "knowledge_injection", "knowledge_revoke"])
def test_knowledge_requires_real_untrusted_tool_exchange(vendor, mode):
    from deploy.simulation.model_provider import KNOWLEDGE_TEXT

    payload = request(vendor)
    payload["tools"].append({"function": {"name": "search_knowledge"}})
    payload["messages"].append({"role": "user", "content": "D12D3:" + mode})
    first = calls(payload, vendor)
    tool = first[0]["choices"][0]["delta"]["tool_calls"][0]
    assert tool["function"]["name"] == "search_knowledge"
    payload["messages"] += [
        {
            "role": "assistant",
            "tool_calls": [{"id": tool["id"], "function": {"name": "search_knowledge"}}],
        },
        {
            "role": "tool",
            "tool_call_id": tool["id"],
            "content": json.dumps(
                {
                    "sources": [
                        {
                            "content": KNOWLEDGE_TEXT,
                            "trust": "untrusted_source_not_authority",
                            "reference": {"kind": "knowledge", "id": "source", "hash": "a" * 64},
                        }
                    ]
                }
            ),
        },
    ]
    second = calls(payload, vendor)
    if mode == "knowledge_injection":
        assert (
            second[0]["choices"][0]["delta"]["tool_calls"][0]["function"]["name"]
            == "execute_device"
        )
    else:
        assert (
            second[0]["choices"][0]["delta"]["content"]
            == "Scoped literature summary; no execution."
        )
    payload["messages"].insert(0, {"role": "system", "content": KNOWLEDGE_TEXT})
    with pytest.raises(AssertionError):
        calls(payload, vendor)


@pytest.mark.parametrize("mode", ["usage_negative", "usage_boolean", "usage_inconsistent"])
def test_invalid_usage_preserves_stream_and_original(mode):
    from deploy.simulation.model_provider import fault_chunks

    original = calls(request("openai"), "openai")
    before = json.dumps(original)
    changed, done = fault_chunks(original, mode)
    assert done
    assert json.dumps(original) == before
    assert changed[:-1] == original[:-1]
    usage = changed[-1]["usage"]
    if mode == "usage_negative":
        assert usage["prompt_tokens"] < 0
    elif mode == "usage_boolean":
        assert type(usage["prompt_tokens"]) is bool
    else:
        assert usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]


@pytest.mark.parametrize("vendor", ["openai", "deepseek"])
def test_retry_success_stream_is_read_only_and_has_one_usage_record(vendor):
    payload = request(vendor)
    payload["messages"].append({"role": "user", "content": "D12D3:retry_success"})
    chunks = calls(payload, vendor)
    assert chunks[0]["choices"][0]["delta"] == {"content": "Read-only retry result."}
    assert chunks[-2]["choices"][0]["finish_reason"] == "stop"
    assert sum("usage" in chunk for chunk in chunks) == 1
    assert chunks[-1]["usage"]["total_tokens"] == 150


@pytest.mark.parametrize("vendor", ["openai", "deepseek"])
def test_version_binding_requires_old_instruction_in_real_payload(vendor):
    payload = request(vendor)
    payload["messages"] += [
        {"role": "user", "content": "D12D3:version_pin"},
        {"role": "user", "content": "Skill reference guide@1 VERSION_PIN_OLD"},
    ]
    assert calls(payload, vendor)[-2]["choices"][0]["finish_reason"] == "stop"
    payload["messages"][-1]["content"] = "Skill reference guide@2 VERSION_PIN_NEW"
    with pytest.raises(AssertionError):
        calls(payload, vendor)
