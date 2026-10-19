"""D11 console authorization, immutable versions and explicit synthetic model probes."""
# ruff: noqa: F811 - pytest imports fixtures by name

from copy import deepcopy

import pytest

from tests.integration.conftest import rows
from tests.integration.test_agents import agents  # noqa: F401
from tests.integration.test_api import api, get, send  # noqa: F401


def configure_model(api):
    service = api[1]
    service.secrets.put("console-key", "synthetic-not-a-provider-key", -1)
    service.configure(
        "connection",
        {
            "id": "console",
            "version": 1,
            "vendor": "openai",
            "base_url": "https://api.openai.com/v1",
            "secret_ref": "console-key",
        },
    )
    service.configure(
        "model",
        {
            "id": "console",
            "version": 1,
            "connection_id": "console",
            "connection_version": 1,
            "model": "synthetic",
            "context_tokens": 8192,
            "output_tokens": 256,
            "capabilities": {"streaming": "declared", "tools": "declared"},
        },
    )


@pytest.mark.parametrize(
    "path",
    ["/principals", "/settings", "/platform/tools", "/agents/planner@1", "/skills/iv_guidance@1"],
)
def test_console_admin_reads_do_not_leak_to_observer(api, path):
    assert get(api, path, "observer").status_code == 403
    assert get(api, path, "outsider").status_code == 403


def test_version_validation_does_not_publish_or_execute(api):
    configure_model(api)
    config = deepcopy(api[1].registry.store.version("agent", "planner@1")["document"])
    config["manifest"].update(agent_id="console", model_ref="console@1")
    assert send(api, "POST", "/agents", config).status_code == 201
    detail = get(api, "/agents/console@1").json()
    assert detail["state"] == "DRAFT" and "canonical_bytes" not in detail
    result = send(api, "POST", "/agents/console@1/validate")
    assert result.status_code == 200, result.text
    assert result.json()["execution"] == "not_executed"
    assert get(api, "/agents/console@1").json()["state"] == "DRAFT"
    assert api[5].requests == []
    assert send(api, "POST", "/agents/console@1/publish").status_code == 200
    config["manifest"]["max_iterations"] += 1
    assert send(api, "POST", "/agents", config).status_code == 409


def test_principal_role_compare_and_set_and_scope_independence(api):
    page = get(api, "/principals?limit=2").json()
    assert len(page["items"]) == 2 and page["next_cursor"]
    following = get(api, "/principals?limit=2&cursor=" + page["next_cursor"]).json()
    assert not {r["id"] for r in page["items"]} & {r["id"] for r in following["items"]}
    body = {"role": "researcher", "expected_role": "observer"}
    assert send(api, "POST", "/principals/observer/role", body, actor="observer").status_code == 403
    assert send(api, "POST", "/principals/observer/role", body).status_code == 200
    assert send(api, "POST", "/principals/observer/role", body).status_code == 409
    assert get(api, "/me", "observer").json()["role"] == "researcher"
    assert (
        rows(api[4], "SELECT role FROM experiment_memberships WHERE actor_id='observer'")[0]["role"]
        == "observer"
    )
    assert (
        send(
            api, "POST", "/principals/owner/role", {"role": "observer", "expected_role": "admin"}
        ).status_code
        == 403
    )
    assert rows(api[4], "SELECT * FROM api_audit WHERE operation='setPrincipalRole'")


def test_model_probe_is_explicit_bounded_and_idempotent(api, monkeypatch):
    configure_model(api)
    model = api[5]
    model.outputs = ["OK"]
    monkeypatch.setattr(api[1].configure, "client", lambda ref: model)
    assert send(api, "POST", "/models/console@1/test", actor="observer").status_code == 403
    assert model.requests == []
    result = send(api, "POST", "/models/console@1/test", key="console-probe")
    assert result.status_code == 200, result.text
    assert result.json()["success"] and result.json()["usage"] is None
    assert result.json()["estimated_cost"] is None
    assert result.json()["tested_capability"] == "text_stream_only"
    assert send(api, "POST", "/models/console@1/test", key="console-probe").json() == result.json()
    assert len(model.requests) == 1 and model.requests[0].messages == (("user", "Reply OK."),)
    assert model.requests[0].tools == () and model.profile.max_attempts == 1
    assert model.profile.output_tokens <= 32
    assert "synthetic-not-a-provider-key" not in get(api, "/audit").text


def test_settings_and_registry_details_only_public_metadata(api):
    settings = get(api, "/settings").json()
    assert settings["event_retention"] == "no_automatic_deletion"
    detail = get(api, "/agents/planner@1").json()
    assert set(detail) == {"ref", "state", "document", "content_hash", "publisher", "validated_at"}
    assert get(api, "/principals?limit=0").status_code == 422
    assert get(api, "/principals?limit=1&limit=2").status_code == 422
