"""Explicit browser drill seed, run only in a maintenance container with /private mounted.

Creates an unapproved plan, never an approval, Run, command or model credential.
Stdout contains short-lived tokens and MUST be captured to a private file by the runner.
"""

import json
import secrets
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from alap.adapters.postgres.api import PostgresAPIStore
from alap.adapters.postgres.repository import PostgresUnitOfWork
from alap.application.experiments import ExperimentService
from alap.contracts import ContractCatalog


def main():
    root = Path("/private")
    settings = json.loads((root / "engine.json").read_text())
    if settings["mode"] != "simulation":
        raise ValueError("Simulation only")
    suffix = secrets.token_hex(6)
    experiment, observer = "EXP-BROWSER-" + suffix, "browser-observer-" + suffix
    api_dsn = (root / "deployment/components/api.dsn").read_text()
    base = ExperimentService(
        PostgresUnitOfWork(api_dsn),
        ContractCatalog(Path("/app/contracts")),
        skills=settings["execution_skills"],
        policy_versions=settings["policy_versions"],
        capability_versions=settings["capability_versions"],
    )
    revision = json.loads(Path("/app/contracts/examples/plan_revision.json").read_text())
    revision["plan_revision_id"] = "PR-BROWSER-" + suffix
    revision["proposal"]["proposal_id"] = "P-BROWSER-" + suffix
    revision["proposal"]["experiment_id"] = experiment
    for task in revision["proposal"]["tasks"]:
        for condition in task["preconditions"] + [task["success_condition"]]:
            if condition["kind"] == "stable_window":
                condition["min_duration_s"] = 0.1
    base.create_experiment(
        "admin",
        experiment_id=experiment,
        sample_id="simulation",
        title="Compose 浏览器验收 " + suffix,
        key="browser-create-" + suffix,
    )
    scope = {
        "resources": revision["proposal"]["requested_resources"],
        "risk_levels": ["operator_review"],
    }
    # Provision only identities/scopes with the maintenance role. All plan writes
    # below use the same restricted API role as the running HTTP service.
    with psycopg.connect((root / "deployment/migration.dsn").read_text()) as db:
        db.execute(
            "INSERT INTO principals(id,issuer,external_subject,kind) VALUES (%s,%s,%s,%s)",
            (observer, "simulation-browser-drill", observer, "user"),
        )
        db.execute("INSERT INTO platform_roles VALUES (%s,'observer')", (observer,))
        db.execute(
            "UPDATE experiment_memberships SET scope=%s WHERE experiment_id=%s",
            (Jsonb(scope), experiment),
        )
        db.execute(
            "INSERT INTO experiment_memberships(experiment_id,actor_id,role,scope) "
            "VALUES (%s,%s,'observer',%s)",
            (experiment, observer, Jsonb(scope)),
        )
    base.save_plan(
        "admin",
        experiment_id=experiment,
        revision=revision,
        expected_revision=1,
        key="browser-plan-" + suffix,
    )
    store = PostgresAPIStore(api_dsn)
    print(
        json.dumps(
            {
                "experiment": experiment,
                "owner": store.issue_token("admin"),
                "observer": store.issue_token(observer),
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        code = getattr(exc, "code", type(exc).__name__)
        raise SystemExit("Browser fixture failed: " + code) from None
