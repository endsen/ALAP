"""FR-003/004 foundation: structure, DAG, resources and revision integrity."""

import copy
import itertools
import json

import pytest
from jsonschema import ValidationError

from alap.domain.rules import DomainError


def validate(catalog, proposal, skills, snapshot_version=1):
    return catalog.validate_proposal(proposal, snapshot_version=snapshot_version, skills=skills)


def test_valid_plan_orders_dependencies(catalog, proposal, skills):
    assert validate(catalog, proposal, skills) == ("temperature", "field", "iv")


def test_input_task_order_does_not_change_dag(catalog, proposal, skills):
    for tasks in itertools.permutations(proposal["tasks"]):
        changed = {**proposal, "tasks": list(tasks)}
        assert validate(catalog, changed, skills) == ("temperature", "field", "iv")


def test_stale_snapshot(catalog, proposal, skills):
    with pytest.raises(DomainError, match="PLAN_STALE"):
        validate(catalog, proposal, skills, snapshot_version=2)


@pytest.mark.parametrize("dependency", ["temperature", "iv"])
def test_self_and_indirect_cycles(catalog, proposal, skills, dependency):
    proposal["tasks"][0]["depends_on"] = [dependency]
    with pytest.raises(DomainError, match="CYCLIC_PLAN"):
        validate(catalog, proposal, skills)


def test_unknown_dependency(catalog, proposal, skills):
    proposal["tasks"][0]["depends_on"] = ["missing"]
    with pytest.raises(DomainError, match="MISSING_DEPENDENCY"):
        validate(catalog, proposal, skills)


def test_duplicate_task_ids(catalog, proposal, skills):
    proposal["tasks"].append(copy.deepcopy(proposal["tasks"][0]))
    with pytest.raises(DomainError, match="DUPLICATE_TASK"):
        validate(catalog, proposal, skills)


@pytest.mark.parametrize(
    "resources", [["sim-temp"], ["sim-temp", "sim-magnet", "sim-smu", "extra"]]
)
def test_plan_resource_set_must_match(catalog, proposal, skills, resources):
    proposal["requested_resources"] = resources
    with pytest.raises(DomainError, match="RESOURCE_MISMATCH"):
        validate(catalog, proposal, skills)


def test_primary_device_must_be_reserved(catalog, proposal, skills):
    proposal["tasks"][0]["required_resources"] = ["sim-magnet"]
    with pytest.raises(DomainError, match="UNDECLARED_RESOURCE"):
        validate(catalog, proposal, skills)


def test_condition_device_must_be_reserved(catalog, proposal, skills):
    proposal["tasks"][2]["required_resources"] = ["sim-smu"]
    with pytest.raises(DomainError, match="UNDECLARED_RESOURCE"):
        validate(catalog, proposal, skills)


def test_success_readback_cannot_point_at_other_device(catalog, proposal, skills):
    task = proposal["tasks"][1]
    task["success_condition"]["resource_id"] = "sim-temp"
    with pytest.raises(DomainError, match="INVALID_SUCCESS_CONDITION"):
        validate(catalog, proposal, skills)


def test_stable_window_cannot_exceed_timeout(catalog, proposal, skills):
    proposal["tasks"][0]["timeout_s"] = 1
    with pytest.raises(DomainError, match="INVALID_SUCCESS_CONDITION"):
        validate(catalog, proposal, skills)


@pytest.mark.parametrize("field,value", [("target", 296.0), ("unit", "T"), ("quantity", "field")])
def test_readback_must_match_setpoint(catalog, proposal, skills, field, value):
    proposal["tasks"][0]["success_condition"][field] = value
    with pytest.raises(DomainError, match="SETPOINT_MISMATCH"):
        validate(catalog, proposal, skills)


def test_unknown_skill_version(catalog, proposal, skills):
    proposal["tasks"][0]["skill_ref"] = "set_temperature@2"
    with pytest.raises(DomainError, match="UNKNOWN_SKILL"):
        validate(catalog, proposal, skills)


