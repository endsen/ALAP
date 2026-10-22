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
