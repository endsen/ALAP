"""Explicit deployment assembly; no implicit simulator, public listener or schema migration."""

import hashlib
import json
import os
from pathlib import Path

from alap.adapters.agents.bootstrap import build_agent
from alap.adapters.api.app import create_app
from alap.adapters.gateway.config import build_gateway_ports
from alap.adapters.postgres.repository import PostgresUnitOfWork
from alap.adapters.postgres.settings import database_url
from alap.adapters.storage.hdf5 import Hdf5Store
from alap.application.api import APIService
from alap.application.control import ControlService
from alap.application.datasets import DatasetService
from alap.application.execution import ExecutionService
from alap.application.experiments import ExperimentService
from alap.contracts import ContractCatalog


def build_service(dsn, key, settings, *, gateways=None, authenticator=None):
    if "gateway_transport" in settings:
        if gateways is not None or authenticator is not None:
            raise ValueError("Configure Gateway transport once, through settings or explicit ports")
        authenticator, gateways = build_gateway_ports(settings["gateway_transport"])
    root = Path(__file__).resolve().parents[4]
    catalog = ContractCatalog(root / "contracts")
    base = ExperimentService(
        PostgresUnitOfWork(dsn),
        catalog,
        skills=settings["execution_skills"],
        policy_versions=settings["policy_versions"],
        capability_versions=settings["capability_versions"],
    )
    execution = ExecutionService(base, authenticator=authenticator, gateways=gateways or {})
    data = DatasetService(execution, Hdf5Store(settings["artifact_root"]))
    store, vault, registry, manager, resources, runtime = build_agent(
        dsn, key, catalog, base.skills, data
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
    dsn = database_url()
    key = Path(os.environ["ALAP_MASTER_KEY_FILE"]).read_bytes().strip()
    settings = json.loads(Path(os.environ["ALAP_API_SETTINGS"]).read_text())
    service = build_service(dsn, key, settings)
    return create_app(service, replay_key=hashlib.sha256(b"alap-api-replay:" + key).digest())
