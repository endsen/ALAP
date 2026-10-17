"""Validate the public projections, including failures the v3.0 smoke script missed."""

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def api_validator():
    document = yaml.safe_load((ROOT / "contracts/openapi.yaml").read_text(encoding="utf-8"))
    document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    uri = "https://alap.invalid/openapi"
    registry = Registry().with_resource(uri, Resource.from_contents(document))

    def get(name):
        return Draft202012Validator(
            {"$ref": f"{uri}#/components/schemas/{name}"},
            registry=registry,
            format_checker=FormatChecker(),
        )

    return get


def test_complete_dataset_is_not_rejected_by_public_api(api_validator, example):
    api_validator("DatasetManifest").validate(example("dataset_manifest"))


def test_api_requires_acquisition_window(api_validator, example):
    manifest = example("dataset_manifest")
    del manifest["acquisition_interval"]
    with pytest.raises(ValidationError):
        api_validator("DatasetManifest").validate(manifest)


def test_api_rejects_staging_manifest(api_validator, example):
    manifest = example("dataset_manifest")
    manifest["status"] = "STAGING"
    with pytest.raises(ValidationError):
        api_validator("DatasetManifest").validate(manifest)


def test_rest_plan_supports_execution_conditions(api_validator, proposal):
    request = {
        k: v
        for k, v in proposal.items()
        if k not in {"proposal_id", "experiment_id", "source_agent_run_id"}
    }
    api_validator("PlanProposalCreate").validate(request)
    request["source_agent_run_id"] = "forged-identity"
    with pytest.raises(ValidationError):
        api_validator("PlanProposalCreate").validate(request)


def test_unvalidated_proposal_does_not_claim_revision(api_validator, proposal):
    api_validator("PlanProposal").validate({**proposal, "state": "PROPOSED"})
    with pytest.raises(ValidationError):
        api_validator("PlanProposal").validate({**proposal, "state": "VALIDATED"})
    api_validator("PlanProposal").validate(
        {**proposal, "state": "VALIDATED", "plan_revision_id": "PR-1", "plan_hash": "a" * 64}
    )


def test_all_schema_files_have_positive_examples(catalog):
    for name in catalog.schemas:
        example = json.loads((ROOT / f"contracts/examples/{name}.json").read_text(encoding="utf-8"))
        catalog.validate(name, example)
