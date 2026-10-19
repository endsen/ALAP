"""Opt-in synthetic DeepSeek smoke; credentials read without echo, never persisted.

Not part of CI. Produces metadata only. Executes no tools. Maximum three requests,
256 output tokens each, no retries. Uses the cheapest available named chat/flash
model from the authenticated catalog; refuses to guess an unknown model family.
"""

import getpass
import http.client
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from alap.adapters.llm.chat import ChatModelClient  # noqa: E402
from alap.application.models import (  # noqa: E402
    Capabilities,
    ModelProfile,
    ModelRequest,
    ProviderConnection,
    ToolDefinition,
)


def main():
    secret = os.environ.get("ALAP_DEEPSEEK_API_KEY") or getpass.getpass("DeepSeek API key: ")
    connection = http.client.HTTPSConnection("api.deepseek.com", timeout=20)
    try:
        connection.request("GET", "/models", headers={"Authorization": "Bearer " + secret})
        response = connection.getresponse()
        if response.status != 200:
            print(json.dumps({"catalog_status": response.status}))
            return 1
        catalog = json.loads(response.read(65536))
    finally:
        connection.close()
    available = {entry["id"] for entry in catalog["data"]}
    model = next((name for name in ("deepseek-chat", "deepseek-flash") if name in available), None)
    if model is None:
        print("No configured smoke model available; inspect official model documentation.")
        return 1

    class EphemeralSecret:
        def resolve(self, reference):
            return secret

    client = ChatModelClient(
        ProviderConnection("smoke", 1, "deepseek", "https://api.deepseek.com", "memory:smoke"),
        ModelProfile(
            "smoke",
            1,
            "smoke",
            1,
            model,
            32768,
            256,
            Capabilities("declared", "declared", "declared"),
            timeout_seconds=45,
        ),
        secrets=EphemeralSecret(),
    )
    schema = json.dumps(
        {
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
            "additionalProperties": False,
        }
    )
    cases = [
        (
            "text",
            ModelRequest(
                (("user", "Reply with ALAP_OK only. Synthetic connectivity test."),), "smoke-text"
            ),
        ),
        (
            "json",
            ModelRequest(
                (("user", 'Return only JSON: {"count": 2}. Synthetic test.'),),
                "smoke-json",
                output_schema_json=schema,
                json_object_mode=True,
            ),
        ),
        (
            "tools",
            ModelRequest(
                (
                    (
                        "user",
                        "Call propose_plan with count 2. Synthetic test; nothing will be executed.",
                    ),
                ),
                "smoke-tools",
                tools=(ToolDefinition("propose_plan", "Propose a synthetic plan", schema),),
            ),
        ),
    ]
    success = True
    for name, request in cases:
        events = list(client.stream(replace(request, total_seconds=50)))
        last = events[-1]
        passed = last.kind == "finish"
        if name == "json":
            passed = passed and last.data["structured"] == {"count": 2}
        if name == "tools":
            proposals = last.data.get("tool_proposals", [])
            passed = passed and len(proposals) == 1 and proposals[0]["arguments"] == {"count": 2}
        if name == "text":
            passed = passed and "ALAP_OK" in "".join(
                str(e.data["text"]) for e in events if e.kind == "text_delta"
            )
        print(
            json.dumps(
                {
                    "case": name,
                    "passed": passed,
                    "vendor": last.vendor,
                    "model": last.model,
                    "terminal": last.kind,
                    "code": last.data.get("code"),
                    "usage": last.data.get("usage"),
                    "elapsed_ms": last.data.get("elapsed_ms"),
                }
            ),
            flush=True,
        )
        success = success and passed
    return 0 if success else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # Do not print exception objects: transport errors can contain private data.
        print("Smoke failed before completion; no provider error body recorded.")
        raise SystemExit(1) from None
