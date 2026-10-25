"""Restricted revocation closure: ownership, authorization, atomicity and idempotency."""

import psycopg
import pytest

from alap.adapters.agents.langgraph import LangGraphAgentRunner
from alap.domain.rules import DomainError

from .conftest import rows
from .test_agents import agents, call  # noqa: F401
from .test_resources import publish, resources, scoped_run, source  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture
def referenced(resources):  # noqa: F811
    service, (runtime, _, model, _, _, dsn) = resources
    identity = source(resources)
    run = scoped_run(resources, publish(resources, ["search_knowledge@1"]))
    model.outputs = [[call("search_knowledge", {"query": "IV"})]]
    runner = LangGraphAgentRunner(runtime)
    runner.advance("owner", run["id"])
    runner.advance("owner", run["id"])
    return service, runtime, model, dsn, identity, run["id"]


def stored(dsn, identity):
    return rows(dsn, "SELECT checkpoint,revision FROM agent_runs WHERE id=%s", (identity,))[0]


@pytest.mark.parametrize(
    "case", ["no_owner", "wrong_actor", "revoked_member", "valid", "restored", "terminal"]
)
def test_closure_cannot_bypass_authority_or_rewrite_unrelated_runs(referenced, case):
    service, runtime, model, dsn, source_id, identity = referenced
    if case == "terminal":
        runtime.cancel("owner", identity)
    if case != "valid":
        service.store.share_source("owner", source_id, "owner", revoked=True)
    if case == "restored":
        service.store.share_source("owner", source_id, "owner", revoked=False)
    if case == "revoked_member":
        with psycopg.connect(dsn) as db:
            db.execute(
                "UPDATE experiment_memberships SET revoked_at=clock_timestamp() "
                "WHERE actor_id='owner'"
            )
    before = stored(dsn, identity)
    traces = rows(dsn, "SELECT * FROM agent_trace ORDER BY seq")
    if case == "no_owner":
        with pytest.raises(DomainError, match="RUN_BUSY"):
            runtime.store.fail_revoked_source("owner", identity)
    else:
        with runtime.store.exclusive(identity):
            if case in {"wrong_actor", "revoked_member"}:
                with pytest.raises(DomainError, match="FORBIDDEN"):
                    runtime.store.fail_revoked_source(
                        "observer" if case == "wrong_actor" else "owner", identity
                    )
            else:
                assert runtime.store.fail_revoked_source("owner", identity) is False
    assert stored(dsn, identity) == before
    assert rows(dsn, "SELECT * FROM agent_trace ORDER BY seq") == traces
    assert len(model.requests) == 1


def test_revocation_closure_rollback_and_retry_preserve_history(referenced):
    service, runtime, model, dsn, source_id, identity = referenced
    service.store.share_source("owner", source_id, "owner", revoked=True)
    before = stored(dsn, identity)
    # Reject the real audit INSERT in PostgreSQL; checkpoint and audit must roll back together.
    with psycopg.connect(dsn) as db:
        db.execute("""CREATE FUNCTION reject_closure() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN IF NEW.event->>'code'='SOURCE_REVOKED' THEN
          RAISE EXCEPTION 'closure audit unavailable'; END IF; RETURN NEW; END $$""")
        db.execute(
            "CREATE TRIGGER reject_closure BEFORE INSERT ON agent_trace "
            "FOR EACH ROW EXECUTE FUNCTION reject_closure()"
        )
    try:
        with pytest.raises(psycopg.errors.RaiseException, match="closure audit unavailable"):
            runtime.step("owner", identity)
        assert stored(dsn, identity) == before
    finally:
        with psycopg.connect(dsn) as db:
            db.execute("DROP TRIGGER reject_closure ON agent_trace")
            db.execute("DROP FUNCTION reject_closure()")
    with pytest.raises(DomainError, match="SOURCE_REVOKED"):
        runtime.step("owner", identity)
    after = stored(dsn, identity)
    assert after["revision"] == before["revision"] + 1
    expected = dict(
        before["checkpoint"], status="FAILED", stage="done", error="SOURCE_REVOKED", result=None
    )
    assert after["checkpoint"] == expected
    with pytest.raises(DomainError, match="SOURCE_REVOKED"):
        runtime.step("owner", identity)
    assert stored(dsn, identity) == after
    assert len(model.requests) == 1
    assert rows(dsn, "SELECT * FROM agent_proposals") == []
    service.store.share_source("owner", source_id, "owner", revoked=False)
    assert runtime.step("owner", identity)["checkpoint"]["status"] == "FAILED"
    assert stored(dsn, identity) == after
    assert len(model.requests) == 1


def test_dead_owner_cannot_reconnect_for_closure(referenced):
    service, runtime, _, dsn, source_id, identity = referenced
    service.store.share_source("owner", source_id, "owner", revoked=True)
    before = stored(dsn, identity)
    with runtime.store.exclusive(identity):
        session = runtime.store._owner.get()[1]
        with psycopg.connect(dsn, autocommit=True) as db:
            assert db.execute(
                "SELECT pg_terminate_backend(%s)", (session.info.backend_pid,)
            ).fetchone()[0]
        with pytest.raises(psycopg.OperationalError):
            runtime.store.fail_revoked_source("owner", identity)
    assert stored(dsn, identity) == before
