"""Real bearer/role checks and independent monitor/Gateway/Engine maintenance recovery."""

# ruff: noqa: F811

import json
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from test_edge_process import monitor_process  # noqa: F401

from alap.adapters.api.app import create_app
from alap.adapters.postgres.api import PostgresAPIStore
from alap.application.api import APIService
from alap.application.edge_maintenance import EdgeMaintenanceService

from .conftest import rows
from .test_edge_execution import supervised  # noqa: F401
from .test_engine_process import until
from .test_execution import execution  # noqa: F401
from .test_gateway_process import remote  # noqa: F401

pytestmark = pytest.mark.postgres
PATH = "/api/v1/maintenance/gateways/gw/edge"


@pytest.fixture
def maintenance(supervised, execution):  # noqa: F811
    dsn = execution[4][3]
    store = PostgresAPIStore(dsn)
    with psycopg.connect(dsn) as db:
        db.execute("INSERT INTO platform_roles VALUES ('owner','admin'),('engine','admin')")
    tokens = {actor: store.issue_token(actor) for actor in ("owner", "observer", "engine")}
    service = APIService(
        execution[0].base, store, maintenance=EdgeMaintenanceService(execution[0], store)
    )
    with TestClient(create_app(service, replay_key=b"m" * 32)) as client:
        yield client, store, tokens


def get(maintenance, actor="owner"):
    client, _, tokens = maintenance
    return client.get(PATH, headers={"Authorization": "Bearer " + tokens[actor]})


def post(maintenance, review, *, key=None, actor="owner"):
    client, _, tokens = maintenance
    return client.post(
        PATH + "/acknowledgements",
        json=review,
        headers={
            "Authorization": "Bearer " + tokens[actor],
            "Idempotency-Key": key or str(uuid4()),
        },
    )


def review(maintenance):
    response = get(maintenance)
    assert response.status_code == 200, response.text
    state = response.json()
    return {k: state[k] for k in ("incident", "generation", "gateway_epoch", "policy_version")} | {
        "expected_outputs": state["outputs"],
        "reason": "Human reviewed simulated source zero and reconciled failure",
    }


def interrupted(supervised, execution):
    edge, start, _, _ = supervised
    child, _ = start()
    until(lambda: edge.snapshot()["outputs"]["sim-smu"] != 0)
    child.kill()
    child.wait(timeout=10)
    restarted, log = start()
    until(lambda: "EDGE_LATCHED" in log.read_text())
    assert rows(execution[4][3], "SELECT state FROM runs")[0]["state"] == "PAUSED"
    return restarted


def test_maintenance_is_human_admin_only_and_uses_separate_key(maintenance, supervised):
    assert maintenance[0].get(PATH).status_code == 401
    assert get(maintenance, "observer").status_code == 403
    assert get(maintenance, "engine").status_code == 403
    assert get(maintenance).status_code == 200
    _, _, port, heartbeat = supervised
    for auth in (port.auth, heartbeat):
        with pytest.raises(ConnectionError):
            port._call("edge_review", None, authenticator=auth, path="/maintenance")
    maintenance[1].disable_principal("owner")
    assert get(maintenance).status_code == 401


def test_review_acknowledgement_allows_handshake_but_never_resumes_old_run(
    maintenance,
    supervised,
    execution,  # noqa: F811
):
    restarted = interrupted(supervised, execution)
    body = review(maintenance)
    key = str(uuid4())
    response = post(maintenance, body, key=key)
    assert response.status_code == 200, response.text
    assert response.json()["execution_resumed"] is False
    assert post(maintenance, body, key=key).json() == response.json()
    dsn = execution[4][3]
    until(lambda: rows(dsn, "SELECT mode FROM control_generation")[0]["mode"] == "ACTIVE")
    assert rows(dsn, "SELECT state FROM runs")[0]["state"] == "PAUSED"
    assert rows(dsn, "SELECT * FROM datasets") == []
    assert supervised[0].snapshot()["outputs"]["sim-smu"] == 0
    assert supervised[0].snapshot()["mode"] == "WAITING"
    commands = rows(dsn, "SELECT id FROM command_ledger")
    assert len(commands) == 3
    assert all(execution[2].action_count(c["id"]) == 1 for c in commands)
    assert restarted.poll() is None
    ack = get(maintenance).json()["last_acknowledgement"]
    detail = json.loads(ack["detail"])
    assert (
        detail["operator"] == "owner"
        and detail["review"]["review_id"] == response.json()["review_id"]
    )
    assert rows(dsn, "SELECT * FROM api_audit WHERE operation='edgeAcknowledgementIntent'")
    with psycopg.connect(dsn) as db:
        db.execute("UPDATE platform_roles SET role='observer' WHERE actor_id='owner'")
    assert post(maintenance, body, key=key).status_code == 403


@pytest.mark.parametrize(
    "field", ["incident", "generation", "gateway_epoch", "policy_version", "expected_outputs"]
)
def test_stale_review_never_clears_latch(maintenance, supervised, execution, field):  # noqa: F811
    interrupted(supervised, execution)
    body = review(maintenance)
    body[field] = (
        {"sim-smu": 0, "sim-temp": 294, "sim-magnet": 0}
        if field == "expected_outputs"
        else str(uuid4())
    )
    response = post(maintenance, body)
    assert response.status_code in {409, 422}, response.text
    assert supervised[0].snapshot()["mode"] == "TRIPPED"
    assert not any(e["kind"] == "acknowledged" for e in supervised[0].snapshot()["events"])


