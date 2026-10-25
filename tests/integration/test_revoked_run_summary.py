"""HTTP status-only views remain readable without releasing revoked knowledge."""

from copy import deepcopy

import psycopg
import pytest

from alap.domain.rules import DomainError

from .conftest import rows
from .test_agents import agents, call  # noqa: F401
from .test_api import api, get, send  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("terminal", [False, True])
def test_revoked_summary_masks_content_but_preserves_owner_scope(api, terminal):  # noqa: F811
    _, service, _, _, dsn, model = api
    runtime = service.runtime
    runtime.resources = service.resources
    service.registry.tools.update(service.resources.tools())
    doc = deepcopy(service.store.version("agent", "planner@1")["document"])
    doc["manifest"].update(version=2, context_policy="scoped_knowledge")
    doc["manifest"]["allowed_tools"].append("search_knowledge@1")
    service.registry.import_agent(doc)
    service.registry.publish_agent("planner@2", "owner")
    source_id = send(
        api,
        "POST",
        "/experiments/EXP-SIM-001/knowledge",
        {
            "source_id": "summary-guide",
            "version": 1,
            "kind": "document",
            "resources": doc["manifest"]["scoped_instruments"],
            "content": "private IV source sentinel",
            "source_uri": "alap:summary-secret",
        },
    ).json()["id"]
    run = runtime.start("owner", "EXP-SIM-001", "planner@2", "private goal sentinel")
    model.outputs = [[call("search_knowledge", {"query": "IV"})]]
    runtime.step("owner", run["id"])
    runtime.step("owner", run["id"])
    path = "/agent-runs/" + run["id"]
    assert get(api, path).json()["goal"] == "private goal sentinel"
    service.store.share_source("owner", source_id, "owner", revoked=True)
    if terminal:
        with pytest.raises(DomainError, match="SOURCE_REVOKED"):
            runtime.step("owner", run["id"])
    before = rows(dsn, "SELECT revision FROM agent_runs WHERE id=%s", (run["id"],))[0]
    response = get(api, path)
    assert response.status_code == 200, response.text
    view = response.json()
    assert view == {
        "id": run["id"],
        "experiment_id": "EXP-SIM-001",
        "definition_ref": "planner@2",
        "revision": before["revision"],
        "status": "FAILED" if terminal else "RUNNING",
        "goal": "内容不可访问",
        "result": None,
        "access_error": "SOURCE_REVOKED",
        "cancel_requested": False,
    }
    listed = get(api, "/experiments/EXP-SIM-001/agent-runs")
    assert listed.status_code == 200 and view in listed.json()["items"]
    assert "sentinel" not in response.text + listed.text
    for suffix in ("/trace", "/proposals"):
        denied = get(api, path + suffix)
        assert denied.status_code != 200
        assert denied.json()["error"]["code"] == "SOURCE_REVOKED"
        assert "sentinel" not in denied.text
    for actor in ("observer", "outsider"):
        assert get(api, path, actor).status_code == 403
    with psycopg.connect(dsn) as db:
        db.execute(
            "UPDATE experiment_memberships SET revoked_at=clock_timestamp() WHERE actor_id='owner'"
        )
    assert get(api, path).status_code == 403
    assert get(api, "/experiments/EXP-SIM-001/agent-runs").status_code == 403
    assert rows(dsn, "SELECT revision FROM agent_runs WHERE id=%s", (run["id"],))[0] == before
    assert len(model.requests) == 1
