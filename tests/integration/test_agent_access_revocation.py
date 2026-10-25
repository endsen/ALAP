"""Revoked submitter access closes only the owned run, without publishing pending output."""

from copy import deepcopy

import psycopg
import pytest

from alap.domain.rules import DomainError

from .conftest import rows
from .test_agents import agents, call, plan_args, start  # noqa: F401

pytestmark = pytest.mark.postgres


def checkpoint(dsn, identity):
    return rows(dsn, "SELECT checkpoint,revision FROM agent_runs WHERE id=%s", (identity,))[0]


def revoke(dsn, kind):
    with psycopg.connect(dsn) as db:
        if kind == "principal":
            db.execute("UPDATE principals SET disabled_at=clock_timestamp() WHERE id='owner'")
        elif kind == "membership":
            db.execute(
                "UPDATE experiment_memberships SET revoked_at=clock_timestamp() "
                "WHERE actor_id='owner'"
            )
        else:
            db.execute("UPDATE experiment_memberships SET scope='{}' WHERE actor_id='owner'")


def restore(dsn, scope):
    from psycopg.types.json import Jsonb

    with psycopg.connect(dsn) as db:
        db.execute("UPDATE principals SET disabled_at=NULL WHERE id='owner'")
        db.execute(
            "UPDATE experiment_memberships SET revoked_at=NULL,scope=%s WHERE actor_id='owner'",
            (Jsonb(scope),),
        )


@pytest.mark.parametrize("kind", ["principal", "membership", "scope"])
@pytest.mark.parametrize("phase", ["before", "inflight", "tools"])
def test_revoked_submitter_closes_without_output_or_replay(agents, monkeypatch, kind, phase):  # noqa: F811
    runtime, _, model, _, example, dsn = agents
    run = start(agents)
    scope = rows(dsn, "SELECT scope FROM experiment_memberships WHERE actor_id='owner'")[0]["scope"]
    model.outputs = [
        [
            call(
                "propose_plan",
                plan_args(example, run["checkpoint"]["snapshot"]["snapshot_version"]),
            )
        ]
    ]
    if phase == "tools":
        runtime.step("owner", run["id"])
    before = checkpoint(dsn, run["id"])
    if phase == "inflight":
        stream = model.stream

        def revoked_stream(request, cancel):
            revoke(dsn, kind)
            yield from stream(request, cancel)

        monkeypatch.setattr(model, "stream", revoked_stream)
    else:
        revoke(dsn, kind)
    with pytest.raises(DomainError, match="FORBIDDEN"):
        runtime.step("owner", run["id"])
    closed = checkpoint(dsn, run["id"])
    cp = closed["checkpoint"]
    assert cp["status"] == "FAILED" and cp["stage"] == "done"
    assert cp["error"] == "ACCESS_REVOKED" and cp["result"] is None
    assert cp["history"] == before["checkpoint"]["history"]
    assert cp["pending"] == before["checkpoint"]["pending"]
    assert cp["iterations"] == (0 if phase == "before" else 1)
    assert cp["reserved_tokens"] == (0 if phase == "before" else 32000)
    expected_stage = {"before": "model", "inflight": "inflight", "tools": "tools"}[phase]
    trace = rows(dsn, "SELECT event FROM agent_trace WHERE run_id=%s ORDER BY seq", (run["id"],))
    assert trace[-1]["event"] == {
        "type": "blocked",
        "code": "ACCESS_REVOKED",
        "prior_stage": expected_stage,
        "model_outcome_unknown": phase == "inflight",
    }
    assert len(model.requests) == (0 if phase == "before" else 1)
    for table in ("agent_tool_invocations", "agent_proposals", "command_ledger"):
        assert rows(dsn, "SELECT * FROM " + table) == []
    with pytest.raises(DomainError, match="FORBIDDEN"):
        runtime.store.load("owner", run["id"])
    # Repeated attempts and later re-grant cannot resume or duplicate terminal audit.
    with pytest.raises(DomainError, match="FORBIDDEN"):
        runtime.step("owner", run["id"])
    assert checkpoint(dsn, run["id"]) == closed
    restore(dsn, scope)
    assert runtime.step("owner", run["id"])["checkpoint"] == cp
    assert len(model.requests) == (0 if phase == "before" else 1)
    assert (
        rows(dsn, "SELECT event FROM agent_trace WHERE run_id=%s ORDER BY seq", (run["id"],))
        == trace
    )


def test_wrong_actor_cannot_close_another_revoked_run(agents):  # noqa: F811
    runtime, *_, dsn = agents
    run = start(agents)
    revoke(dsn, "membership")
    before = checkpoint(dsn, run["id"])
    with pytest.raises(DomainError, match="FORBIDDEN"):
        runtime.step("observer", run["id"])
    assert checkpoint(dsn, run["id"]) == before


def test_access_closure_needs_original_ownership_and_current_revocation(agents):  # noqa: F811
    runtime, *_, dsn = agents
    run = start(agents)
    before = checkpoint(dsn, run["id"])
    with pytest.raises(DomainError, match="RUN_BUSY"):
        runtime.store.fail_revoked_access("owner", run["id"])
    with runtime.store.exclusive(run["id"]):
        assert runtime.store.fail_revoked_access("owner", run["id"]) is False
    assert checkpoint(dsn, run["id"]) == before


