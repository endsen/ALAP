"""Each test migrates its own schema in an explicitly named disposable PostgreSQL database."""

import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from sqlalchemy.engine import make_url

from alap.adapters.postgres.repository import PostgresUnitOfWork
from alap.application.experiments import ExperimentService
from alap.contracts import ContractCatalog

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def database(monkeypatch):
    url = os.environ.get("ALAP_TEST_DATABASE_URL")
    if not url:
        pytest.fail("Real PostgreSQL required: set ALAP_TEST_DATABASE_URL (no in-memory fallback)")
    params = conninfo_to_dict(url)
    if not params.get("dbname", "").startswith("alap_test"):
        pytest.fail("Integration database name must start with alap_test")
    schema = "test_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(url, options=f"-csearch_path={schema}")
    migration_url = (
        make_url(url)
        .set(drivername="postgresql+psycopg")
        .update_query_dict({"options": f"-csearch_path={schema}"})
    )
    monkeypatch.setenv("ALAP_DATABASE_URL", migration_url.render_as_string(hide_password=False))
    config = Config(str(ROOT / "alembic.ini"))
    try:
        command.upgrade(config, "head")
        yield dsn, config
    finally:
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def scenario(database):
    dsn, _ = database
    example = json.loads((ROOT / "contracts/examples/plan_revision.json").read_text())
    skills = json.loads((ROOT / "contracts/examples/simulator_skills.json").read_text())
    uow = PostgresUnitOfWork(dsn)
    service = ExperimentService(
        uow,
        ContractCatalog(ROOT / "contracts"),
        skills=skills,
        policy_versions=example["policy_versions"],
        capability_versions=example["capability_versions"],
    )
    with psycopg.connect(dsn) as connection:
        for actor in ("owner", "approver", "outsider", "observer", "agent", "timer"):
            connection.execute(
                "INSERT INTO principals(id,issuer,external_subject,kind) VALUES (%s,%s,%s,%s)",
                (
                    actor,
                    "alap-timer" if actor == "timer" else "test",
                    actor,
                    "service" if actor in ("agent", "timer") else "user",
                ),
            )
        connection.execute(
            "INSERT INTO samples(id,owner_id,metadata) VALUES ('sample','owner','{}')"
        )
    experiment = service.create_experiment(
        "owner", experiment_id="EXP-SIM-001", sample_id="sample", key="create"
    )
    scope = {
        "resources": example["proposal"]["requested_resources"],
        "risk_levels": ["operator_review"],
    }
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE experiment_memberships SET scope=%s", (Jsonb(scope),))
        for actor, role in [
            ("approver", "approver"),
            ("observer", "observer"),
            ("agent", "approver"),
        ]:
            connection.execute(
                """INSERT INTO experiment_memberships(experiment_id,actor_id,role,scope)
                VALUES (%s,%s,%s,%s)""",
                (experiment["id"], actor, role, Jsonb(scope)),
            )
    return service, uow, example, dsn


def rows(dsn, query, params=()):
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        return connection.execute(query, params).fetchall()
