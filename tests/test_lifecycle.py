"""D02 acceptance: state safety under delayed receipts, conflicts and control races."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from alap.domain.lifecycle import (
    RULES,
    STATE_TYPES,
    Actor,
    ApprovalState,
    Authority,
    CommandState,
    DatasetState,
    Effect,
    Evidence,
    Kind,
    LeaseState,
    Record,
    RunState,
    TaskState,
    transition,
)
from alap.domain.rules import DomainError

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)
HASH = "a" * 64


def record(kind, state, version=0):
    return Record(kind, "subject-1", state, version, HASH)


def proof(item, fact, **overrides):
    value = Evidence(
        fact,
        f"evidence-{fact}",
        item.kind,
        item.subject_id,
        item.version,
        item.binding_hash,
        NOW - timedelta(seconds=1),
        NOW + timedelta(seconds=10),
    )
    return replace(value, **overrides)


def decide(item, event, authority=Authority.ENGINE, facts="", **overrides):
    args = dict(
        expected_version=item.version,
        actor=Actor("actor-1", authority),
        evidence=tuple(proof(item, fact) for fact in facts.split()),
        now=NOW,
    )
    args.update(overrides)
    return transition(item, event, **args)


def test_command_lifecycle_needs_readback_and_durable_result():
    item = record(Kind.COMMAND, CommandState.NOT_DISPATCHED)
    item = decide(
        item,
        "dispatch",
        facts=(
            "authorization_valid lease_valid preconditions_fresh "
            "run_dispatch_allowed journal_prepared"
        ),
    ).current
    item = decide(
        item, "accepted", Authority.GATEWAY, "gateway_authenticated journal_accepted"
    ).current
    assert item.state == CommandState.ACCEPTED  # ACK is not execution or success.
    with pytest.raises(DomainError, match="ILLEGAL_TRANSITION"):
        decide(item, "complete", Authority.GATEWAY)
    item = decide(
        item, "execution_started", Authority.GATEWAY, "gateway_authenticated journal_running"
    ).current
    item = decide(
        item, "execution_finished", Authority.GATEWAY, "gateway_authenticated execution_finished"
    ).current
    with pytest.raises(DomainError, match="MISSING_EVIDENCE"):
        decide(
            item,
            "complete",
            Authority.GATEWAY,
            "gateway_authenticated success_verified datasets_committed",
        )
    result = decide(
        item,
        "complete",
        Authority.GATEWAY,
        "gateway_authenticated success_verified datasets_committed result_durable",
    )
    assert result.current.state == CommandState.SUCCEEDED
    assert result.current.version == 5
    assert result.evidence_ids == tuple(sorted(result.evidence_ids))


def test_ack_loss_requires_reconciliation_and_cannot_redispatch():
    item = record(Kind.COMMAND, CommandState.DISPATCHED)
    decision = decide(item, "uncertain", facts="outcome_uncertain")
    assert {Effect.FREEZE_DISPATCH, Effect.QUARANTINE_RESOURCES} <= decision.effects
    item = decision.current
    for event in ("dispatch", "accepted", "complete", "execution_started"):
        with pytest.raises(DomainError, match="ILLEGAL_TRANSITION"):
            decide(item, event, Authority.GATEWAY)
    item = decide(item, "begin_reconciliation", Authority.RECONCILER, "dispatch_disabled").current
    item = decide(
        item,
        "reconciled_success",
        Authority.RECONCILER,
        "reconciliation_complete execution_finished",
    ).current
    assert item.state == CommandState.VERIFYING
    assert (
        decide(
            item,
            "complete",
            Authority.GATEWAY,
            "gateway_authenticated success_verified datasets_committed result_durable",
        ).current.state
        == CommandState.SUCCEEDED
    )


def test_proven_nonexecution_closes_original_command_instead_of_retrying():
    item = record(Kind.COMMAND, CommandState.NEEDS_RECONCILIATION)
    item = decide(
        item,
        "reconciled_not_executed",
        Authority.RECONCILER,
        "reconciliation_complete never_executed",
    ).current
    assert item.state == CommandState.REJECTED_BEFORE_EXECUTE
    with pytest.raises(DomainError, match="ILLEGAL_TRANSITION"):
        decide(item, "dispatch")


def test_cancel_not_confirmed_is_unknown_not_cancelled():
    item = record(Kind.COMMAND, CommandState.RUNNING)
    result = decide(item, "cancel", facts="cancellation_authorized")
    assert result.current.state == CommandState.CANCEL_REQUESTED
    assert Effect.REQUEST_SAFE_STOP in result.effects
    with pytest.raises(DomainError, match="MISSING_EVIDENCE"):
        decide(result.current, "cancel_confirmed", Authority.GATEWAY, "gateway_authenticated")
    assert (
        decide(result.current, "uncertain", facts="outcome_uncertain").current.state
        == CommandState.UNKNOWN
    )


def test_completion_can_win_cancel_race_without_replaying_command():
    item = record(Kind.COMMAND, CommandState.CANCEL_REQUESTED)
    item = decide(
        item, "execution_finished", Authority.GATEWAY, "gateway_authenticated execution_finished"
    ).current
    item = decide(
        item,
        "complete",
        Authority.GATEWAY,
        "gateway_authenticated success_verified datasets_committed result_durable",
    ).current
    assert item.state == CommandState.SUCCEEDED


def test_run_pause_waits_for_quiescent_children_and_resume_revalidates():
    item = record(Kind.RUN, RunState.RUNNING)
    decision = decide(item, "pause", Authority.OPERATOR, "control_authorized")
    assert decision.current.state == RunState.PAUSE_REQUESTED
    assert Effect.FREEZE_DISPATCH in decision.effects
    with pytest.raises(DomainError, match="MISSING_EVIDENCE"):
        decide(decision.current, "pause_confirmed", facts="dispatch_disabled")
    item = decide(
        decision.current, "pause_confirmed", facts="children_quiescent dispatch_disabled"
    ).current
    with pytest.raises(DomainError, match="MISSING_EVIDENCE"):
        decide(item, "resume", Authority.OPERATOR, "control_authorized")
    item = decide(
        item,
        "resume",
        Authority.OPERATOR,
        "control_authorized authorization_valid lease_valid preconditions_fresh children_quiescent",
    ).current
    assert item.state == RunState.READY


def test_task_cannot_pause_and_restart_a_physical_step():
    item = record(Kind.TASK, TaskState.RUNNING)
    for event in ("pause", "resume", "dispatch"):
        with pytest.raises(DomainError, match="ILLEGAL_TRANSITION"):
            decide(item, event)


def test_task_aggregation_requires_authoritative_command_result():
    item = record(Kind.TASK, TaskState.DISPATCHED)
    with pytest.raises(DomainError, match="MISSING_EVIDENCE"):
        decide(item, "execution_finished")
    item = decide(item, "execution_finished", facts="command_succeeded").current
    with pytest.raises(DomainError, match="MISSING_EVIDENCE"):
        decide(item, "complete", facts="command_succeeded success_verified")
    assert (
        decide(
            item, "complete", facts="command_succeeded success_verified datasets_committed"
        ).current.state
        == TaskState.SUCCEEDED
    )


def test_task_verification_failure_does_not_rewrite_command_success():
    item = record(Kind.TASK, TaskState.VERIFYING)
    assert (
        decide(
            item, "verification_failed", facts="failure_confirmed command_terminal device_quiescent"
        ).current.state
        == TaskState.FAILED
    )


def test_unstarted_task_cancel_requires_proof_it_was_not_dispatched():
    item = record(Kind.TASK, TaskState.READY)
    with pytest.raises(DomainError, match="MISSING_EVIDENCE"):
        decide(item, "cancel", facts="run_cancel_requested")
    assert (
        decide(item, "cancel", facts="run_cancel_requested no_dispatch").current.state
        == TaskState.CANCELLED
    )


@pytest.mark.parametrize("state", [RunState.RUNNING, RunState.CANCEL_REQUESTED])
def test_run_failure_does_not_hide_running_or_unknown_children(state):
    item = record(Kind.RUN, state)
    with pytest.raises(DomainError, match="MISSING_EVIDENCE"):
        decide(item, "fail", facts="failure_confirmed")
    assert (
        decide(item, "fail", facts="failure_confirmed children_quiescent").current.state
        == RunState.FAILED
    )


def test_reconciled_run_stays_paused_until_explicit_resume():
    item = record(Kind.RUN, RunState.NEEDS_RECONCILIATION)
    result = decide(
        item, "reconciled_pause", Authority.RECONCILER, "reconciliation_complete children_quiescent"
    )
    assert result.current.state == RunState.PAUSED
    assert Effect.FREEZE_DISPATCH in result.effects


def test_recovery_stop_is_possible_without_new_execution_permission():
    item = record(Kind.COMMAND, CommandState.NEEDS_RECONCILIATION)
    result = decide(
        item,
        "request_recovery_stop",
        Authority.RECONCILER,
        "reconciliation_complete execution_active recovery_stop_authorized",
    )
    assert result.current.state == CommandState.CANCEL_REQUESTED
    assert Effect.REQUEST_SAFE_STOP in result.effects


@pytest.mark.parametrize(
    "missing",
    [
        "authorization_valid",
        "lease_valid",
        "preconditions_fresh",
        "run_dispatch_allowed",
        "journal_prepared",
    ],
)
def test_every_dispatch_gate_is_required(missing):
    item = record(Kind.COMMAND, CommandState.NOT_DISPATCHED)
    facts = (
        "authorization_valid lease_valid preconditions_fresh run_dispatch_allowed journal_prepared"
    ).split()
    facts.remove(missing)
    with pytest.raises(DomainError, match="MISSING_EVIDENCE"):
        decide(item, "dispatch", facts=" ".join(facts))


def test_operator_cannot_forge_gateway_completion():
    item = record(Kind.COMMAND, CommandState.VERIFYING)
    with pytest.raises(DomainError, match="TRANSITION_FORBIDDEN"):
        decide(
            item,
            "complete",
            Authority.OPERATOR,
            "gateway_authenticated success_verified datasets_committed result_durable",
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"subject_id": "other"},
        {"subject_kind": Kind.COMMAND},
        {"subject_version": 2},
        {"subject_version": False},
        {"binding_hash": "b" * 64},
    ],
)
def test_evidence_cannot_cross_subject_version_or_binding(overrides):
    item = record(Kind.RUN, RunState.READY)
    ev = proof(item, "resources_busy", **overrides)
    with pytest.raises(DomainError, match="EVIDENCE_MISMATCH"):
        decide(item, "resources_unavailable", evidence=(ev,))


@pytest.mark.parametrize(
    "overrides",
    [
        {"valid_until": NOW},
        {"valid_from": NOW + timedelta(seconds=1)},
        {"valid_until": NOW.replace(tzinfo=None)},
        {"valid_from": NOW + timedelta(days=1)},
    ],
)
def test_stale_or_future_evidence_rejected(overrides):
    item = record(Kind.RUN, RunState.READY)
    with pytest.raises(DomainError, match="EVIDENCE_EXPIRED"):
        decide(
            item, "resources_unavailable", evidence=(proof(item, "resources_busy", **overrides),)
        )


def test_duplicate_delivery_requires_application_idempotency_not_a_second_transition():
    item = record(Kind.RUN, RunState.READY)
    result = decide(item, "resources_unavailable", facts="resources_busy")
    with pytest.raises(DomainError, match="STATE_CONFLICT"):
        decide(result.current, "resources_unavailable", expected_version=0)
    assert item.version == 0  # input is unchanged
    with pytest.raises(FrozenInstanceError):
        result.current.version = 99


def test_duplicate_evidence_rejected():
    item = record(Kind.RUN, RunState.READY)
    ev = proof(item, "resources_busy")
    with pytest.raises(DomainError, match="DUPLICATE_EVIDENCE"):
        decide(item, "resources_unavailable", evidence=(ev, ev))


def test_naive_clock_rejected():
    with pytest.raises(DomainError, match="INVALID_CLOCK"):
        decide(record(Kind.RUN, RunState.READY), "pause", now=NOW.replace(tzinfo=None))


def test_record_kind_cannot_accept_equally_named_state_from_other_machine():
    with pytest.raises(DomainError, match="INVALID_STATE"):
        Record(Kind.RUN, "r1", TaskState.READY, 0, HASH)


@pytest.mark.parametrize(
    "event,facts,target",
    [
        (
            "approve",
            "approval_authorized plan_current approval_window_valid",
            ApprovalState.APPROVED,
        ),
        ("reject", "approval_authorized", ApprovalState.REJECTED),
    ],
)
def test_approval_decision_requires_scoped_authority(event, facts, target):
    item = record(Kind.APPROVAL, ApprovalState.PENDING)
    with pytest.raises(DomainError, match="TRANSITION_FORBIDDEN"):
        decide(item, event, Authority.ENGINE, facts)
    assert decide(item, event, Authority.APPROVER, facts).current.state == target


def test_revoked_approval_cannot_be_reapproved():
    item = record(Kind.APPROVAL, ApprovalState.APPROVED)
    result = decide(item, "revoke", Authority.APPROVER, "approval_authorized")
    assert Effect.INVALIDATE_AUTHORIZATION in result.effects
    with pytest.raises(DomainError, match="ILLEGAL_TRANSITION"):
        decide(result.current, "approve", Authority.APPROVER)


def test_expired_lease_keeps_resource_quarantined():
    item = record(Kind.LEASE, LeaseState.ACTIVE)
    result = decide(item, "expire", Authority.TIMER, "expiry_reached")
    assert result.current.state == LeaseState.EXPIRED
    assert Effect.QUARANTINE_RESOURCES in result.effects
    with pytest.raises(DomainError, match="ILLEGAL_TRANSITION"):
        decide(result.current, "renew")


def test_lease_release_waits_for_no_commands_and_safe_device():
    item = record(Kind.LEASE, LeaseState.ACTIVE)
    item = decide(item, "request_release", facts="dispatch_disabled").current
    with pytest.raises(DomainError, match="MISSING_EVIDENCE"):
        decide(item, "release", facts="no_inflight_commands")
    assert (
        decide(item, "release", facts="device_quiescent no_inflight_commands").current.state
        == LeaseState.RELEASED
    )


def test_dataset_publish_and_later_integrity_failure():
    item = record(Kind.DATASET, DatasetState.STAGING)
    with pytest.raises(DomainError, match="ILLEGAL_TRANSITION"):
        decide(item, "commit", Authority.DATA_SERVICE)
    item = decide(item, "upload_complete", Authority.DATA_SERVICE, "upload_complete").current
    with pytest.raises(DomainError, match="MISSING_EVIDENCE"):
        decide(
            item,
            "commit",
            Authority.DATA_SERVICE,
            "artifact_durable manifest_valid metadata_prepared",
        )
    item = decide(
        item,
        "commit",
        Authority.DATA_SERVICE,
        "artifact_durable checksum_verified manifest_valid metadata_prepared",
    ).current
    assert item.state == DatasetState.COMMITTED
    result = decide(item, "corruption_found", Authority.DATA_SERVICE, "corruption_verified")
    assert result.current.state == DatasetState.CORRUPT
    assert Effect.REVOKE_DATA_ACCESS in result.effects
    with pytest.raises(DomainError, match="ILLEGAL_TRANSITION"):
        decide(result.current, "commit", Authority.DATA_SERVICE)


def test_no_transition_can_reopen_terminal_execution_or_redispatch_an_old_command():
    for rule in RULES:
        if rule.kind in (Kind.RUN, Kind.TASK, Kind.COMMAND):
            assert rule.source.value not in {
                "SUCCEEDED",
                "FAILED",
                "CANCELLED",
                "SKIPPED",
                "FAILED_CONFIRMED",
                "REJECTED_BEFORE_EXECUTE",
            }
        if rule.kind == Kind.COMMAND:
            assert rule.target != CommandState.NOT_DISPATCHED
            if rule.target == CommandState.DISPATCHED:
                assert rule.source == CommandState.NOT_DISPATCHED


def test_every_state_is_reachable_from_its_machine_start():
    starts = {
        Kind.RUN: RunState.READY,
        Kind.TASK: TaskState.PENDING,
        Kind.COMMAND: CommandState.NOT_DISPATCHED,
        Kind.APPROVAL: ApprovalState.PENDING,
        Kind.LEASE: LeaseState.ACTIVE,
        Kind.DATASET: DatasetState.STAGING,
    }
    for kind, start in starts.items():
        reached = {start}
        while True:
            expanded = reached | {r.target for r in RULES if r.kind == kind and r.source in reached}
            if expanded == reached:
                break
            reached = expanded
        assert reached == set(STATE_TYPES[kind])


def test_terminal_run_needs_quiescent_children_for_every_exit():
    for rule in RULES:
        if rule.kind == Kind.RUN and rule.target in {
            RunState.SUCCEEDED,
            RunState.CANCELLED,
            RunState.FAILED,
        }:
            assert "children_quiescent" in rule.facts


def test_unknown_always_freezes_and_quarantines():
    for rule in RULES:
        if rule.target.value == "UNKNOWN":
            assert {Effect.FREEZE_DISPATCH, Effect.QUARANTINE_RESOURCES} <= rule.effects


def test_lease_renewal_requires_new_window_and_preserves_ownership_binding():
    item = record(Kind.LEASE, LeaseState.ACTIVE, version=3)
    facts = "authorization_valid epoch_current renewal_before_expiry"
    with pytest.raises(DomainError, match="MISSING_EVIDENCE"):
        decide(item, "renew", facts=facts)
    renewed = decide(item, "renew", facts=facts + " renewal_window_valid").current
    assert renewed.binding_hash == item.binding_hash
    assert renewed.version == 4


def test_resume_only_enables_run_dispatch_after_all_guards():
    item = record(Kind.RUN, RunState.PAUSED)
    decision = decide(
        item,
        "resume",
        Authority.OPERATOR,
        "control_authorized authorization_valid lease_valid preconditions_fresh children_quiescent",
    )
    assert decision.effects == frozenset({Effect.ENABLE_DISPATCH})


def test_evidence_window_excludes_exact_expiry():
    item = record(Kind.APPROVAL, ApprovalState.PENDING)
    with pytest.raises(DomainError, match="EVIDENCE_EXPIRED"):
        decide(
            item,
            "reject",
            Authority.APPROVER,
            evidence=(proof(item, "approval_authorized", valid_until=NOW),),
        )