def test_late_revocation_does_not_replace_completed_result(agents):  # noqa: F811
    runtime, _, model, *_, dsn = agents
    run = start(agents)
    model.outputs = ["completed result"]
    runtime.step("owner", run["id"])
    before = deepcopy(checkpoint(dsn, run["id"]))
    revoke(dsn, "membership")
    with pytest.raises(DomainError, match="FORBIDDEN"):
        runtime.step("owner", run["id"])
    assert checkpoint(dsn, run["id"]) == before


@pytest.mark.parametrize("kind", ["principal", "membership", "scope"])
def test_revocation_at_tool_commit_discards_proposal_and_ledger(agents, monkeypatch, kind):  # noqa: F811
    runtime, _, model, _, example, dsn = agents
    run = start(agents)
    model.outputs = [
        [
            call(
                "propose_plan",
                plan_args(example, run["checkpoint"]["snapshot"]["snapshot_version"]),
            )
        ]
    ]
    runtime.step("owner", run["id"])
    before = checkpoint(dsn, run["id"])
    commit = runtime.store.commit

    def revoke_at_publish(run, cp, event, **kwargs):
        if kwargs.get("proposals"):
            revoke(dsn, kind)
        return commit(run, cp, event, **kwargs)

    monkeypatch.setattr(runtime.store, "commit", revoke_at_publish)
    with pytest.raises(DomainError, match="FORBIDDEN"):
        runtime.step("owner", run["id"])
    cp = checkpoint(dsn, run["id"])["checkpoint"]
    assert cp == dict(
        before["checkpoint"], status="FAILED", stage="done", error="ACCESS_REVOKED", result=None
    )
    for table in ("agent_tool_invocations", "agent_proposals", "command_ledger"):
        assert rows(dsn, "SELECT * FROM " + table) == []


def test_access_closure_audit_failure_rolls_back_checkpoint(agents):  # noqa: F811
    runtime, *_, dsn = agents
    run = start(agents)
    revoke(dsn, "membership")
    before = checkpoint(dsn, run["id"])
    with psycopg.connect(dsn) as db:
        db.execute("""CREATE FUNCTION reject_access_closure() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN IF NEW.event->>'code'='ACCESS_REVOKED' THEN
          RAISE EXCEPTION 'access closure audit unavailable'; END IF; RETURN NEW; END $$""")
        db.execute(
            "CREATE TRIGGER reject_access_closure BEFORE INSERT ON agent_trace "
            "FOR EACH ROW EXECUTE FUNCTION reject_access_closure()"
        )
    try:
        with pytest.raises(psycopg.errors.RaiseException, match="access closure audit unavailable"):
            runtime.step("owner", run["id"])
        assert checkpoint(dsn, run["id"]) == before
    finally:
        with psycopg.connect(dsn) as db:
            db.execute("DROP TRIGGER reject_access_closure ON agent_trace")
            db.execute("DROP FUNCTION reject_access_closure()")
    with pytest.raises(DomainError, match="FORBIDDEN"):
        runtime.step("owner", run["id"])
    assert checkpoint(dsn, run["id"])["revision"] == before["revision"] + 1


def test_lost_session_cannot_reconnect_to_close_revoked_access(agents):  # noqa: F811
    runtime, *_, dsn = agents
    run = start(agents)
    revoke(dsn, "membership")
    before = checkpoint(dsn, run["id"])
    with runtime.store.exclusive(run["id"]):
        session = runtime.store._owner.get()[1]
        with psycopg.connect(dsn, autocommit=True) as db:
            assert db.execute(
                "SELECT pg_terminate_backend(%s)", (session.info.backend_pid,)
            ).fetchone()[0]
        with pytest.raises(psycopg.OperationalError):
            runtime.store.fail_revoked_access("owner", run["id"])
    assert checkpoint(dsn, run["id"]) == before


@pytest.mark.parametrize("phase", ["before", "inflight"])
def test_restored_grant_before_closure_never_fabricates_revocation(agents, monkeypatch, phase):  # noqa: F811
    runtime, _, model, *_, dsn = agents
    run = start(agents)
    scope = rows(dsn, "SELECT scope FROM experiment_memberships WHERE actor_id='owner'")[0]["scope"]
    model.outputs = ["read-only result"]
    if phase == "inflight":
        stream = model.stream

        def revoke_in_stream(request, cancel):
            revoke(dsn, "membership")
            yield from stream(request, cancel)

        monkeypatch.setattr(model, "stream", revoke_in_stream)
    else:
        revoke(dsn, "membership")
    close = runtime.store.fail_revoked_access

    def restore_before_close(actor, identity):
        restore(dsn, scope)
        return close(actor, identity)

    monkeypatch.setattr(runtime.store, "fail_revoked_access", restore_before_close)
    with pytest.raises(DomainError, match="FORBIDDEN"):
        runtime.step("owner", run["id"])
    cp = checkpoint(dsn, run["id"])["checkpoint"]
    assert cp["status"] == ("READY" if phase == "before" else "RUNNING")
    assert not rows(dsn, "SELECT * FROM agent_trace WHERE event->>'code'='ACCESS_REVOKED'")
    done = runtime.step("owner", run["id"])["checkpoint"]
    if phase == "before":
        assert done["status"] == "COMPLETED"
    else:
        assert done["status"] == "FAILED" and done["error"] == "MODEL_INTERRUPTED"
    assert len(model.requests) == 1
