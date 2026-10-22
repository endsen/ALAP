"""Maintenance seed for isolated deployed model drill; creates no plan, approval or Run."""

import json
from copy import deepcopy
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from alap.adapters.agents.bootstrap import build_agent
from alap.adapters.postgres.repository import PostgresUnitOfWork
from alap.application.experiments import ExperimentService
from alap.contracts import ContractCatalog


def main():
    root, drill = Path("/private"), Path("/drill")
    settings = json.loads((root / "agent.json").read_text())
    assert settings["mode"] == "simulation"
    state = json.loads((drill / "state.json").read_text())
    catalog = ContractCatalog(Path("/app/contracts"))
    dsn = (root / "deployment/components/api.dsn").read_text()
    store, vault, registry, manager, _, _ = build_agent(
        dsn, (root / "master.key").read_bytes(), catalog, settings["execution_skills"], None
    )
    base = ExperimentService(
        PostgresUnitOfWork(dsn),
        catalog,
        skills=settings["execution_skills"],
        policy_versions=settings["policy_versions"],
        capability_versions=settings["capability_versions"],
    )
    guide = json.loads(Path("/app/contracts/examples/skill_manifest.json").read_text())
    guide["skill_id"] = state["guide"]
    registry.import_skill(guide)
    registry.publish_skill(state["guide"] + "@1", "admin")
    refs = [state["guide"] + "@1"]
    for ref, spec in settings["execution_skills"].items():
        doc = deepcopy(guide)
        doc.update(
            skill_id=ref.split("@")[0],
            kind="execution",
            executor="engine",
            side_effect="physical_write",
            input_schema=spec["input_schema"],
            content="Built-in engine skill; never execute in Agent.",
            required_tools=[],
            required_scopes=[],
        )
        registry.import_skill(doc)
        if store.version("skill", ref)["state"] == "DRAFT":
            registry.publish_skill(ref, "admin")
        refs.append(ref)
    resources = ["sim-temp", "sim-magnet", "sim-smu"]
    scope = {"resources": resources, "risk_levels": ["operator_review"]}
    for case in state["cases"]:
        exp, vendor, ident = case["experiment"], case["vendor"], case["id"]
        base.create_experiment(
            "admin",
            experiment_id=exp,
            sample_id="simulation",
            title="离线模型部署验收 " + ident,
            key="create-" + ident,
        )
        with psycopg.connect((root / "deployment/migration.dsn").read_text()) as db:
            db.execute(
                "UPDATE experiment_memberships SET scope=%s WHERE experiment_id=%s",
                (Jsonb(scope), exp),
            )
        vault.put(ident, "offline-d12d2-only", -1)
        manager(
            "connection",
            {
                "id": ident,
                "version": 1,
                "vendor": vendor,
                "base_url": "https://api."
                + vendor
                + ".com"
                + ("/v1" if vendor == "openai" else ""),
                "secret_ref": ident,
            },
        )
        manager(
            "model",
            {
                "id": ident,
                "version": 1,
                "connection_id": ident,
                "connection_version": 1,
                "model": "offline-" + vendor,
                "context_tokens": 64000,
                "output_tokens": 4096,
                "capabilities": {"streaming": "declared", "tools": "declared", "usage": "declared"},
            },
        )
        case_refs = refs
        if "guide" in case:
            own_guide = dict(guide, skill_id=case["guide"])
            registry.import_skill(own_guide)
            registry.publish_skill(case["guide"] + "@1", "admin")
            case_refs = [case["guide"] + "@1", *refs[1:]]
        registry.import_agent(
            {
                "manifest": {
                    "schema_version": "2.0",
                    "agent_id": ident,
                    "version": 1,
                    "kind": "planner",
                    "model_ref": ident + "@1",
                    "max_iterations": 4,
                    "max_runtime_seconds": 120,
                    "allowed_tools": ["read_snapshot@1", "propose_plan@1"],
                    "scoped_instruments": resources,
                    "scoped_experiments": [exp],
                    "autonomy_level": "L1",
                    "skill_refs": case_refs,
                    "context_policy": "experiment_snapshot_only",
                },
                "token_budget": 128000,
                "context_bytes": 48000,
                "max_tool_calls": 2,
            }
        )
        registry.publish_agent(ident + "@1", "admin")
    state["owner"] = store.issue_token("admin")
    print(json.dumps(state))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(
            "Agent fixture failed: " + getattr(exc, "code", type(exc).__name__)
        ) from None
