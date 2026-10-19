"""Explicit deployment assembly; no implicit simulator, public listener or schema migration."""

import hashlib
import json
import os
from pathlib import Path

from alap.adapters.api.app import create_app
from alap.adapters.api.models import ModelManager
from alap.adapters.mcp.http import MCPConnection, StreamableHTTP
from alap.adapters.postgres.api import PostgresAPIStore
from alap.adapters.postgres.repository import PostgresUnitOfWork
from alap.adapters.secrets.encrypted import EncryptedSecrets
from alap.adapters.storage.hdf5 import Hdf5Store
from alap.application.agent_config import AgentRegistry
from alap.application.agent_resources import AgentResources
from alap.application.agent_runtime import AgentRuntime, built_in_tools
from alap.application.api import APIService
from alap.application.control import ControlService
from alap.application.datasets import DatasetService
from alap.application.execution import ExecutionService
from alap.application.experiments import ExperimentService
from alap.contracts import ContractCatalog


def build_service(dsn, key, settings, *, gateways=None, authenticator=None):
    root = Path(__file__).resolve().parents[4]
    catalog = ContractCatalog(root / "contracts")
    base = ExperimentService(
        PostgresUnitOfWork(dsn),
        catalog,
        skills=settings["execution_skills"],
        policy_versions=settings["policy_versions"],
        capability_versions=settings["capability_versions"],
    )
    store = PostgresAPIStore(dsn)
    vault = EncryptedSecrets(store, key)
    registry = AgentRegistry(store, catalog, built_in_tools(catalog) | AgentResources.tools(), {})
    manager = ModelManager(store, registry, vault)
    manager()
    execution = ExecutionService(base, authenticator=authenticator, gateways=gateways or {})
    data = DatasetService(execution, Hdf5Store(settings["artifact_root"]))
    resources = AgentResources(
        store, catalog, lambda c: StreamableHTTP(c, vault), MCPConnection, datasets=data
    )
    manager.resources = resources
    manager()
    runtime = AgentRuntime(
        store, registry, catalog, manager.client, execution_skills=base.skills, resources=resources
    )
    # Published bundles already contain pinned MCP tool definitions. New publication reloads
    # approved definitions separately through explicit grant review; discovery grants nothing.
    return APIService(
        base,
        store,
        registry=registry,
        runtime=runtime,
        resources=resources,
        control=ControlService(execution, engine_actor=settings["engine_actor"]),
        datasets=data,
        secrets=vault,
        configure=manager,
    )


def factory():
    """uvicorn alap.adapters.api.bootstrap:factory --factory --host 127.0.0.1"""
    dsn = os.environ["ALAP_DATABASE_URL"]
    key = Path(os.environ["ALAP_MASTER_KEY_FILE"]).read_bytes().strip()
    settings = json.loads(Path(os.environ["ALAP_API_SETTINGS"]).read_text())
    service = build_service(dsn, key, settings)
    return create_app(service, replay_key=hashlib.sha256(b"alap-api-replay:" + key).digest())
