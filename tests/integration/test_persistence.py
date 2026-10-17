"""D03 acceptance uses real committed transactions and separate concurrent connections."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event

import psycopg
import pytest
from alembic import command

from alap.adapters.postgres.repository import PostgresRepository
from alap.domain.rules import DomainError

from .conftest import rows

pytestmark = pytest.mark.postgres
EXP = "EXP-SIM-001"


def plan(scenario):
    service, _, revision, _ = scenario
    return service.save_plan(
        "owner", experiment_id=EXP, revision=revision, expected_revision=1, key="plan"
    )


def approved(scenario, *, lifetime=3600):
    service, _, _, _ = scenario
    saved = plan(scenario)
    request = service.request_approval(
        "owner",
        experiment_id=EXP,
        plan_id=saved["id"],
        plan_hash=saved["plan_hash"],
        expires_at=datetime.now(UTC) + timedelta(seconds=lifetime),
        expected_revision=saved["revision"],
        key="request",
    )
    return service.decide_approval(
        "approver",
        experiment_id=EXP,
        approval_id=request["id"],
        event="approve",
        expected_revision=request["revision"],
        expected_version=0,
        key="approve",
    )


def start(service, approval, key="start"):
    return service.start_run(
        "owner",
        experiment_id=EXP,
        approval_id=approval["id"],
        expected_revision=approval["revision"],
        key=key,
    )


def test_migration_up_down_up_and_constraints(database):
    dsn, config = database
    assert rows(dsn, "SELECT version_num FROM alembic_version")[0]["version_num"] == "d04_001"
    command.downgrade(config, "base")
    assert rows(dsn, "SELECT to_regclass('experiments') AS name")[0]["name"] is None
    command.upgrade(config, "d03_001")
    assert rows(dsn, "SELECT to_regclass('approvals') AS name")[0]["name"] is None
    command.upgrade(config, "head")
    with pytest.raises(psycopg.errors.ForeignKeyViolation), psycopg.connect(dsn) as connection:
        connection.execute("INSERT INTO samples VALUES ('s','missing','{}',0)")
    with pytest.raises(psycopg.errors.CheckViolation), psycopg.connect(dsn) as connection:
        connection.execute("INSERT INTO principals VALUES ('p','test','p','anonymous',NULL)")


def test_complete_flow_is_atomic_and_snapshot_matches_cursor(scenario):
    service, uow, _, dsn = scenario
    approval = approved(scenario)
    run = start(service, approval)
    assert run["state"] == "READY"
    persisted = rows(dsn, "SELECT * FROM runs")[0]
    assert persisted["dispatch_blocked"] is True  # D04 has not acquired any resources.
    assert len(persisted["task_identities"]) == 3
    assert {t["attempt_no"] for t in persisted["task_identities"]} == {1}
    snapshot = service.read_snapshot("observer", EXP, uow.snapshot)
    assert snapshot["event_cursor"] == 5
    assert [e["experiment_seq"] for e in snapshot["events"]] == list(range(1, 6))
    assert len(rows(dsn, "SELECT * FROM transition_audit")) == 5
    assert len(rows(dsn, "SELECT * FROM evidence_records")) == 3


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE plan_revisions SET plan_json='{}'",
        "DELETE FROM plan_revisions",
        "UPDATE approvals SET expires_at=expires_at + interval '1 hour',state_version=1",
        "UPDATE approvals SET scope_json='{}',state_version=1",
        "DELETE FROM evidence_records",
        "UPDATE transition_audit SET event='forged'",
    ],
)
def test_database_rejects_immutable_history_mutations(scenario, mutation):
    _, _, _, dsn = scenario
    approved(scenario)
    with pytest.raises(psycopg.errors.CheckViolation), psycopg.connect(dsn) as connection:
        connection.execute(mutation)


def test_canonical_bytes_preserved_not_rebuilt_from_jsonb(scenario):
    _, _, revision, dsn = scenario
    saved = plan(scenario)
    row = rows(dsn, "SELECT * FROM plan_revisions")[0]
    from alap.domain.rules import freeze_revision

    snapshot = freeze_revision(revision)
    assert bytes(row["canonical_bytes"]) == snapshot.canonical_bytes
    assert row["plan_hash"] == saved["plan_hash"] == snapshot.plan_hash


def test_start_without_approval_and_stale_version_rejected(scenario):
    service, _, _, dsn = scenario
    saved = plan(scenario)
    request = service.request_approval(
        "owner",
        experiment_id=EXP,
        plan_id=saved["id"],
        plan_hash=saved["plan_hash"],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        expected_revision=2,
        key="req",
    )
    with pytest.raises(DomainError, match="APPROVAL_INVALID"):
        start(service, request)
    with pytest.raises(DomainError, match="STATE_CONFLICT"):
        service.decide_approval(
            "approver",
            experiment_id=EXP,
            approval_id=request["id"],
            event="approve",
            expected_revision=2,
            expected_version=0,
            key="bad",
        )
    assert rows(dsn, "SELECT * FROM runs") == []


@pytest.mark.parametrize("actor", ["outsider", "observer", "agent"])
def test_permission_and_human_approver_enforced(scenario, actor):
    service, _, _, dsn = scenario
    saved = plan(scenario)
    request = service.request_approval(
        "owner",
        experiment_id=EXP,
        plan_id=saved["id"],
        plan_hash=saved["plan_hash"],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        expected_revision=2,
        key="req",
    )
    with pytest.raises(DomainError, match="FORBIDDEN"):
        service.decide_approval(
            actor,
            experiment_id=EXP,
            approval_id=request["id"],
            event="approve",
            expected_revision=3,
            expected_version=0,
            key="bad",
        )
    assert rows(dsn, "SELECT state FROM approvals")[0]["state"] == "PENDING"


def test_scope_and_disabled_membership_rechecked(scenario):
    service, _, _, dsn = scenario
    saved = approved(scenario)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE experiment_memberships SET scope='{}' WHERE actor_id='owner'")
    with pytest.raises(DomainError, match="FORBIDDEN"):
        start(service, saved)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE principals SET disabled_at=clock_timestamp() WHERE id='owner'")
    with pytest.raises(DomainError, match="FORBIDDEN"):
        start(service, saved)


def test_superseding_plan_invalidates_approval_and_freezes_run(scenario):
    service, _, revision, dsn = scenario
    approval = approved(scenario)
    run = start(service, approval)
    changed = deepcopy(revision)
    changed["revision"] = 2
    changed["plan_revision_id"] = "PR-2"
    changed["proposal"]["based_on_snapshot_version"] = run["revision"]
    changed["proposal"]["reason"] = "replanned"
    service.save_plan(
        "owner",
        experiment_id=EXP,
        revision=changed,
        expected_revision=run["revision"],
        key="plan-2",
    )
    assert rows(dsn, "SELECT state FROM approvals")[0]["state"] == "SUPERSEDED"
    stored = rows(dsn, "SELECT * FROM runs")[0]
    assert stored["state"] == "PAUSED" and stored["dispatch_blocked"]
    with pytest.raises(DomainError, match="PLAN_STALE"):
        service.start_run(
            "owner", experiment_id=EXP, approval_id=approval["id"], expected_revision=8, key="new"
        )


def test_policy_change_blocks_execution(scenario):
    service, _, _, dsn = scenario
    approval = approved(scenario)
    service.policy_versions["sim-temp"] = "changed"
    with pytest.raises(DomainError, match="PLAN_STALE"):
        start(service, approval)
    assert rows(dsn, "SELECT * FROM runs") == []


def test_same_key_concurrent_start_returns_one_run(scenario):
    service, _, _, dsn = scenario
    approval = approved(scenario)
    barrier = Barrier(2)

    def worker():
        barrier.wait(timeout=5)
        return start(service, approval)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert results[0] == results[1]
    assert len(rows(dsn, "SELECT * FROM runs")) == 1
    assert len(rows(dsn, "SELECT * FROM outbox_events WHERE aggregate_type='run'")) == 1
    # A retry after later state changes still returns the recorded response, not a new action.
    assert start(service, approval) == results[0]


def test_same_key_different_payload_conflicts(scenario):
    service, _, _, dsn = scenario
    approval = approved(scenario)
    start(service, approval)
    changed = {**approval, "revision": 5}
    with pytest.raises(DomainError, match="IDEMPOTENCY_CONFLICT"):
        start(service, changed)
    assert len(rows(dsn, "SELECT * FROM runs")) == 1


def test_concurrent_create_unique_key_and_conflicting_payload(scenario):
    service, _, _, dsn = scenario
    barrier = Barrier(2)

    def worker(identity):
        barrier.wait(timeout=5)
        try:
            return service.create_experiment(
                "owner", experiment_id=identity, sample_id="sample", key="race-create"
            )
        except DomainError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, ["exp-a", "exp-b"]))
    assert sum(isinstance(r, dict) for r in results) == 1
    assert "IDEMPOTENCY_CONFLICT" in results
    assert len(rows(dsn, "SELECT * FROM experiments")) == 2


def test_different_keys_cannot_overwrite_same_snapshot(scenario):
    service, _, _, dsn = scenario
    approval = approved(scenario)
    barrier = Barrier(2)

    def worker(key):
        barrier.wait(timeout=5)
        try:
            return start(service, approval, key)
        except DomainError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, ["a", "b"]))
    assert sum(isinstance(r, dict) for r in results) == 1
    assert "STATE_CONFLICT" in results
    assert len(rows(dsn, "SELECT * FROM runs")) == 1


def test_failure_before_outbox_rolls_back_state_evidence_effects_and_idempotency(
    scenario, monkeypatch
):
    service, _, _, dsn = scenario
    approval = approved(scenario)
    run = start(service, approval)
    before = rows(dsn, "SELECT * FROM experiments")
    original = PostgresRepository.insert

    def fail_outbox(self, table, values):
        if table == "outbox_events":
            raise RuntimeError("injected before outbox")
        return original(self, table, values)

    with monkeypatch.context() as patch:
        patch.setattr(PostgresRepository, "insert", fail_outbox)
        with pytest.raises(RuntimeError, match="injected"):
            service.decide_approval(
                "approver",
                experiment_id=EXP,
                approval_id=approval["id"],
                event="revoke",
                expected_revision=run["revision"],
                expected_version=1,
                key="revoke",
            )
    assert rows(dsn, "SELECT * FROM experiments") == before
    assert rows(dsn, "SELECT state FROM approvals")[0]["state"] == "APPROVED"
    assert rows(dsn, "SELECT state FROM runs")[0]["state"] == "READY"
    assert len(rows(dsn, "SELECT * FROM evidence_records")) == 3
    assert rows(dsn, "SELECT * FROM idempotency_records WHERE key='revoke'") == []
    service.decide_approval(
        "approver",
        experiment_id=EXP,
        approval_id=approval["id"],
        event="revoke",
        expected_revision=run["revision"],
        expected_version=1,
        key="revoke",
    )
    assert rows(dsn, "SELECT state FROM runs")[0]["state"] == "PAUSED"


def test_revoke_commit_wins_against_waiting_start(scenario):
    service, uow, _, dsn = scenario
    approval = approved(scenario)
    locked, release = Event(), Event()

    @contextmanager
    def paused_transaction():
        with uow() as repo:
            original = repo.get

            def get(table, identity, *, lock=False):
                value = original(table, identity, lock=lock)
                if table == "experiments" and lock:
                    locked.set()
                    assert release.wait(5)
                return value

            repo.get = get
            yield repo

    from copy import copy

    revoker = copy(service)
    revoker.transaction = paused_transaction
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(
            revoker.decide_approval,
            "approver",
            experiment_id=EXP,
            approval_id=approval["id"],
            event="revoke",
            expected_revision=4,
            expected_version=1,
            key="revoke",
        )
        assert locked.wait(5)
        starter = pool.submit(start, service, approval)
        release.set()
        assert future.result(timeout=5)["state"] == "REVOKED"
        with pytest.raises(DomainError, match="STATE_CONFLICT"):
            starter.result(timeout=5)
    assert rows(dsn, "SELECT * FROM runs") == []


def test_expiry_boundary_checked_without_timer(scenario, monkeypatch):
    service, _, _, dsn = scenario
    approval = approved(scenario)
    expiry = rows(dsn, "SELECT expires_at FROM approvals")[0]["expires_at"]
    # Controlled trusted clock tests the exact expiry boundary without sleeping.
    monkeypatch.setattr(PostgresRepository, "now", lambda self: expiry)
    with pytest.raises(DomainError, match="APPROVAL_EXPIRED"):
        start(service, approval)
    assert rows(dsn, "SELECT state FROM approvals")[0]["state"] == "APPROVED"
    assert service.expire_approvals("timer", experiment_id=EXP) == 1
    assert service.expire_approvals("timer", experiment_id=EXP) == 0
    assert rows(dsn, "SELECT state FROM approvals")[0]["state"] == "EXPIRED"


def test_cross_experiment_composite_foreign_key(scenario):
    service, _, _, dsn = scenario
    approval = approved(scenario)
    start(service, approval)
    service.create_experiment("owner", experiment_id="other", sample_id="sample", key="other")
    run = rows(dsn, "SELECT * FROM runs")[0]
    with pytest.raises(psycopg.errors.ForeignKeyViolation), psycopg.connect(dsn) as connection:
        connection.execute(
            """INSERT INTO runs(id,experiment_id,plan_revision_id,approval_id,plan_hash,state,
            binding_hash,task_identities,created_by)
            VALUES ('cross','other',%s,%s,%s,'READY',%s,'[]','owner')""",
            (run["plan_revision_id"], approval["id"], run["plan_hash"], run["binding_hash"]),
        )


def test_repeatable_read_snapshot_does_not_mix_new_cursor(scenario):
    service, uow, _, dsn = scenario
    saved = plan(scenario)
    with uow.snapshot() as repo:
        before = repo.get("experiments", EXP)
        service.request_approval(
            "owner",
            experiment_id=EXP,
            plan_id=saved["id"],
            plan_hash=saved["plan_hash"],
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            expected_revision=2,
            key="request",
        )
        assert repo.get("experiments", EXP) == before
        assert len(repo.events(EXP)) == before["event_cursor"] == 2
    assert rows(dsn, "SELECT event_cursor FROM experiments")[0]["event_cursor"] == 3


@pytest.mark.parametrize("operation", ["snapshot", "start", "approve"])
def test_cross_experiment_access_is_denied(scenario, operation):
    service, uow, _, dsn = scenario
    approval = approved(scenario)
    with pytest.raises(DomainError, match="FORBIDDEN"):
        if operation == "snapshot":
            service.read_snapshot("outsider", EXP, uow.snapshot)
        elif operation == "start":
            service.start_run(
                "outsider",
                experiment_id=EXP,
                approval_id=approval["id"],
                expected_revision=4,
                key="no",
            )
        else:
            service.decide_approval(
                "outsider",
                experiment_id=EXP,
                approval_id=approval["id"],
                event="revoke",
                expected_revision=4,
                expected_version=1,
                key="no",
            )
    assert not rows(dsn, "SELECT * FROM runs")


def test_wrong_plan_hash_and_stale_snapshot_cannot_request_approval(scenario):
    service, _, revision, dsn = scenario
    saved = plan(scenario)
    with pytest.raises(DomainError, match="PLAN_MISMATCH"):
        service.request_approval(
            "owner",
            experiment_id=EXP,
            plan_id=saved["id"],
            plan_hash="0" * 64,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            expected_revision=2,
            key="wrong",
        )
    changed = deepcopy(revision)
    changed["revision"] = 2
    changed["plan_revision_id"] = "second"
    with pytest.raises(DomainError, match="PLAN_STALE"):
        service.save_plan(
            "owner", experiment_id=EXP, revision=changed, expected_revision=2, key="stale"
        )
    assert rows(dsn, "SELECT * FROM approvals") == []


def test_rejected_and_revoked_approvals_cannot_be_reopened(scenario):
    service, _, _, dsn = scenario
    approval = approved(scenario)
    revoked = service.decide_approval(
        "approver",
        experiment_id=EXP,
        approval_id=approval["id"],
        event="revoke",
        expected_revision=4,
        expected_version=1,
        key="revoke",
    )
    with pytest.raises(DomainError, match="ILLEGAL_TRANSITION"):
        service.decide_approval(
            "approver",
            experiment_id=EXP,
            approval_id=approval["id"],
            event="approve",
            expected_revision=revoked["revision"],
            expected_version=2,
            key="again",
        )
    with pytest.raises(DomainError, match="APPROVAL_INVALID"):
        start(service, revoked)
    assert not rows(dsn, "SELECT * FROM runs")


def test_idempotent_response_not_exposed_after_membership_revoked(scenario):
    service, _, _, dsn = scenario
    approval = approved(scenario)
    start(service, approval)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE experiment_memberships SET revoked_at=clock_timestamp() WHERE actor_id='owner'"
        )
    with pytest.raises(DomainError, match="FORBIDDEN"):
        start(service, approval)
    assert len(rows(dsn, "SELECT * FROM runs")) == 1


def test_outbox_contract_and_immutable_event_payload(scenario):
    service, _, _, dsn = scenario
    approved(scenario)
    for event in rows(dsn, "SELECT * FROM outbox_events"):
        event.pop("aggregate_type")
        event.pop("published_at")
        event["occurred_at"] = event["occurred_at"].isoformat()
        service.catalog.validate("event", event)
    with pytest.raises(psycopg.errors.CheckViolation), psycopg.connect(dsn) as connection:
        connection.execute("UPDATE outbox_events SET payload='{}'")
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE outbox_events SET published_at=clock_timestamp()")


def test_expiry_freezes_existing_run_atomically(scenario, monkeypatch):
    service, _, _, dsn = scenario
    approval = approved(scenario)
    start(service, approval)
    expiry = rows(dsn, "SELECT expires_at FROM approvals")[0]["expires_at"]
    monkeypatch.setattr(PostgresRepository, "now", lambda self: expiry)
    assert service.expire_approvals("timer", experiment_id=EXP) == 1
    run = rows(dsn, "SELECT * FROM runs")[0]
    assert run["dispatch_blocked"] and run["state"] == "PAUSED"
    assert len(rows(dsn, "SELECT * FROM evidence_records")) == 6


def test_actual_database_clock_after_waiting_for_experiment_lock(scenario):
    service, _, _, dsn = scenario
    approval = approved(scenario, lifetime=1.5)
    with psycopg.connect(dsn) as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        blocker.execute("SELECT id FROM experiments WHERE id=%s FOR UPDATE", (EXP,))
        future = pool.submit(start, service, approval)
        # Independent session waits on the experiment lock while real DB time crosses expiry.
        blocker.execute(
            "SELECT pg_sleep(GREATEST(0, EXTRACT(EPOCH FROM "
            "(expires_at-clock_timestamp()))) + 0.05) FROM approvals"
        )
        blocker.commit()
        with pytest.raises(DomainError, match="APPROVAL_EXPIRED"):
            future.result(timeout=5)
    assert not rows(dsn, "SELECT * FROM runs")


def test_approval_evidence_records_checked_scope_and_references(scenario):
    _, _, _, dsn = scenario
    approved(scenario)
    evidence = rows(dsn, "SELECT * FROM evidence_records")
    authority = next(e for e in evidence if e["fact"] == "approval_authorized")
    assert authority["source"]["checked"]["actor_id"] == "approver"
    assert authority["source"]["checked"]["scope"]["resources"]
    audit = rows(dsn, "SELECT * FROM transition_audit WHERE event='approve'")[0]
    assert set(audit["evidence_ids"]) == {e["id"] for e in evidence}
