"""One-shot simulation provisioning. No approvals, execution runs or LLM credentials."""

import asyncio
import json
from pathlib import Path

import nats
import psycopg
from psycopg.types.json import Jsonb

from alap.adapters.postgres.api import PostgresAPIStore
from alap.adapters.postgres.deployment import initialize, migrate, provision_components
from alap.adapters.postgres.repository import PostgresUnitOfWork
from alap.application.experiments import ExperimentService
from alap.contracts import ContractCatalog


async def initialize_stream(settings):
    for attempt in range(30):
        try:
            connection = await nats.connect(
                settings["nats_url"],
                connect_timeout=2,
                max_reconnect_attempts=0,
                error_cb=ignore_error,
            )
            break
        except OSError, nats.errors.Error:
            if attempt == 29:
                raise RuntimeError("Message service unavailable") from None
            await asyncio.sleep(1)
    try:
        await connection.jetstream().add_stream(
            name=settings["stream"],
            subjects=[settings["subject"]],
            storage="file",
            max_age=604800,
            max_bytes=268435456,
            duplicate_window=120,
        )
    finally:
        await connection.close()


async def ignore_error(_error):
    pass


def main():
    root = Path("/private")
    if not (root / "prepared").is_file() or (root / "deployment").exists():
        raise ValueError("A fresh prepared directory is required")
    settings = json.loads((root / "engine.json").read_text())
    asyncio.run(initialize_stream(json.loads((root / "outbox.json").read_text())))
    admin = (root / "admin.dsn").read_text()
    directory = root / "deployment"
    initialize(admin, "alap_simulation", directory)
    migrate(directory)
    dsn = (directory / "migration.dsn").read_text()
    with psycopg.connect(dsn) as db:
        for identity, issuer, kind in (
            ("admin", "alap-local", "user"),
            ("engine", "alap-engine", "service"),
            ("gateway", "alap-gateway", "service"),
            ("worker", "alap-agents", "service"),
            ("events", "alap-events", "service"),
        ):
            db.execute(
                "INSERT INTO principals(id,issuer,external_subject,kind) VALUES (%s,%s,%s,%s)",
                (identity, issuer, identity, kind),
            )
        db.execute("INSERT INTO platform_roles VALUES ('admin','admin')")
        db.execute("INSERT INTO samples(id,owner_id,metadata) VALUES ('simulation','admin','{}')")
        db.execute("INSERT INTO gateways(id,principal_id) VALUES ('gw','gateway')")
        for resource, policy in settings["policy_versions"].items():
            db.execute(
                "INSERT INTO instruments VALUES (%s,'gw',%s,%s,%s,'{}')",
                (resource, resource, policy, settings["capability_versions"][resource]),
            )
            db.execute(
                "INSERT INTO resource_controls(id,epoch,last_fencing_token,reason) "
                "SELECT %s,epoch,0,'initial' FROM control_generation",
                (resource,),
            )
    base = ExperimentService(
        PostgresUnitOfWork(dsn),
        ContractCatalog(Path("/app/contracts")),
        skills=settings["execution_skills"],
        policy_versions=settings["policy_versions"],
        capability_versions=settings["capability_versions"],
    )
    base.create_experiment("admin", experiment_id="EXP-SIM-001", sample_id="simulation", key="init")
    with psycopg.connect(dsn) as db:
        db.execute(
            "UPDATE experiment_memberships SET scope=%s WHERE experiment_id='EXP-SIM-001'",
            (
                Jsonb(
                    {
                        "resources": list(settings["policy_versions"]),
                        "risk_levels": ["operator_review"],
                    }
                ),
            ),
        )
    provision_components(admin, directory)
    api = PostgresAPIStore((directory / "components/api.dsn").read_text())
    token = api.issue_token("admin")
    with (root / "admin.token").open("x") as file:
        file.write(token + "\n")
    (root / "admin.token").chmod(0o600)
    (root / "ready").write_text("simulation initialized\n")
    print(json.dumps({"event": "simulation_initialized", "token_ttl_seconds": 3600}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never print SQL or credential-bearing DSNs/URLs from drivers.
        print(json.dumps({"event": "simulation_initialization_failed"}))
        raise SystemExit(1) from None
