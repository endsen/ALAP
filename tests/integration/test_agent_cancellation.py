"""Durable cancellation intent and atomic publication races on real PostgreSQL."""

import psycopg
import pytest

from alap.adapters.postgres.agents import PostgresAgentStore
from alap.domain.rules import DomainError

from .conftest import rows
from .test_agents import agents, call, plan_args, start  # noqa: F401

pytestmark = pytest.mark.postgres


def test_request_survives_new_store_and_worker_confirms_before_model(agents):  # noqa: F811
    runtime, _, model, *_ = agents
    run = start(agents)
    requested = runtime.store.request_cancel("owner", run["id"])
    assert requested["checkpoint"]["status"] == "READY"
    assert requested["revision"] == run["revision"]
    runtime.store = PostgresAgentStore(agents[-1])
    done = runtime.step("owner", run["id"])
    assert done["checkpoint"]["status"] == "CANCELLED"
    assert not model.requests
    assert runtime.cancel("owner", run["id"])["revision"] == done["revision"]


def test_request_owner_and_current_membership_required(agents):  # noqa: F811
    runtime, *_ = agents
    run = start(agents)
    with pytest.raises(DomainError, match="FORBIDDEN"):
        runtime.cancel("observer", run["id"])
    with psycopg.connect(agents[-1]) as db:
        db.execute(
            "UPDATE experiment_memberships SET revoked_at=clock_timestamp() WHERE actor_id='owner'"
        )
    with pytest.raises(DomainError, match="FORBIDDEN"):
        runtime.cancel("owner", run["id"])
    assert (
        rows(agents[-1], "SELECT cancel_requested_at FROM agent_runs")[0]["cancel_requested_at"]
        is None
    )


def test_cancel_at_reservation_commit_never_calls_model(agents, monkeypatch):  # noqa: F811
    runtime, _, model, *_ = agents
    run = start(agents)
    original = runtime.store.commit

    def before_commit(run, checkpoint, event, **kwargs):
        if event["type"] == "model_reserved":
            runtime.store.request_cancel("owner", run["id"])
        return original(run, checkpoint, event, **kwargs)

    monkeypatch.setattr(runtime.store, "commit", before_commit)
    done = runtime.step("owner", run["id"])
    assert done["checkpoint"]["status"] == "CANCELLED"
    assert done["checkpoint"]["reserved_tokens"] == 0
    assert not model.requests


def test_cancel_at_tool_publication_discards_proposal_and_invocation(agents, monkeypatch):  # noqa: F811
    runtime, _, model, *_ = agents
    run = start(agents)
    args = plan_args(agents[4], run["checkpoint"]["snapshot"]["snapshot_version"])
    model.outputs = [[call("propose_plan", args)]]
    runtime.step("owner", run["id"])
    original = runtime.store.commit

    def before_commit(run, checkpoint, event, **kwargs):
        if kwargs.get("invocations"):
            runtime.store.request_cancel("owner", run["id"])
        return original(run, checkpoint, event, **kwargs)

    monkeypatch.setattr(runtime.store, "commit", before_commit)
    done = runtime.step("owner", run["id"])
    assert done["checkpoint"]["status"] == "CANCELLED"
    for table in ("agent_tool_invocations", "agent_proposals", "command_ledger"):
        assert rows(agents[-1], "SELECT * FROM " + table) == []


def test_terminal_completion_wins_before_late_cancel(agents):  # noqa: F811
    runtime, _, model, *_ = agents
    run = start(agents)
    model.outputs = ["done"]
    done = runtime.step("owner", run["id"])
    late = runtime.cancel("owner", run["id"])
    assert late["checkpoint"] == done["checkpoint"]
    assert late["revision"] == done["revision"]
    assert late["cancel_requested_at"] is None


def test_acknowledgement_and_trace_rollback_together(agents):  # noqa: F811
    runtime, *_ = agents
    run = start(agents)
    runtime.store.request_cancel("owner", run["id"])
    with psycopg.connect(agents[-1]) as db:
        db.execute("""CREATE FUNCTION reject_cancel_trace() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN IF NEW.event->>'type'='cancelled' THEN RAISE EXCEPTION 'test rejection';
          END IF; RETURN NEW; END $$""")
        db.execute(
            "CREATE TRIGGER reject_cancel BEFORE INSERT ON agent_trace "
            "FOR EACH ROW EXECUTE FUNCTION reject_cancel_trace()"
        )
    try:
        with pytest.raises(psycopg.Error):
            runtime.step("owner", run["id"])
        current = runtime.store.load("owner", run["id"])
        assert current["checkpoint"] == run["checkpoint"]
        assert current["cancel_requested_at"] is not None
    finally:
        with psycopg.connect(agents[-1]) as db:
            db.execute("DROP TRIGGER reject_cancel ON agent_trace")
            db.execute("DROP FUNCTION reject_cancel_trace()")
    assert runtime.step("owner", run["id"])["checkpoint"]["status"] == "CANCELLED"


@pytest.mark.parametrize("change", ["clear", "time", "binding", "checkpoint"])
def test_cancel_intent_cannot_be_retracted_or_bypass_immutability(agents, change):  # noqa: F811
    runtime, *_ = agents
    run = start(agents)
    if change in {"clear", "time"}:
        runtime.store.request_cancel("owner", run["id"])
    assignments = {
        "clear": "cancel_requested_at=NULL,revision=revision+1",
        "time": "cancel_requested_at=clock_timestamp(),revision=revision+1",
        "binding": "cancel_requested_at=clock_timestamp(),actor_id='observer'",
        "checkpoint": "cancel_requested_at=clock_timestamp(),checkpoint='{}'::jsonb",
    }
    with pytest.raises(psycopg.errors.CheckViolation), psycopg.connect(agents[-1]) as db:
        db.execute("UPDATE agent_runs SET " + assignments[change] + " WHERE id=%s", (run["id"],))