@pytest.mark.parametrize(
    "field,value", [("kind", "measure_iv"), ("success_condition", {"kind": "readback_verified"})]
)
def test_skill_kind_and_success_cannot_be_overridden(catalog, proposal, skills, field, value):
    proposal["tasks"][0][field] = value
    with pytest.raises(DomainError, match="SKILL_MISMATCH"):
        validate(catalog, proposal, skills)


@pytest.mark.parametrize(
    "parameters",
    [
        {"target_kelvin": 900},
        {"target_celsius": 20},
        {"target_kelvin": True},
        {"target_kelvin": 295, "raw_scpi": "WRITE"},
    ],
)
def test_skill_parameters_are_validated(catalog, proposal, skills, parameters):
    proposal["tasks"][0]["parameters"] = parameters
    with pytest.raises(ValidationError):
        validate(catalog, proposal, skills)


@pytest.mark.parametrize(
    "field", ["preconditions", "success_condition", "skill_ref", "required_resources"]
)
def test_execution_fields_cannot_be_omitted(catalog, proposal, skills, field):
    del proposal["tasks"][0][field]
    with pytest.raises(ValidationError):
        validate(catalog, proposal, skills)


@pytest.mark.parametrize(
    "field,value", [("unit", "mT"), ("max_age_s", 0), ("tolerance", -1), ("min_duration_s", 0)]
)
def test_invalid_stability_contract(catalog, proposal, skills, field, value):
    proposal["tasks"][0]["success_condition"][field] = value
    with pytest.raises(ValidationError):
        validate(catalog, proposal, skills)


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), float("-inf"), {1: "not a JSON key"}]
)
def test_non_json_numbers_and_objects_rejected(catalog, proposal, skills, value):
    proposal["tasks"][0]["parameters"]["target_kelvin"] = value
    with pytest.raises(DomainError, match="INVALID_JSON_VALUE"):
        validate(catalog, proposal, skills)


def test_snapshot_bytes_immune_to_input_mutation(catalog, example, skills):
    revision = example("plan_revision")
    snapshot = catalog.validate_revision(revision, snapshot_version=1, skills=skills)
    original = snapshot.plan_hash
    revision["proposal"]["tasks"][0]["parameters"]["target_kelvin"] = 296.0
    assert snapshot.plan_hash == original
    assert (
        json.loads(snapshot.canonical_bytes)["proposal"]["tasks"][0]["parameters"]["target_kelvin"]
        == 295.0
    )


def test_hash_independent_of_object_key_order(catalog, example, skills):
    revision = example("plan_revision")
    reordered = dict(reversed(list(revision.items())))
    assert (
        catalog.validate_revision(revision, snapshot_version=1, skills=skills).plan_hash
        == catalog.validate_revision(reordered, snapshot_version=1, skills=skills).plan_hash
    )


@pytest.mark.parametrize("change", ["parameter", "condition", "policy", "capability", "skill"])
def test_executable_change_changes_hash(catalog, example, skills, change):
    revision = example("plan_revision")
    before = catalog.validate_revision(revision, snapshot_version=1, skills=skills).plan_hash
    task = revision["proposal"]["tasks"][0]
    if change == "parameter":
        task["parameters"]["target_kelvin"] = 296.0
        task["success_condition"]["target"] = 296.0
    elif change == "condition":
        task["success_condition"]["tolerance"] = 0.2
    elif change == "policy":
        revision["policy_versions"]["sim-temp"] = "sim-policy-2"
    elif change == "capability":
        revision["capability_versions"]["sim-temp"] = "sim-capability-2"
    else:
        skills["set_temperature@2"] = skills["set_temperature@1"]
        task["skill_ref"] = "set_temperature@2"
    assert (
        catalog.validate_revision(revision, snapshot_version=1, skills=skills).plan_hash != before
    )


def test_plan_versions_cover_all_resources(catalog, example, skills):
    revision = example("plan_revision")
    del revision["policy_versions"]["sim-temp"]
    with pytest.raises(DomainError, match="PROVENANCE_MISMATCH"):
        catalog.validate_revision(revision, snapshot_version=1, skills=skills)