def test_lost_ack_is_inspected_not_automatically_reissued(
    maintenance, supervised, execution, monkeypatch
):  # noqa: F811
    interrupted(supervised, execution)
    body, key = review(maintenance), str(uuid4())
    port = supervised[2]
    original = port.maintenance
    calls = []

    def lost(operation, value):
        result = original(operation, value)
        if operation == "edge_acknowledge":
            calls.append(value["review_id"])
            raise ConnectionError("Injected lost maintenance reply")
        return result

    monkeypatch.setattr(port, "maintenance", lost)
    assert post(maintenance, body, key=key).status_code == 500
    response = post(maintenance, body, key=key)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EXECUTION_UNKNOWN"
    detail = json.loads(get(maintenance).json()["last_acknowledgement"]["detail"])
    assert detail["review"]["review_id"] == calls[0]
    assert len(calls) == 1
    assert len([e for e in supervised[0].snapshot()["events"] if e["kind"] == "acknowledged"]) == 1


def test_audit_failure_prevents_acknowledgement(maintenance, supervised, execution, monkeypatch):  # noqa: F811
    interrupted(supervised, execution)
    body = review(maintenance)

    def fail(*args):
        raise OSError("Injected audit failure")

    monkeypatch.setattr(maintenance[1], "audit", fail)
    assert post(maintenance, body).status_code == 500
    assert supervised[0].snapshot()["mode"] == "TRIPPED"


def test_recovery_barrier_and_unresolved_command_gate(maintenance, supervised, execution):
    edge, start, _, _ = supervised
    child, _ = start()
    until(lambda: edge.snapshot()["outputs"]["sim-smu"] != 0)
    child.kill()
    child.wait(timeout=10)
    until(lambda: edge.snapshot()["mode"] == "TRIPPED")
    body = review(maintenance)
    response = post(maintenance, body)
    assert response.json()["error"]["code"] == "RECOVERY_REQUIRED"
    execution[0].begin_recovery("engine")
    execution[0].recover_inflight("engine")
    response = post(maintenance, body)
    assert response.status_code == 409 and response.json()["error"]["code"] == "EDGE_BUSY"
    assert edge.snapshot()["mode"] == "TRIPPED"
    assert (
        rows(execution[4][3], "SELECT * FROM api_audit WHERE operation='edgeAcknowledgementIntent'")
        == []
    )


def test_expired_raw_maintenance_authorization_does_not_clear_latch(
    maintenance, supervised, execution
):
    from datetime import UTC, datetime, timedelta

    from alap.domain.rules import DomainError

    interrupted(supervised, execution)
    body = review(maintenance)
    now = datetime.now(UTC)
    value = {
        "actor": "owner",
        "review_id": str(uuid4()),
        "central_epoch": str(uuid4()),
        "review": body,
        "issued_at": (now - timedelta(seconds=2)).isoformat(),
        "expires_at": (now - timedelta(seconds=1)).isoformat(),
    }
    with pytest.raises(DomainError, match="EDGE_REVIEW_EXPIRED"):
        supervised[2].maintenance("edge_acknowledge", value)
    assert supervised[0].snapshot()["mode"] == "TRIPPED"


def test_gateway_journal_blocks_ack_until_explicit_crash_reconciliation(
    maintenance, supervised, execution, remote
):
    from datetime import UTC, datetime, timedelta

    from alap.domain.rules import DomainError

    edge, start, port, _ = supervised
    child, _ = start()
    until(lambda: edge.snapshot()["outputs"]["sim-smu"] != 0)
    child.kill()
    child.wait(timeout=10)
    remote.process.kill()
    remote.process.wait(timeout=10)
    until(lambda: edge.snapshot()["mode"] == "TRIPPED")
    with remote():
        body = review(maintenance)
        now = datetime.now(UTC)
        value = {
            "actor": "owner",
            "review_id": str(uuid4()),
            "central_epoch": str(uuid4()),
            "review": body,
            "issued_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=10)).isoformat(),
        }
        with pytest.raises(DomainError, match="EDGE_BUSY"):
            port.maintenance("edge_acknowledge", value)
        restarted, log = start()
        until(lambda: '"mode": "RECOVERING"' in log.read_text())
        command = rows(
            execution[4][3], "SELECT id FROM command_ledger WHERE instrument_id='sim-smu'"
        )[0]["id"]
        execution[0].reconcile("engine", command, recover_gateway=True)
        response = post(maintenance, review(maintenance))
        assert response.status_code == 200, response.text
        until(
            lambda: (
                rows(execution[4][3], "SELECT mode FROM control_generation")[0]["mode"] == "ACTIVE"
            )
        )
        assert rows(execution[4][3], "SELECT state FROM runs")[0]["state"] == "PAUSED"
        assert execution[2].action_count(command) == 1
        assert restarted.poll() is None
