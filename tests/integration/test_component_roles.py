"""Separate PostgreSQL logins, lock-only authorization and real worker/application paths."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from psycopg import sql

from alap.adapters.postgres.api import PostgresAPIStore
from alap.adapters.postgres.deployment import migrate, provision_components
from alap.adapters.postgres.engine_owner import PostgresEngineOwner
from alap.adapters.postgres.read_locks import lock_read
from alap.adapters.postgres.repository import PostgresUnitOfWork
from alap.adapters.postgres.resources import PostgresResourceStore
from alap.adapters.storage.hdf5 import Hdf5Store
from alap.application.agent_worker import AgentWorker
from alap.application.datasets import DatasetService
from alap.application.engine_worker import EngineWorker
from alap.application.events import EventService
from alap.application.experiments import ExperimentService

from .conftest import rows
from .test_agents import agents, call, plan_args, start  # noqa: F401
from .test_api import api, get, send  # noqa: F401
from .test_datasets import acquisition  # noqa: F401
from .test_deployment import deployment  # noqa: F401
from .test_engine_recovery import owned_engine
from .test_execution import execution  # noqa: F401
from .test_resources import (  # noqa: F401
    committed,
    mcp_server,
    publish,
    resources,
    scoped_run,
    setup_mcp,
    source,
)

pytestmark = pytest.mark.postgres


@pytest.fixture
def database(deployment):  # noqa: F811
    # Provision test subjects with the trusted maintenance identity, never a worker login.
    return (deployment[0] / "migration.dsn").read_text().strip(), None


@pytest.fixture
def components(deployment):  # noqa: F811
    directory, manifest, admin = deployment
    try:
        provision_components(admin, directory)
        yield {
            name: (directory / "components" / (name + ".dsn")).read_text().strip()
            for name in ("api", "agent", "engine", "outbox")
        }
    finally:
        with psycopg.connect(admin, autocommit=True) as db:
            db.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(manifest["database"])
                )
            )
            for name in ("api", "agent", "engine", "outbox"):
                db.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(
                        sql.Identifier(manifest["database"] + "_" + name)
                    )
                )


@pytest.mark.parametrize(
    "component,statement",
    [
        ("agent", "INSERT INTO command_ledger(id) VALUES ('unauthorized')"),
        ("agent", "UPDATE approvals SET state=state"),
        ("agent", "UPDATE principals SET disabled_at=NULL"),
        ("agent", "UPDATE mcp_grants SET revoked=FALSE"),
        ("agent", "UPDATE api_credentials SET revision=revision"),
        ("engine", "SELECT * FROM api_credentials"),
        ("engine", "INSERT INTO approvals(id) VALUES ('unauthorized')"),
        ("engine", "UPDATE platform_roles SET role='admin'"),
        ("outbox", "SELECT * FROM agent_runs"),
        ("outbox", "UPDATE outbox_events SET payload='{}'"),
        ("outbox", "INSERT INTO outbox_events(event_id) VALUES ('forged')"),
        ("api", "INSERT INTO command_ledger(id) VALUES ('bypass')"),
    ],
)
def test_component_denials(components, component, statement):
    with psycopg.connect(components[component]) as db:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute(statement)


def test_engine_completes_simulation_under_own_role(components, execution, tmp_path):  # noqa: F811
    with PostgresEngineOwner(components["engine"]) as owner:
        engine = owned_engine(owner, execution[0])
        worker = EngineWorker(
            engine, DatasetService(engine, Hdf5Store(tmp_path / "objects")), "engine"
        )
        for _ in range(6):
            assert worker.tick()["problems"] == []
    assert rows(components["engine"], "SELECT state FROM runs")[0]["state"] == "SUCCEEDED"
    assert rows(components["engine"], "SELECT state FROM datasets")[0]["state"] == "COMMITTED"


def test_agent_proposal_and_original_permissions(components, agents):  # noqa: F811
    runtime, registry, model, _, example, dsn = agents
    with psycopg.connect(dsn) as db:
        db.execute("INSERT INTO principals VALUES('worker','alap-agents','worker','service',NULL)")
    runtime.store = registry.store = PostgresAPIStore(components["agent"])
    run = start(agents)
    model.outputs = [[call("propose_plan", plan_args(example, 1))]]
    worker = AgentWorker(runtime, "worker", ["EXP-SIM-001"])
    worker.tick()
    worker.tick()
    assert runtime.store.load("owner", run["id"])["checkpoint"]["status"] == "COMPLETED"
    assert len(rows(components["agent"], "SELECT * FROM agent_proposals")) == 1
    assert rows(components["engine"], "SELECT * FROM command_ledger") == []


def test_outbox_publish_without_event_forgery(components, scenario):
    original, _, _, dsn = scenario
    with psycopg.connect(dsn) as db:
        db.execute("INSERT INTO principals VALUES('events','alap-events','events','service',NULL)")
    base = ExperimentService(
        PostgresUnitOfWork(components["outbox"]),
        original.catalog,
        skills={},
        policy_versions={},
        capability_versions={},
    )
    published = []

    class Publisher:
        async def publish(self, value):
            published.append(value)

    service = EventService(base)
    assert asyncio.run(service.publish_once("events", Publisher())) == len(published) > 0
    assert service.consume("events", "test", published[0])
    assert not service.consume("events", "test", published[0])


def test_read_lock_blocks_revocation_but_cannot_write(components, scenario):
    with psycopg.connect(components["agent"]) as agent:
        lock_read(agent, "principal", "owner")

        def revoke():
            with psycopg.connect(scenario[3]) as admin:
                admin.execute("SET LOCAL lock_timeout='100ms'")
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    admin.execute(
                        "UPDATE principals SET disabled_at=clock_timestamp() WHERE id='owner'"
                    )

        with ThreadPoolExecutor(1) as pool:
            pool.submit(revoke).result()
    with psycopg.connect(components["outbox"]) as outbox:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            lock_read(outbox, "registry", "agent", "anything@1")


def test_api_control_management_paths(components, api, tmp_path):  # noqa: F811
    from cryptography.fernet import Fernet
    from fastapi.testclient import TestClient

    from alap.adapters.api.app import create_app
    from alap.adapters.api.bootstrap import build_service

    base = api[1].base
    service = build_service(
        components["api"],
        Fernet.generate_key(),
        {
            "execution_skills": base.skills,
            "policy_versions": base.policy_versions,
            "capability_versions": base.capability_versions,
            "engine_actor": "engine",
            "artifact_root": str(tmp_path / "objects"),
        },
    )
    with TestClient(create_app(service, replay_key=b"x" * 32)) as client:
        scoped = (client, service, api[2], api[3], components["api"], api[5])
        assert get(scoped, "/me").status_code == 200
        response = send(
            scoped, "PUT", "/credentials/provider", {"value": "offline-test-only"}, revision=-1
        )
        assert response.status_code in (200, 201), response.text


def test_repeated_migration_keeps_roles_separate(components, deployment):  # noqa: F811
    directory, manifest, _ = deployment
    migrate(directory)
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect((directory / "runtime.dsn").read_text()).close()
    with psycopg.connect(components["agent"]) as db:
        assert not db.execute(
            "SELECT pg_has_role(current_user,%s,'MEMBER')", (manifest["runtime"],)
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute("CREATE TABLE forbidden(id int)")


def test_migration_removes_stale_column_grants(components, deployment):  # noqa: F811
    directory, manifest, _ = deployment
    with psycopg.connect((directory / "migration.dsn").read_text()) as owner:
        owner.execute(
            sql.SQL("GRANT UPDATE(payload) ON outbox_events TO {}").format(
                sql.Identifier(manifest["database"] + "_outbox")
            )
        )
    migrate(directory)
    with psycopg.connect(components["outbox"]) as db:
        assert db.execute(
            "SELECT has_column_privilege(current_user,'outbox_events','published_at','UPDATE')"
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute("UPDATE outbox_events SET payload='{}'")


@pytest.mark.parametrize("drift", [False, True])
def test_agent_mcp_discovery_cannot_restore_authority(components, resources, mcp_server, drift):  # noqa: F811
    from copy import deepcopy

    from alap.adapters.agents.langgraph import LangGraphAgentRunner

    service, (runtime, registry, model, _, _, _) = resources
    identity, name, _, run = setup_mcp(resources, mcp_server)
    original = deepcopy(mcp_server[0].spec)
    service.store = PostgresResourceStore(components["agent"])
    runtime.store = registry.store = PostgresAPIStore(components["agent"])
    if drift:
        mcp_server[0].spec["description"] = "changed schema needs fresh review"
    model.outputs = [[call(name.split("@")[0], {"query": "test"})], "done"]
    done = LangGraphAgentRunner(runtime).run("owner", run["id"])
    assert done["checkpoint"]["status"] == ("FAILED" if drift else "COMPLETED")
    assert len(mcp_server[0].calls) == (0 if drift else 1)
    tool = rows(
        components["agent"], "SELECT connection_ref FROM mcp_tools WHERE id=%s", (identity,)
    )
    service.store.discovered(tool[0]["connection_ref"], [original])
    assert rows(components["agent"], "SELECT revoked FROM mcp_grants")[0]["revoked"] == drift


def test_agent_knowledge_context_under_own_role(components, resources):  # noqa: F811
    from alap.adapters.agents.langgraph import LangGraphAgentRunner

    service, (runtime, registry, model, _, _, _) = resources
    identity = source(resources)
    definition = publish(resources, ["search_knowledge@1"])
    run = scoped_run(resources, definition)
    service.store = PostgresResourceStore(components["agent"])
    runtime.store = registry.store = PostgresAPIStore(components["agent"])
    model.outputs = [[call("search_knowledge", {"query": "IV"})], "done"]
    done = LangGraphAgentRunner(runtime).run("owner", run["id"])
    assert done["checkpoint"]["status"] == "COMPLETED"
    assert done["checkpoint"]["external_refs"][0]["id"] == identity


def test_agent_analysis_under_own_role(components, committed):  # noqa: F811
    (service, (_, _, _, _, example, _)), identity = committed
    service.store = PostgresResourceStore(components["agent"])
    service.datasets.transaction = PostgresUnitOfWork(components["agent"])
    service.datasets.base.transaction = service.datasets.transaction
    result = service.analyze(
        "owner", "EXP-SIM-001", identity, example["proposal"]["requested_resources"]
    )
    assert result["summary"]["sample_count"] == 21
