"""D02 pure state decisions; trusted facts must be established by application adapters.

This module performs no authorization lookup, persistence, clock read or device operation.
A successful decision must be persisted with evidence, effects and outbox in one transaction.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from alap.domain.rules import DomainError


class Kind(StrEnum):
    RUN = "run"
    TASK = "task"
    COMMAND = "command"
    APPROVAL = "approval"
    LEASE = "lease"
    DATASET = "dataset"


class RunState(StrEnum):
    READY = "READY"
    WAITING_RESOURCE = "WAITING_RESOURCE"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    PAUSE_REQUESTED = "PAUSE_REQUESTED"
    PAUSED = "PAUSED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"


class TaskState(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    WAITING_RESOURCE = "WAITING_RESOURCE"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"
    UNKNOWN = "UNKNOWN"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"


class CommandState(StrEnum):
    NOT_DISPATCHED = "NOT_DISPATCHED"
    DISPATCHED = "DISPATCHED"
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED_CONFIRMED = "FAILED_CONFIRMED"
    REJECTED_BEFORE_EXECUTE = "REJECTED_BEFORE_EXECUTE"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"


class ApprovalState(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class LeaseState(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASE_PENDING = "RELEASE_PENDING"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class DatasetState(StrEnum):
    STAGING = "STAGING"
    VALIDATING = "VALIDATING"
    COMMITTED = "COMMITTED"
    CORRUPT = "CORRUPT"


class Authority(StrEnum):
    ENGINE = "engine"
    GATEWAY = "gateway"
    RECONCILER = "reconciler"
    OPERATOR = "operator"
    APPROVER = "approver"
    DATA_SERVICE = "data_service"
    TIMER = "timer"


class Effect(StrEnum):
    FREEZE_DISPATCH = "freeze_dispatch"
    ENABLE_DISPATCH = "enable_dispatch"
    QUARANTINE_RESOURCES = "quarantine_resources"
    REQUEST_SAFE_STOP = "request_safe_stop"
    REVOKE_DATA_ACCESS = "revoke_data_access"
    INVALIDATE_AUTHORIZATION = "invalidate_authorization"


STATE_TYPES = {
    Kind.RUN: RunState,
    Kind.TASK: TaskState,
    Kind.COMMAND: CommandState,
    Kind.APPROVAL: ApprovalState,
    Kind.LEASE: LeaseState,
    Kind.DATASET: DatasetState,
}

INITIAL_STATES = {
    Kind.RUN: RunState.READY,
    Kind.TASK: TaskState.PENDING,
    Kind.COMMAND: CommandState.NOT_DISPATCHED,
    Kind.APPROVAL: ApprovalState.PENDING,
    Kind.LEASE: LeaseState.ACTIVE,
    Kind.DATASET: DatasetState.STAGING,
}


@dataclass(frozen=True)
class Record:
    kind: Kind
    subject_id: str
    state: StrEnum
    version: int
    binding_hash: str

    def __post_init__(self):
        if type(self.kind) is not Kind or type(self.state) is not STATE_TYPES[self.kind]:
            raise DomainError("INVALID_STATE", "State type must match the aggregate kind")
        if type(self.version) is not int or self.version < 0:
            raise DomainError("INVALID_VERSION", "Version must be a nonnegative integer")
        if not isinstance(self.subject_id, str) or not self.subject_id.strip():
            raise DomainError("INVALID_SUBJECT", "Subject identity is required")
        if not isinstance(self.binding_hash, str) or not re.fullmatch(
            r"[a-f0-9]{64}", self.binding_hash
        ):
            raise DomainError("INVALID_BINDING", "A canonical SHA-256 binding is required")


@dataclass(frozen=True)
class Actor:
    actor_id: str
    authority: Authority

    def __post_init__(self):
        if not isinstance(self.actor_id, str) or not self.actor_id.strip():
            raise DomainError("INVALID_ACTOR", "Authenticated actor identity is required")
        if type(self.authority) is not Authority:
            raise DomainError("INVALID_AUTHORITY", "Trusted actor authority is required")


@dataclass(frozen=True)
class Evidence:
    fact: str
    evidence_id: str
    subject_kind: Kind
    subject_id: str
    subject_version: int
    binding_hash: str
    valid_from: datetime
    valid_until: datetime


@dataclass(frozen=True)
class Rule:
    kind: Kind
    source: StrEnum
    event: str
    target: StrEnum
    authorities: frozenset[Authority]
    facts: frozenset[str]
    effects: frozenset[Effect] = frozenset()


@dataclass(frozen=True)
class Decision:
    previous: Record
    current: Record
    event: str
    actor: Actor
    evidence_ids: tuple[str, ...]
    effects: frozenset[Effect]
    decided_at: datetime


# Every fact is a subject/version/hash-bound, time-limited attestation. Its
# meaning and allowed producer are specified in docs/21_STATE_MACHINES.md.
_rules: list[Rule] = []


def _add(kind, sources, event, target, authorities, facts, effects=()):
    enum = STATE_TYPES[kind]
    for source in sources.split():
        _rules.append(
            Rule(
                kind,
                enum(source),
                event,
                enum(target),
                frozenset(authorities),
                frozenset(facts.split()),
                frozenset(effects),
            )
        )


ENGINE = (Authority.ENGINE,)
GATEWAY = (Authority.GATEWAY,)
RECONCILER = (Authority.RECONCILER,)
OPERATOR = (Authority.OPERATOR,)
DATA_SERVICE = (Authority.DATA_SERVICE,)
FREEZE = (Effect.FREEZE_DISPATCH,)
QUARANTINE = (Effect.FREEZE_DISPATCH, Effect.QUARANTINE_RESOURCES)
STOP = (*FREEZE, Effect.REQUEST_SAFE_STOP)
DISPATCH = "authorization_valid lease_valid preconditions_fresh run_dispatch_allowed"

# Run coordinates child tasks; it never represents a transport-level dispatch.
_add(Kind.RUN, "READY", "resources_unavailable", "WAITING_RESOURCE", ENGINE, "resources_busy")
_add(
    Kind.RUN,
    "WAITING_RESOURCE",
    "resources_acquired",
    "READY",
    ENGINE,
    "lease_valid authorization_valid",
)
_add(Kind.RUN, "READY", "start", "RUNNING", ENGINE, DISPATCH)
_add(
    Kind.RUN,
    "RUNNING",
    "tasks_succeeded",
    "VERIFYING",
    ENGINE,
    "all_tasks_succeeded children_quiescent",
)
_add(
    Kind.RUN,
    "VERIFYING",
    "complete",
    "SUCCEEDED",
    ENGINE,
    "all_tasks_succeeded datasets_committed children_quiescent",
)
_add(
    Kind.RUN,
    "READY WAITING_RESOURCE PAUSED RUNNING VERIFYING PAUSE_REQUESTED CANCEL_REQUESTED",
    "fail",
    "FAILED",
    ENGINE,
    "failure_confirmed children_quiescent",
    FREEZE,
)
_add(
    Kind.RUN,
    "READY WAITING_RESOURCE",
    "pause",
    "PAUSED",
    OPERATOR,
    "control_authorized children_quiescent",
    FREEZE,
)
_add(
    Kind.RUN,
    "RUNNING VERIFYING",
    "pause",
    "PAUSE_REQUESTED",
    OPERATOR,
    "control_authorized",
    FREEZE,
)
_add(
    Kind.RUN,
    "PAUSE_REQUESTED",
    "pause_confirmed",
    "PAUSED",
    ENGINE,
    "children_quiescent dispatch_disabled",
    FREEZE,
)
_add(
    Kind.RUN,
    "PAUSED",
    "resume",
    "READY",
    OPERATOR,
    "control_authorized authorization_valid lease_valid preconditions_fresh children_quiescent",
    (Effect.ENABLE_DISPATCH,),
)
_add(
    Kind.RUN,
    "READY WAITING_RESOURCE PAUSED RUNNING VERIFYING PAUSE_REQUESTED",
    "cancel",
    "CANCEL_REQUESTED",
    OPERATOR,
    "control_authorized",
    STOP,
)
_add(
    Kind.RUN,
    "CANCEL_REQUESTED",
    "cancel_confirmed",
    "CANCELLED",
    ENGINE,
    "children_quiescent cancellation_complete",
    FREEZE,
)
# A completion that won the cancellation/pause race is an observed success, not a stop.
_add(
    Kind.RUN,
    "CANCEL_REQUESTED PAUSE_REQUESTED",
    "completion_won_race",
    "SUCCEEDED",
    ENGINE,
    "all_tasks_succeeded datasets_committed children_quiescent",
    FREEZE,
)
_add(
    Kind.RUN,
    "READY WAITING_RESOURCE PAUSED",
    "authorization_lost",
    "PAUSED",
    ENGINE,
    "authorization_invalid children_quiescent",
    FREEZE,
)
_add(
    Kind.RUN,
    "RUNNING VERIFYING PAUSE_REQUESTED",
    "authorization_lost",
    "PAUSE_REQUESTED",
    ENGINE,
    "authorization_invalid",
    FREEZE,
)
_add(
    Kind.RUN,
    "READY WAITING_RESOURCE RUNNING VERIFYING PAUSE_REQUESTED PAUSED CANCEL_REQUESTED",
    "uncertain",
    "UNKNOWN",
    ENGINE,
    "outcome_uncertain",
    QUARANTINE,
)
_add(
    Kind.RUN,
    "UNKNOWN",
    "begin_reconciliation",
    "NEEDS_RECONCILIATION",
    RECONCILER,
    "dispatch_disabled",
    QUARANTINE,
)
_add(
    Kind.RUN,
    "NEEDS_RECONCILIATION",
    "reconciled_pause",
    "PAUSED",
    RECONCILER,
    "reconciliation_complete children_quiescent",
    FREEZE,
)
_add(
    Kind.RUN,
    "NEEDS_RECONCILIATION",
    "reconciled_success",
    "VERIFYING",
    RECONCILER,
    "reconciliation_complete all_tasks_succeeded children_quiescent",
    FREEZE,
)
_add(
    Kind.RUN,
    "NEEDS_RECONCILIATION",
    "reconciled_failure",
    "FAILED",
    RECONCILER,
    "reconciliation_complete failure_confirmed children_quiescent",
    FREEZE,
)
_add(
    Kind.RUN,
    "NEEDS_RECONCILIATION",
    "reconciled_cancel",
    "CANCELLED",
    RECONCILER,
    "reconciliation_complete cancellation_complete children_quiescent",
    FREEZE,
)

# Tasks pause at run boundaries: an already executing finite skill finishes or is cancelled.
_add(Kind.TASK, "PENDING", "dependencies_succeeded", "READY", ENGINE, "dependencies_succeeded")
_add(Kind.TASK, "READY", "resources_unavailable", "WAITING_RESOURCE", ENGINE, "resources_busy")
_add(Kind.TASK, "WAITING_RESOURCE", "resources_acquired", "READY", ENGINE, "lease_valid")
_add(Kind.TASK, "READY", "dispatch", "DISPATCHED", ENGINE, DISPATCH + " command_prepared")
_add(Kind.TASK, "DISPATCHED", "execution_started", "RUNNING", ENGINE, "command_running")
_add(
    Kind.TASK,
    "DISPATCHED RUNNING CANCEL_REQUESTED",
    "execution_finished",
    "VERIFYING",
    ENGINE,
    "command_succeeded",
)
_add(
    Kind.TASK,
    "VERIFYING",
    "complete",
    "SUCCEEDED",
    ENGINE,
    "command_succeeded success_verified datasets_committed",
)
_add(
    Kind.TASK,
    "PENDING READY WAITING_RESOURCE",
    "cancel",
    "CANCELLED",
    ENGINE,
    "run_cancel_requested no_dispatch",
    FREEZE,
)
_add(
    Kind.TASK,
    "DISPATCHED RUNNING VERIFYING",
    "cancel",
    "CANCEL_REQUESTED",
    ENGINE,
    "run_cancel_requested",
    STOP,
)
_add(
    Kind.TASK,
    "CANCEL_REQUESTED",
    "cancel_confirmed",
    "CANCELLED",
    ENGINE,
    "command_cancelled device_quiescent",
    FREEZE,
)
_add(
    Kind.TASK,
    "PENDING READY WAITING_RESOURCE",
    "skip",
    "SKIPPED",
    ENGINE,
    "dependency_failed no_dispatch",
    FREEZE,
)
_add(
    Kind.TASK,
    "PENDING READY WAITING_RESOURCE",
    "validation_failed",
    "FAILED",
    ENGINE,
    "failure_confirmed no_dispatch",
    FREEZE,
)
_add(
    Kind.TASK,
    "DISPATCHED RUNNING VERIFYING CANCEL_REQUESTED",
    "fail",
    "FAILED",
    ENGINE,
    "command_failed device_quiescent",
    FREEZE,
)
_add(
    Kind.TASK,
    "DISPATCHED RUNNING VERIFYING CANCEL_REQUESTED",
    "uncertain",
    "UNKNOWN",
    ENGINE,
    "outcome_uncertain",
    QUARANTINE,
)
_add(
    Kind.TASK,
    "UNKNOWN",
    "begin_reconciliation",
    "NEEDS_RECONCILIATION",
    RECONCILER,
    "dispatch_disabled",
    QUARANTINE,
)
_add(
    Kind.TASK,
    "NEEDS_RECONCILIATION",
    "reconciled_success",
    "VERIFYING",
    RECONCILER,
    "reconciliation_complete command_succeeded",
    FREEZE,
)
_add(
    Kind.TASK,
    "NEEDS_RECONCILIATION",
    "reconciled_running",
    "RUNNING",
    RECONCILER,
    "reconciliation_complete command_running authorization_valid lease_valid preconditions_fresh",
    FREEZE,
)
_add(
    Kind.TASK,
    "NEEDS_RECONCILIATION",
    "reconciled_failure",
    "FAILED",
    RECONCILER,
    "reconciliation_complete command_failed device_quiescent",
    FREEZE,
)
_add(
    Kind.TASK,
    "NEEDS_RECONCILIATION",
    "reconciled_cancel",
    "CANCELLED",
    RECONCILER,
    "reconciliation_complete command_cancelled device_quiescent",
    FREEZE,
)

# Central command state mirrors durable gateway receipts, never assumes an ACK is success.
_add(
    Kind.COMMAND, "NOT_DISPATCHED", "dispatch", "DISPATCHED", ENGINE, DISPATCH + " journal_prepared"
)
_add(
    Kind.COMMAND,
    "NOT_DISPATCHED",
    "cancel",
    "CANCELLED",
    ENGINE,
    "no_dispatch cancellation_authorized",
    FREEZE,
)
_add(
    Kind.COMMAND,
    "DISPATCHED",
    "accepted",
    "ACCEPTED",
    GATEWAY,
    "gateway_authenticated journal_accepted",
)
_add(
    Kind.COMMAND,
    "DISPATCHED ACCEPTED",
    "execution_started",
    "RUNNING",
    GATEWAY,
    "gateway_authenticated journal_running",
)
_add(
    Kind.COMMAND,
    "DISPATCHED ACCEPTED RUNNING CANCEL_REQUESTED",
    "execution_finished",
    "VERIFYING",
    GATEWAY,
    "gateway_authenticated execution_finished",
)
_add(
    Kind.COMMAND,
    "VERIFYING",
    "complete",
    "SUCCEEDED",
    GATEWAY,
    "gateway_authenticated success_verified datasets_committed result_durable",
)
_add(
    Kind.COMMAND,
    "NOT_DISPATCHED DISPATCHED ACCEPTED",
    "reject",
    "REJECTED_BEFORE_EXECUTE",
    GATEWAY,
    "gateway_authenticated never_executed",
    FREEZE,
)
_add(
    Kind.COMMAND,
    "DISPATCHED ACCEPTED RUNNING VERIFYING CANCEL_REQUESTED",
    "fail",
    "FAILED_CONFIRMED",
    GATEWAY,
    "gateway_authenticated failure_confirmed device_quiescent result_durable",
    FREEZE,
)
_add(
    Kind.COMMAND,
    "DISPATCHED ACCEPTED RUNNING VERIFYING",
    "cancel",
    "CANCEL_REQUESTED",
    ENGINE,
    "cancellation_authorized",
    STOP,
)
_add(
    Kind.COMMAND,
    "CANCEL_REQUESTED",
    "cancel_confirmed",
    "CANCELLED",
    GATEWAY,
    "gateway_authenticated safe_stop_confirmed device_quiescent result_durable",
    FREEZE,
)
_add(
    Kind.COMMAND,
    "DISPATCHED ACCEPTED RUNNING VERIFYING CANCEL_REQUESTED",
    "uncertain",
    "UNKNOWN",
    (Authority.ENGINE, Authority.GATEWAY),
    "outcome_uncertain",
    QUARANTINE,
)
_add(
    Kind.COMMAND,
    "UNKNOWN",
    "begin_reconciliation",
    "NEEDS_RECONCILIATION",
    RECONCILER,
    "dispatch_disabled",
    QUARANTINE,
)
_add(
    Kind.COMMAND,
    "NEEDS_RECONCILIATION",
    "reconciled_success",
    "VERIFYING",
    RECONCILER,
    "reconciliation_complete execution_finished",
    FREEZE,
)
_add(
    Kind.COMMAND,
    "NEEDS_RECONCILIATION",
    "reconciled_running",
    "RUNNING",
    RECONCILER,
    "reconciliation_complete execution_active authorization_valid lease_valid preconditions_fresh",
    FREEZE,
)
_add(
    Kind.COMMAND,
    "NEEDS_RECONCILIATION",
    "reconciled_failure",
    "FAILED_CONFIRMED",
    RECONCILER,
    "reconciliation_complete failure_confirmed device_quiescent result_durable",
    FREEZE,
)
_add(
    Kind.COMMAND,
    "NEEDS_RECONCILIATION",
    "reconciled_cancel",
    "CANCELLED",
    RECONCILER,
    "reconciliation_complete safe_stop_confirmed device_quiescent result_durable",
    FREEZE,
)
_add(
    Kind.COMMAND,
    "NEEDS_RECONCILIATION",
    "reconciled_not_executed",
    "REJECTED_BEFORE_EXECUTE",
    RECONCILER,
    "reconciliation_complete never_executed",
    FREEZE,
)
_add(
    Kind.COMMAND,
    "NEEDS_RECONCILIATION",
    "request_recovery_stop",
    "CANCEL_REQUESTED",
    RECONCILER,
    "reconciliation_complete execution_active recovery_stop_authorized",
    STOP,
)

# A grant or expiry never implicitly stops a physical device or releases quarantine.
_add(
    Kind.APPROVAL,
    "PENDING",
    "approve",
    "APPROVED",
    (Authority.APPROVER,),
    "approval_authorized plan_current approval_window_valid",
)
_add(Kind.APPROVAL, "PENDING", "reject", "REJECTED", (Authority.APPROVER,), "approval_authorized")
_add(
    Kind.APPROVAL,
    "PENDING APPROVED",
    "expire",
    "EXPIRED",
    (Authority.TIMER,),
    "expiry_reached",
    (Effect.INVALIDATE_AUTHORIZATION, Effect.FREEZE_DISPATCH),
)
_add(
    Kind.APPROVAL,
    "APPROVED",
    "revoke",
    "REVOKED",
    (Authority.APPROVER,),
    "approval_authorized",
    (Effect.INVALIDATE_AUTHORIZATION, Effect.FREEZE_DISPATCH),
)
_add(
    Kind.APPROVAL,
    "PENDING APPROVED",
    "supersede",
    "SUPERSEDED",
    ENGINE,
    "plan_changed",
    (Effect.INVALIDATE_AUTHORIZATION, Effect.FREEZE_DISPATCH),
)
_add(
    Kind.LEASE, "ACTIVE", "request_release", "RELEASE_PENDING", ENGINE, "dispatch_disabled", FREEZE
)
_add(
    Kind.LEASE,
    "RELEASE_PENDING",
    "release",
    "RELEASED",
    ENGINE,
    "device_quiescent no_inflight_commands",
)
_add(
    Kind.LEASE,
    "ACTIVE RELEASE_PENDING",
    "expire",
    "EXPIRED",
    (Authority.TIMER,),
    "expiry_reached",
    QUARANTINE,
)
_add(
    Kind.LEASE,
    "ACTIVE RELEASE_PENDING",
    "revoke",
    "REVOKED",
    OPERATOR,
    "control_authorized",
    QUARANTINE,
)
_add(
    Kind.LEASE,
    "ACTIVE",
    "renew",
    "ACTIVE",
    ENGINE,
    "authorization_valid epoch_current renewal_before_expiry renewal_window_valid",
)
_add(Kind.DATASET, "STAGING", "upload_complete", "VALIDATING", DATA_SERVICE, "upload_complete")
_add(
    Kind.DATASET,
    "VALIDATING",
    "commit",
    "COMMITTED",
    DATA_SERVICE,
    "artifact_durable checksum_verified manifest_valid metadata_prepared",
)
_add(
    Kind.DATASET,
    "STAGING VALIDATING COMMITTED",
    "corruption_found",
    "CORRUPT",
    DATA_SERVICE,
    "corruption_verified",
    (Effect.REVOKE_DATA_ACCESS,),
)

_add(
    Kind.TASK,
    "VERIFYING",
    "verification_failed",
    "FAILED",
    ENGINE,
    "failure_confirmed command_terminal device_quiescent",
    FREEZE,
)

RULES = tuple(_rules)
RULE_INDEX = {(rule.kind, rule.source, rule.event): rule for rule in RULES}
if len(RULE_INDEX) != len(RULES):
    raise RuntimeError("Duplicate lifecycle transition")


def _aware(value: datetime) -> bool:
    return (
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
    )


def transition(
    record: Record,
    event: str,
    *,
    expected_version: int,
    actor: Actor,
    evidence: tuple[Evidence, ...],
    now: datetime,
) -> Decision:
    """Decide an allowed transition; the caller must atomically persist all returned effects."""
    if type(record) is not Record or type(actor) is not Actor or type(event) is not str:
        raise DomainError("INVALID_TRANSITION_INPUT", "Typed record, actor and event are required")
    if type(expected_version) is not int or expected_version != record.version:
        raise DomainError("STATE_CONFLICT", "Reload the authoritative aggregate version")
    if not _aware(now):
        raise DomainError("INVALID_CLOCK", "An explicit timezone-aware clock value is required")
    rule = RULE_INDEX.get((record.kind, record.state, event))
    if rule is None:
        raise DomainError("ILLEGAL_TRANSITION", "Event is not legal from the current state")
    if actor.authority not in rule.authorities:
        raise DomainError("TRANSITION_FORBIDDEN", "Actor authority cannot apply this event")
    facts: set[str] = set()
    evidence_ids: set[str] = set()
    for item in evidence:
        if type(item) is not Evidence:
            raise DomainError("INVALID_EVIDENCE", "Typed evidence is required")
        if (
            type(item.subject_kind) is not Kind
            or item.subject_kind != record.kind
            or item.subject_id != record.subject_id
            or type(item.subject_version) is not int
            or item.subject_version != record.version
            or item.binding_hash != record.binding_hash
        ):
            raise DomainError("EVIDENCE_MISMATCH", "Evidence must bind this aggregate and version")
        if (
            not _aware(item.valid_from)
            or not _aware(item.valid_until)
            or not item.valid_from <= now < item.valid_until
        ):
            raise DomainError(
                "EVIDENCE_EXPIRED", "Evidence is stale, premature or has an invalid window"
            )
        if not isinstance(item.evidence_id, str) or not item.evidence_id.strip():
            raise DomainError("INVALID_EVIDENCE", "A durable evidence reference is required")
        if not isinstance(item.fact, str) or not item.fact.strip():
            raise DomainError("INVALID_EVIDENCE", "A named fact is required")
        if item.fact in facts or item.evidence_id in evidence_ids:
            raise DomainError("DUPLICATE_EVIDENCE", "Facts and evidence references must be unique")
        if item.fact not in rule.facts:
            raise DomainError(
                "UNEXPECTED_EVIDENCE", "Only facts required for this event are accepted"
            )
        facts.add(item.fact)
        evidence_ids.add(item.evidence_id)
    if facts != rule.facts:
        raise DomainError("MISSING_EVIDENCE", "Every required transition fact must be established")
    updated = Record(
        record.kind, record.subject_id, rule.target, record.version + 1, record.binding_hash
    )
    return Decision(record, updated, event, actor, tuple(sorted(evidence_ids)), rule.effects, now)
