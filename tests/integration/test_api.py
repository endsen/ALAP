"""D09 HTTP boundary against migrated PostgreSQL, no mocked authentication or database."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from alap.adapters.api.app import create_app
from alap.adapters.api.models import ModelManager
from alap.adapters.mcp.http import MCPConnection, StreamableHTTP
from alap.adapters.postgres.api import PostgresAPIStore
from alap.adapters.secrets.encrypted import EncryptedSecrets
from alap.application.agent_resources import AgentResources
from alap.application.api import APIService
from alap.domain.rules import DomainError
from tests.integration.conftest import rows
from tests.integration.test_agents import agents  # noqa: F401


@pytest.fixture
def api(agents, scenario):  # noqa: F811 - imported pytest fixture
    runtime, registry, model, document, example, dsn = agents
    base = scenario[0]
    store = PostgresAPIStore(dsn)
    runtime.store = registry.store = store
    vault = EncryptedSecrets(store, Fernet.generate_key())
    resources = AgentResources(
        store, base.catalog, lambda c: StreamableHTTP(c, vault), MCPConnection
    )
    manager = ModelManager(store, registry, vault)
    service = APIService(
        base,
        store,
        registry=registry,
        runtime=runtime,
        resources=resources,
        secrets=vault,
        configure=manager,
    )
    with psycopg.connect(dsn) as db:
        db.execute("INSERT INTO platform_roles VALUES ('owner','admin'),('outsider','researcher')")
    tokens = {
        actor: store.issue_token(actor) for actor in ("owner", "observer", "outsider", "approver")
    }
    app = create_app(service, replay_key=b"x" * 32, stream_seconds=0)
    client = TestClient(app)
    yield client, service, tokens, example, dsn, model
    client.close()


def auth(api, actor="owner"):
    return {"Authorization": "Bearer " + api[2][actor]}


def send(api, method, path, body=None, *, actor="owner", key=None, revision=None):
    headers = auth(api, actor) | {"Idempotency-Key": key or str(uuid4())}
    if revision is not None:
        headers["If-Match"] = f'"{revision}"'
    return api[0].request(method, "/api/v1" + path, json=body, headers=headers)


def get(api, path, actor="owner", **headers):
    return api[0].get("/api/v1" + path, headers=auth(api, actor) | headers)


def test_every_contract_operation_requires_real_bearer(api):
    for path, ops in api[0].app.openapi()["paths"].items():
        for method in ops:
            response = api[0].request(method, "/api/v1" + path)
            assert response.status_code == 401, (path, response.text)
            assert response.json()["error"]["request_id"]
            assert response.headers["www-authenticate"] == "Bearer"


def test_tokens_expiry_disable_and_revocation(api):
    assert get(api, "/me").status_code == 200
    with psycopg.connect(api[4]) as db:
        db.execute(
            "UPDATE api_tokens SET expires_at=clock_timestamp()-interval '1 second' "
            "WHERE actor_id='owner'"
        )
    assert get(api, "/me").status_code == 401
    api[2]["owner"] = api[1].store.issue_token("owner")
    api[1].store.revoke_tokens("owner")
    assert get(api, "/me").status_code == 401
    api[2]["owner"] = api[1].store.issue_token("owner")
    api[1].store.disable_principal("owner")
    assert get(api, "/me").status_code == 401
    raw = rows(api[4], "SELECT token_hash FROM api_tokens")
    assert all(r["token_hash"] != api[2]["owner"] for r in raw)


def test_experiments_authorization_pagination_and_etag(api):
    response = get(api, "/experiments/EXP-SIM-001")
    assert response.status_code == 200, response.text
    assert response.headers["etag"] == '"1"'
    assert get(api, "/experiments/EXP-SIM-001", "outsider").status_code == 403
    assert get(api, "/experiments", "outsider").json()["items"] == []
    assert get(api, "/experiments?limit=0").status_code == 422
    assert get(api, "/experiments?limit=1&limit=2").status_code == 422
    assert get(api, "/experiments?actor=owner").status_code == 422
    assert get(api, "/instruments").status_code == 200


def test_create_metadata_idempotency_and_body_conflict(api):
    body = {"title": "实验标题", "objective": "offline only", "sample_id": "sample"}
    first = send(api, "POST", "/experiments", body, key="create-one")
    assert first.status_code == 201, first.text
    assert first.json()["title"] == body["title"]
    assert send(api, "POST", "/experiments", body, key="create-one").json() == first.json()
    assert (
        send(api, "POST", "/experiments", body | {"title": "changed"}, key="create-one").status_code
        == 409
    )
    assert send(api, "POST", "/experiments", body, actor="observer").status_code == 403
    assert send(api, "POST", "/experiments", body | {"actor_id": "owner"}).status_code == 422


def test_approval_flow_exact_versions_no_physical_command(api):
    revision = deepcopy(api[3])
    response = send(api, "POST", "/experiments/EXP-SIM-001/proposals", revision, revision=1)
    assert response.status_code == 201, response.text
    saved = response.json()
    plan = rows(api[4], "SELECT * FROM plan_revisions")[0]
    body = {
        "plan_revision_id": plan["id"],
        "plan_hash": plan["plan_hash"],
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    response = send(
        api, "POST", "/experiments/EXP-SIM-001/approval-requests", body, revision=saved["revision"]
    )
    assert response.status_code == 201, response.text
    approval = response.json()
    decision = {"approval_id": approval["id"], "decision": "approve", "state_version": 0}
    assert (
        send(
            api,
            "POST",
            "/experiments/EXP-SIM-001/approvals",
            decision,
            actor="observer",
            revision=approval["revision"],
        ).status_code
        == 403
    )
    assert (
        send(api, "POST", "/experiments/EXP-SIM-001/approvals", decision, revision=0).status_code
        == 409
    )
    response = send(
        api,
        "POST",
        "/experiments/EXP-SIM-001/approvals",
        decision,
        actor="approver",
        revision=approval["revision"],
    )
    assert response.status_code == 201, response.text
    response = send(
        api,
        "POST",
        "/experiments/EXP-SIM-001/runs",
        {"approval_id": approval["id"]},
        revision=response.json()["revision"],
    )
    assert response.status_code == 202, response.text
    assert response.json()["state"] == "READY"
    assert rows(api[4], "SELECT * FROM command_ledger") == []


def test_management_role_and_skill_lifecycle(api):
    assert get(api, "/skills", "observer").status_code == 403
    listed = get(api, "/skills")
    assert listed.status_code == 200
    doc = deepcopy(listed.json()["items"][0]["document"])
    doc["version"] = 2
    created = send(api, "POST", "/skills", doc)
    assert created.status_code == 201, created.text
    ref = created.json()["ref"]
    published = send(api, "POST", f"/skills/{ref}/publish", key="publish-key")
    assert published.status_code == 200, published.text
    assert send(api, "POST", f"/skills/{ref}/publish", key="publish-key").json() == published.json()
    assert send(api, "POST", f"/skills/{ref}/disable").status_code == 200
    assert "canonical_bytes" not in listed.text


def test_credentials_encrypted_never_returned_and_cas(api):
    secret = "test-secret-" + uuid4().hex
    response = send(
        api, "PUT", "/credentials/provider", {"value": secret}, revision=-1, key="secret-key"
    )
    assert response.status_code == 200, response.text
    assert secret not in response.text
    assert api[1].secrets.resolve("provider") == secret
    ciphertext = bytes(rows(api[4], "SELECT ciphertext FROM api_credentials")[0]["ciphertext"])
    assert secret.encode() not in ciphertext
    assert secret not in get(api, "/credentials").text
    assert (
        send(api, "PUT", "/credentials/provider", {"value": "different"}, revision=-1).status_code
        == 409
    )
    assert (
        send(
            api, "PUT", "/credentials/provider", {"value": secret}, revision=0, actor="observer"
        ).status_code
        == 403
    )
    assert send(api, "POST", "/credentials/provider/disable", revision=0).status_code == 200
    with pytest.raises(DomainError):
        api[1].secrets.resolve("provider")
    assert secret not in json.dumps(rows(api[4], "SELECT * FROM api_requests"))


def test_connection_and_model_versions(api):
    send(api, "PUT", "/credentials/provider", {"value": "offline-key"}, revision=-1)
    connection = {
        "id": "deepseek",
        "version": 1,
        "vendor": "deepseek",
        "base_url": "https://api.deepseek.com",
        "secret_ref": "provider",
    }
    response = send(api, "POST", "/connections", connection)
    assert response.status_code == 201, response.text
    assert "secret_ref" not in get(api, "/connections").text
    assert (
        send(api, "POST", "/connections", connection | {"base_url": "http://127.0.0.1"}).status_code
        == 422
    )
    profile = {
        "id": "chat",
        "version": 1,
        "connection_id": "deepseek",
        "connection_version": 1,
        "model": "offline-name",
        "context_tokens": 32000,
        "output_tokens": 128,
        "capabilities": dict.fromkeys(
            ["streaming", "tools", "structured", "vision", "usage"], "declared"
        ),
    }
    response = send(api, "POST", "/models", profile)
    assert response.status_code == 201, response.text
    assert send(api, "POST", "/models", profile | {"output_tokens": 256}).status_code == 409
    assert send(api, "POST", "/models/chat@1/disable", revision=0).status_code == 200
    with pytest.raises(DomainError):
        api[1].configure.client("chat@1")


def test_agent_run_trace_usage_and_replay(api):
    response = send(
        api,
        "POST",
        "/agent-runs",
        {"experiment_id": "EXP-SIM-001", "definition_ref": "planner@1", "goal": "offline"},
        key="run-once",
    )
    assert response.status_code == 201, response.text
    identity = response.json()["id"]
    api[5].outputs = ["offline result"]
    response = send(api, "POST", f"/agent-runs/{identity}/advance", key="advance-once")
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "COMPLETED"
    assert (
        send(api, "POST", f"/agent-runs/{identity}/advance", key="advance-once").json()
        == response.json()
    )
    assert len(api[5].requests) == 1
    assert get(api, f"/agent-runs/{identity}", "observer").status_code == 403
    assert get(api, f"/agent-runs/{identity}/trace").status_code == 200
    usage = get(api, "/experiments/EXP-SIM-001/usage").json()
    assert usage["unknown_usage_completions"] == 1
    assert usage["estimated_cost"] is None
    assert get(api, "/experiments/EXP-SIM-001/usage", "outsider").status_code == 403


def test_sse_cursor_replay_and_resync(api):
    response = get(api, "/experiments/EXP-SIM-001/events")
    assert response.status_code == 200, response.text
    assert "id: 1\n" in response.text and ": heartbeat" in response.text
    response = get(api, "/experiments/EXP-SIM-001/events", **{"Last-Event-ID": "1"})
    assert "id:" not in response.text
    assert (
        get(api, "/experiments/EXP-SIM-001/events", **{"Last-Event-ID": "999"}).status_code == 409
    )
    assert (
        get(api, "/experiments/EXP-SIM-001/events?after=0", **{"Last-Event-ID": "1"}).status_code
        == 422
    )
    assert get(api, "/experiments/EXP-SIM-001/events", "outsider").status_code == 403


def test_membership_cas_delegation_and_revocation(api):
    body = {"role": "observer", "scope": {"resources": [], "risk_levels": []}, "revoked": True}
    assert (
        send(api, "PUT", "/experiments/EXP-SIM-001/members/observer", body, revision=0).status_code
        == 409
    )
    response = send(api, "PUT", "/experiments/EXP-SIM-001/members/observer", body, revision=1)
    assert response.status_code == 200, response.text
    assert get(api, "/experiments/EXP-SIM-001", "observer").status_code == 403
    body["scope"]["resources"] = ["outside"]
    assert (
        send(api, "PUT", "/experiments/EXP-SIM-001/members/outsider", body, revision=2).status_code
        == 403
    )


def test_unknown_inflight_request_not_replayed(api):
    body = {"title": "test", "sample_id": "sample", "objective": "test"}

    def fail(*args, **kwargs):
        raise RuntimeError("sensitive-debug-body")

    api[1].execute = fail
    first = send(api, "POST", "/experiments", body, key="crash-key")
    assert first.status_code == 500 and "sensitive" not in first.text
    again = send(api, "POST", "/experiments", body, key="crash-key")
    assert again.status_code == 409 and again.json()["error"]["code"] == "EXECUTION_UNKNOWN"


def test_bad_json_and_secret_errors_are_sanitized(api):
    response = api[0].post(
        "/api/v1/credentials/test",
        content='{"value":"secret","value":NaN}',
        headers=auth(api) | {"Content-Type": "application/json"},
    )
    # Wrong verb is still normalized; no framework input echo.
    assert response.status_code == 404
    response = api[0].put(
        "/api/v1/credentials/test",
        content='{"value":"secret","value":NaN}',
        headers=auth(api)
        | {
            "Content-Type": "application/json",
            "If-Match": '"-1"',
            "Idempotency-Key": "invalid-json",
        },
    )
    assert response.status_code == 422 and "secret" not in response.text
    assert get(api, "/does-not-exist").json()["error"]["code"] == "NOT_FOUND"


def test_current_role_checked_before_cached_admin_response(api):
    response = send(
        api, "PUT", "/credentials/test", {"value": "value"}, revision=-1, key="admin-retry"
    )
    assert response.status_code == 200
    with psycopg.connect(api[4]) as db:
        db.execute("DELETE FROM platform_roles WHERE actor_id='owner'")
    assert (
        send(
            api, "PUT", "/credentials/test", {"value": "value"}, revision=-1, key="admin-retry"
        ).status_code
        == 403
    )


def test_rate_limit_safe_envelope(api):
    app = create_app(api[1], replay_key=b"x" * 32, rate_limit=1)
    with TestClient(app) as client:
        assert client.get("/api/v1/me", headers=auth(api)).status_code == 200
        response = client.get("/api/v1/me", headers=auth(api))
        assert response.status_code == 429 and response.headers["retry-after"] == "60"


def test_knowledge_current_acl_on_repeated_search(api):
    source = {
        "source_id": "api-guide",
        "version": 1,
        "kind": "document",
        "resources": [],
        "content": "scoped knowledge text",
        "source_uri": "alap:api-test",
    }
    created = send(api, "POST", "/experiments/EXP-SIM-001/knowledge", source)
    assert created.status_code == 201, created.text
    identity = created.json()["id"]
    shared = send(
        api, "POST", f"/knowledge/{identity}/share", {"actor_id": "observer", "revoked": False}
    )
    assert shared.status_code == 200, shared.text
    body = {"experiment_id": "EXP-SIM-001", "query": "knowledge", "resources": []}
    result = send(api, "POST", "/knowledge/search", body, actor="observer", key="search-key")
    assert result.status_code == 200 and len(result.json()["items"]) == 1
    send(api, "POST", f"/knowledge/{identity}/share", {"actor_id": "observer", "revoked": True})
    result = send(api, "POST", "/knowledge/search", body, actor="observer", key="search-key")
    assert result.status_code == 200 and result.json()["items"] == []
    assert send(api, "POST", "/knowledge/search", body, actor="outsider").status_code == 403


def test_sse_rechecks_revoked_token_before_delivery(api, monkeypatch):
    original = api[1].store.authenticate
    calls = 0

    def authenticate(token):
        nonlocal calls
        calls += 1
        if calls == 2:
            api[1].store.revoke_tokens("owner")
        return original(token)

    monkeypatch.setattr(api[1].store, "authenticate", authenticate)
    response = get(api, "/experiments/EXP-SIM-001/events")
    assert response.status_code == 200
    assert "stream.error" in response.text and "UNAUTHENTICATED" in response.text
    assert "id: 1" not in response.text


def test_concurrent_api_create_only_one_effect(api):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(2)

    def create():
        barrier.wait(timeout=5)
        return send(
            api,
            "POST",
            "/experiments",
            {"title": "race", "sample_id": "sample", "objective": "race"},
            key="race-create",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: create(), range(2)))
    assert any(r.status_code == 201 for r in responses)
    assert all(r.status_code in {201, 409} for r in responses)
    assert len(rows(api[4], "SELECT id FROM experiments WHERE title='race'")) == 1


def test_failed_validation_body_not_cached_as_success(api):
    response = send(
        api,
        "POST",
        "/mcp",
        {"id": "invalid", "version": 1, "url": "http://127.0.0.1", "address": "127.0.0.1"},
    )
    assert response.status_code == 422, response.text
    assert (
        send(
            api,
            "POST",
            "/mcp",
            {
                "id": "invalid",
                "version": 1,
                "url": "http://127.0.0.1",
                "address": "127.0.0.1",
                "allow_loopback": True,
            },
        ).status_code
        == 422
    )
    response = send(api, "PUT", "/credentials/test", {"value": "a" * 1_048_577}, revision=-1)
    assert response.status_code == 422 and len(response.text) < 500


def test_samples_and_audit_redacted(api):
    response = send(api, "POST", "/samples", {"id": "new-sample", "metadata": {"title": "test"}})
    assert response.status_code == 201
    assert any(r["id"] == "new-sample" for r in get(api, "/samples").json()["items"])
    assert not any(
        r["id"] == "new-sample" for r in get(api, "/samples", "outsider").json()["items"]
    )
    audit = get(api, "/audit")
    assert audit.status_code == 200 and audit.json()["items"]
    assert get(api, "/audit", "observer").status_code == 403


def test_authenticated_responses_match_contract(api):
    from jsonschema import Draft202012Validator, FormatChecker

    contract = api[0].app.openapi()
    for path in [
        "/me",
        "/experiments",
        "/experiments/EXP-SIM-001",
        "/instruments",
        "/skills",
        "/agents",
        "/models",
        "/connections",
        "/credentials",
        "/mcp",
        "/audit",
        "/samples",
    ]:
        response = get(api, path)
        assert response.status_code == 200, (path, response.text)
        template = "/experiments/{experiment_id}" if path == "/experiments/EXP-SIM-001" else path
        schema = contract["paths"][template]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        Draft202012Validator(
            dict(schema, components=contract["components"]), format_checker=FormatChecker()
        ).validate(response.json())


from tests.integration.test_datasets import acquisition, execution, stage  # noqa: E402,F401
from tests.integration.test_resources import mcp_server  # noqa: E402,F401


def test_dataset_download_instrument_scope(api, acquisition):  # noqa: F811
    datasets = acquisition[0]
    identity = stage(acquisition)
    datasets.commit("engine", identity)
    api[1].datasets = datasets
    api[1].resources.datasets = datasets
    response = get(api, f"/datasets/{identity}/download")
    assert response.status_code == 200 and response.content.startswith(b"\x89HDF")
    assert "storage_key" not in get(api, f"/datasets/{identity}").text
    body = {"experiment_id": "EXP-SIM-001", "resources": api[3]["proposal"]["requested_resources"]}
    analyzed = send(api, "POST", f"/datasets/{identity}/analysis", body)
    assert analyzed.status_code == 200, analyzed.text
    with psycopg.connect(api[4]) as db:
        db.execute("UPDATE experiment_memberships SET scope='{}' WHERE actor_id='observer'")
    assert get(api, f"/datasets/{identity}/download", "observer").status_code == 403
    assert get(api, f"/datasets/{identity}", "outsider").status_code == 403


def test_mcp_discovery_grant_revocation_http(api, mcp_server):  # noqa: F811
    state, connection = mcp_server
    ref = api[1].resources.register_connection(connection)
    response = send(api, "POST", f"/mcp/{ref}/discover")
    assert response.status_code == 200, response.text
    identity = response.json()["tools"][0]
    assert rows(api[4], "SELECT * FROM mcp_grants") == []
    body = {
        "actor_id": "owner",
        "experiment_id": "EXP-SIM-001",
        "resources": api[3]["proposal"]["requested_resources"],
    }
    response = send(api, "POST", f"/mcp/tools/{identity}/grant", body)
    assert response.status_code == 200, response.text
    assert api[1].store.approved_tools() == [identity]
    response = send(api, "POST", f"/mcp/tools/{identity}/revoke", body)
    assert response.status_code == 200 and api[1].store.approved_tools() == []
    assert state.calls == []


def test_factory_assembled_service_and_real_http(api, tmp_path):
    import socket
    import threading
    import time

    import httpx
    import uvicorn

    from alap.adapters.api.bootstrap import build_service

    base = api[1].base
    settings = {
        "execution_skills": base.skills,
        "policy_versions": base.policy_versions,
        "capability_versions": base.capability_versions,
        "artifact_root": str(tmp_path),
        "engine_actor": "engine",
    }
    service = build_service(api[4], Fernet.generate_key(), settings)
    app = create_app(service, replay_key=b"z" * 32, stream_seconds=0)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        assert server.started
        response = httpx.get(
            f"http://127.0.0.1:{port}/api/v1/experiments", headers=auth(api), timeout=5
        )
        assert response.status_code == 200 and response.json()["items"]
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()


def test_scope_provision_and_run_control_cas(api, execution):  # noqa: F811
    from alap.application.control import ControlService

    engine, _, _, run, _ = execution
    api[1].control = ControlService(engine, engine_actor="engine")
    current = get(api, f"/runs/{run['id']}")
    assert current.status_code == 200, current.text
    version = current.json()["state_version"]
    path = f"/runs/{run['id']}/actions"
    assert send(api, "POST", path, {"action": "pause"}, revision=version + 10).status_code == 409
    paused = send(api, "POST", path, {"action": "pause"}, revision=version, key="pause-key")
    assert paused.status_code == 202, paused.text
    assert paused.json()["state"] == "PAUSED"
    assert (
        send(api, "POST", path, {"action": "pause"}, revision=version, key="pause-key").json()
        == paused.json()
    )
    assert rows(api[4], "SELECT * FROM command_ledger") == []
    exp = send(
        api,
        "POST",
        "/experiments",
        {"title": "new", "sample_id": "sample", "objective": "scope test"},
    ).json()
    body = {"resources": ["sim-temp"], "risk_levels": ["operator_review"]}
    scoped = send(api, "PUT", f"/experiments/{exp['id']}/scope", body, revision=exp["revision"])
    assert scoped.status_code == 200, scoped.text
    assert (
        send(
            api,
            "PUT",
            f"/experiments/{exp['id']}/scope",
            body,
            revision=scoped.json()["revision"],
            actor="observer",
        ).status_code
        == 403
    )
    member = rows(
        api[4], "SELECT scope FROM experiment_memberships WHERE experiment_id=%s", (exp["id"],)
    )[0]
    assert member["scope"] == body


def test_source_disable_and_registry_agent_publish(api):
    original = get(api, "/agents").json()["items"][0]["document"]
    document = deepcopy(original)
    document["manifest"]["version"] = 2
    assert send(api, "POST", "/agents", document).status_code == 201
    api[1].configure = None
    assert send(api, "POST", "/agents/planner@2/publish").status_code == 200
    assert send(api, "POST", "/agents/planner@2/disable").status_code == 200
    response = send(
        api,
        "POST",
        "/agent-runs",
        {"experiment_id": "EXP-SIM-001", "definition_ref": "planner@2", "goal": "disabled"},
    )
    assert response.status_code in {409, 422}
    doc = {
        "source_id": "disabled",
        "version": 1,
        "kind": "document",
        "resources": [],
        "content": "disabled knowledge",
        "source_uri": "alap:test",
    }
    source = send(api, "POST", "/experiments/EXP-SIM-001/knowledge", doc).json()["id"]
    assert len(get(api, "/experiments/EXP-SIM-001/knowledge").json()["items"]) == 1
    assert send(api, "POST", f"/knowledge/{source}/disable").status_code == 200
    assert get(api, "/experiments/EXP-SIM-001/knowledge").json()["items"] == []


def test_analysis_rechecks_scope_after_idempotent_retry(api, acquisition):  # noqa: F811
    data = acquisition[0]
    identity = stage(acquisition)
    data.commit("engine", identity)
    api[1].resources.datasets = data
    body = {"experiment_id": "EXP-SIM-001", "resources": api[3]["proposal"]["requested_resources"]}
    first = send(
        api, "POST", f"/datasets/{identity}/analysis", body, actor="observer", key="analysis-key"
    )
    assert first.status_code == 200, first.text
    with psycopg.connect(api[4]) as db:
        db.execute("UPDATE experiment_memberships SET scope='{}' WHERE actor_id='observer'")
    again = send(
        api, "POST", f"/datasets/{identity}/analysis", body, actor="observer", key="analysis-key"
    )
    assert again.status_code == 403


def test_agent_proposal_read_model_requires_run_owner(api):
    from tests.integration.test_agents import call, plan_args

    response = send(
        api,
        "POST",
        "/agent-runs",
        {"experiment_id": "EXP-SIM-001", "definition_ref": "planner@1", "goal": "offline plan"},
    )
    identity = response.json()["id"]
    api[5].outputs = [[call("propose_plan", plan_args(api[3], 1))], "done"]
    for _ in range(4):
        result = send(api, "POST", f"/agent-runs/{identity}/advance")
        assert result.status_code == 202, result.text
        if result.json()["status"] == "COMPLETED":
            break
    view = get(api, f"/agent-runs/{identity}").json()
    assert isinstance(view["result"], dict)
    assert len(view["result"]["proposal_ids"]) == 1
    proposals = get(api, f"/agent-runs/{identity}/proposals")
    assert proposals.status_code == 200 and len(proposals.json()["items"]) == 1
    assert proposals.json()["items"][0]["state"] == "PROPOSED"
    assert get(api, f"/agent-runs/{identity}/proposals", "observer").status_code == 403
    assert rows(api[4], "SELECT * FROM command_ledger") == []


def test_event_page_checks_resources_in_its_own_database_snapshot(api):
    result = send(api, "POST", "/experiments/EXP-SIM-001/proposals", deepcopy(api[3]), revision=1)
    assert result.status_code == 201
    with psycopg.connect(api[4]) as db:
        db.execute("UPDATE experiment_memberships SET scope='{}' WHERE actor_id='observer'")
    # Direct service check prevents a race after the HTTP stream's initial authorization.
    with pytest.raises(DomainError, match="FORBIDDEN"):
        api[1].events.after("observer", "EXP-SIM-001", 0)


def test_dashboard_and_usage_grouping_preserve_unknown(api):
    response = send(
        api,
        "POST",
        "/agent-runs",
        {"experiment_id": "EXP-SIM-001", "definition_ref": "planner@1", "goal": "offline"},
    )
    identity = response.json()["id"]
    api[5].outputs = ["result"]
    assert send(api, "POST", f"/agent-runs/{identity}/advance").status_code == 202
    response = get(api, "/experiments/EXP-SIM-001/dashboard")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["experiment"]["id"] == "EXP-SIM-001"
    assert data["approvals_by_state"] == {}
    group = data["usage"]["groups"][0]
    assert group["vendor"] == "offline" and group["agent_ref"] == "planner@1"
    assert group["recorded_attempts"] == 1 and group["unknown_usage"] == 1
    assert group["reported_tokens"] is None and group["estimated_cost"] is None
    assert get(api, "/experiments/EXP-SIM-001/dashboard", "outsider").status_code == 403


def test_workspace_scope_identity_and_plan_context(api):
    assert get(api, "/me").json() == {"id": "owner", "kind": "user", "role": "admin"}
    snapshot = get(api, "/experiments/EXP-SIM-001/snapshot").json()
    assert snapshot["permissions"]["write"] and snapshot["permissions"]["approve"]
    assert "plan_summaries" in snapshot
    observer = get(api, "/experiments/EXP-SIM-001/snapshot", "observer").json()
    assert not observer["permissions"]["write"]
    assert not observer["permissions"]["approve"]
    context = get(api, "/experiments/EXP-SIM-001/plan-context")
    assert context.status_code == 200
    assert context.json()["snapshot_version"] == snapshot["experiment"]["revision"]
    assert get(api, "/experiments/EXP-SIM-001/plan-context", "observer").status_code == 403
    assert get(api, "/experiments/EXP-SIM-001/available-agents", "outsider").status_code == 403
    assert get(api, "/experiments/EXP-SIM-001/available-agents").status_code == 200
