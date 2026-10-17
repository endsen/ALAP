"""Offline contract catalog and schema-to-domain validation boundary."""

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from alap.domain.rules import (
    DomainError,
    PlanSnapshot,
    freeze_revision,
    require_json_value,
    validate_interval,
    validate_plan_resources_and_dag,
    validate_version_maps,
)


class ContractCatalog:
    def __init__(self, directory: Path):
        self.schemas = {
            path.name.removesuffix(".schema.json"): json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("*.schema.json"))
        }
        if not self.schemas:
            raise ValueError("No contract schemas found")
        for schema in self.schemas.values():
            Draft202012Validator.check_schema(schema)
        # No retrieval callback: unknown references fail, never fetch from the network.
        self.registry = Registry().with_resources(
            (schema["$id"], Resource.from_contents(schema)) for schema in self.schemas.values()
        )

    def validate(self, name: str, value: Any) -> None:
        require_json_value(value)
        Draft202012Validator(
            self.schemas[name], registry=self.registry, format_checker=FormatChecker()
        ).validate(value)

    def validate_proposal(
        self, proposal: dict, *, snapshot_version: int, skills: dict
    ) -> tuple[str, ...]:
        self.validate("plan_proposal", proposal)
        order = validate_plan_resources_and_dag(proposal, snapshot_version=snapshot_version)
        for task in proposal["tasks"]:
            spec = skills.get(task["skill_ref"])
            if spec is None:
                raise DomainError("UNKNOWN_SKILL", "Skill version is not in the approved registry")
            if task["kind"] != spec["kind"]:
                raise DomainError("SKILL_MISMATCH", "Task kind differs from its skill contract")
            if task["success_condition"]["kind"] != spec["success_kind"]:
                raise DomainError("SKILL_MISMATCH", "Task success differs from its skill contract")
            Draft202012Validator.check_schema(spec["input_schema"])
            Draft202012Validator(spec["input_schema"], format_checker=FormatChecker()).validate(
                task["parameters"]
            )
            binding = spec.get("setpoint")
            if binding:
                success = task["success_condition"]
                if (
                    success.get("target") != task["parameters"][binding["parameter"]]
                    or success.get("unit") != binding["unit"]
                    or success.get("quantity") != binding["quantity"]
                ):
                    raise DomainError(
                        "SETPOINT_MISMATCH", "Readback condition differs from setpoint"
                    )
        return order

    def validate_revision(
        self, revision: dict, *, snapshot_version: int, skills: dict
    ) -> PlanSnapshot:
        self.validate("plan_revision", revision)
        self.validate_proposal(
            revision["proposal"], snapshot_version=snapshot_version, skills=skills
        )
        validate_version_maps(revision, set(revision["proposal"]["requested_resources"]))
        return freeze_revision(revision)

    def validate_dataset(self, manifest: dict, *, public: bool = False) -> None:
        self.validate("dataset_manifest", manifest)
        validate_version_maps(manifest, set(manifest["instrument_ids"]))
        interval = manifest["acquisition_interval"]
        validate_interval(interval["start_utc"], interval["end_utc"])
        if public and manifest["status"] != "COMMITTED":
            raise DomainError("DATASET_NOT_COMMITTED", "Only committed data can be published")

    def validate_command(self, command: dict) -> None:
        """Structural/temporal check only; gateway authorization is still required."""
        self.validate("command", command)
        validate_interval(command["issued_at"], command["deadline_at"], strictly_increasing=True)
