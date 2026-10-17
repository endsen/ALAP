"""FR-009/011/012 foundation; not evidence of device or database behavior."""

import pytest
from jsonschema import ValidationError

from alap.domain.rules import DomainError


def test_valid_manifest_and_command(catalog, example):
    catalog.validate_dataset(example("dataset_manifest"), public=True)
    catalog.validate_command(example("command"))


def test_rfc3339_lowercase_timestamp(catalog, example):
    command = example("command")
    command["issued_at"] = "2026-10-16t08:00:00z"
    catalog.validate_command(command)


def test_deadline_comparison_uses_actual_instant(catalog, example):
    command = example("command")
    command["issued_at"] = "2026-10-16T16:00:00+08:00"
    command["deadline_at"] = "2026-10-16T08:05:00Z"
    catalog.validate_command(command)
    command["deadline_at"] = "2026-10-16T09:00:00+02:00"
    with pytest.raises(DomainError, match="INVALID_TIME_INTERVAL"):
        catalog.validate_command(command)


@pytest.mark.parametrize("status", ["STAGING", "VALIDATING", "CORRUPT"])
def test_incomplete_data_not_public(catalog, example, status):
    manifest = example("dataset_manifest")
    manifest["status"] = status
    catalog.validate_dataset(manifest)
    with pytest.raises(DomainError, match="DATASET_NOT_COMMITTED"):
        catalog.validate_dataset(manifest, public=True)


@pytest.mark.parametrize(
    "field",
    ["acquisition_interval", "policy_versions", "capability_versions", "device_snapshot_version"],
)
def test_provenance_required(catalog, example, field):
    manifest = example("dataset_manifest")
    del manifest[field]
    with pytest.raises(ValidationError):
        catalog.validate_dataset(manifest)


def test_data_versions_cannot_belong_to_wrong_device(catalog, example):
    manifest = example("dataset_manifest")
    manifest["capability_versions"] = {"another-device": "cap-1"}
    with pytest.raises(DomainError, match="PROVENANCE_MISMATCH"):
        catalog.validate_dataset(manifest)


def test_reversed_acquisition_interval(catalog, example):
    manifest = example("dataset_manifest")
    manifest["acquisition_interval"]["end_utc"] = "2026-10-16T07:00:00Z"
    with pytest.raises(DomainError, match="INVALID_TIME_INTERVAL"):
        catalog.validate_dataset(manifest)


@pytest.mark.parametrize("timestamp", ["2026-10-16T08:00:00", "2026-02-30T08:00:00Z", "invalid"])
def test_invalid_or_naive_timestamps(catalog, example, timestamp):
    command = example("command")
    command["issued_at"] = timestamp
    with pytest.raises(ValidationError):
        catalog.validate_command(command)


@pytest.mark.parametrize("deadline", ["2026-10-16T08:00:00Z", "2026-10-16T07:00:00Z"])
def test_command_deadline_must_follow_issuance(catalog, example, deadline):
    command = example("command")
    command["deadline_at"] = deadline
    with pytest.raises(DomainError, match="INVALID_TIME_INTERVAL"):
        catalog.validate_command(command)


@pytest.mark.parametrize(
    "field", ["control_epoch", "skill_version", "authorized_plan_hash", "lease_id"]
)
def test_command_authorization_fields_required(catalog, example, field):
    command = example("command")
    del command[field]
    with pytest.raises(ValidationError):
        catalog.validate_command(command)


def test_negative_fence_rejected(catalog, example):
    command = example("command")
    command["fencing_token"] = -1
    with pytest.raises(ValidationError):
        catalog.validate_command(command)


def test_event_has_distinct_experiment_cursor(catalog, example):
    event = example("event")
    event["aggregate_seq"] = 7
    event["experiment_seq"] = 43
    catalog.validate("event", event)
    del event["experiment_seq"]
    with pytest.raises(ValidationError):
        catalog.validate("event", event)


@pytest.mark.parametrize(
    "field,value", [("experiment_seq", 0), ("event_type", "raw write"), ("schema_version", "1.0")]
)
def test_invalid_event_rejected(catalog, example, field, value):
    event = example("event")
    event[field] = value
    with pytest.raises(ValidationError):
        catalog.validate("event", event)


def test_invalid_agent_autonomy(catalog, example):
    agent = example("agent_manifest")
    agent["autonomy_level"] = "L99"
    with pytest.raises(ValidationError):
        catalog.validate("agent_manifest", agent)
