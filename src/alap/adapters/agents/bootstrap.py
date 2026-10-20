"""Shared Agent assembly for HTTP control and the independent worker."""

from alap.adapters.api.models import ModelManager
from alap.adapters.mcp.http import MCPConnection, StreamableHTTP
from alap.adapters.postgres.api import PostgresAPIStore
from alap.adapters.secrets.encrypted import EncryptedSecrets
from alap.application.agent_config import AgentRegistry
from alap.application.agent_resources import AgentResources
from alap.application.agent_runtime import AgentRuntime, built_in_tools


def build_agent(dsn, key, catalog, execution_skills, datasets):
    store = PostgresAPIStore(dsn)
    vault = EncryptedSecrets(store, key)
    registry = AgentRegistry(store, catalog, built_in_tools(catalog) | AgentResources.tools(), {})
    manager = ModelManager(store, registry, vault)
    resources = AgentResources(
        store, catalog, lambda c: StreamableHTTP(c, vault), MCPConnection, datasets=datasets
    )
    manager.resources = resources
    manager()
    runtime = AgentRuntime(
        store,
        registry,
        catalog,
        manager.client,
        execution_skills=execution_skills,
        resources=resources,
    )
    return store, vault, registry, manager, resources, runtime
