"""Versioned model management shared by API administration and runtime resolution."""

from dataclasses import asdict

from alap.adapters.llm.chat import ChatModelClient
from alap.adapters.llm.transport import ModelFailure, endpoint
from alap.application.agent_config import split_ref
from alap.application.experiments import require
from alap.application.models import Capabilities, ModelProfile, ProviderConnection
from alap.domain.rules import DomainError


class ModelManager:
    def __init__(self, store, registry, secrets):
        self.store, self.registry, self.secrets = store, registry, secrets
        self.resources = None

    def __call__(self, kind=None, document=None):
        if kind is not None:
            try:
                if kind == "connection":
                    config = ProviderConnection(**document)
                    endpoint(config)
                    self.secrets.resolve(config.secret_ref)
                else:
                    config = ModelProfile(
                        **(document | {"capabilities": Capabilities(**document["capabilities"])})
                    )
                    self.connection(config)
                    require(
                        0 < config.output_tokens < config.context_tokens <= 10_000_000
                        and 0 < config.timeout_seconds <= 300
                        and 1 <= config.max_attempts <= 3,
                        "VALIDATION_ERROR",
                        "Invalid model limits",
                    )
                ref = f"{config.id}@{config.version}"
                split_ref(ref)
                result = self.store.config_put(kind, ref, asdict(config))
            except (ModelFailure, TypeError) as exc:
                raise DomainError("VALIDATION_ERROR", "Invalid model configuration") from exc
        self.registry.models = {
            r["ref"]: r["document"] for r in self.store.configs("model") if r["enabled"]
        }
        if self.resources:
            for identity in self.store.approved_tools():
                ref, tool = self.resources.tool_definition(identity)
                self.registry.tools[ref] = tool
        return result if kind else None

    def connection(self, profile):
        ref = f"{profile.connection_id}@{profile.connection_version}"
        rows = [r for r in self.store.configs("connection") if r["ref"] == ref and r["enabled"]]
        require(len(rows) == 1, "CONFIG_DISABLED", "Connection unavailable")
        connection = ProviderConnection(**rows[0]["document"])
        require(connection.enabled, "CONFIG_DISABLED", "Connection unavailable")
        return connection

    def client(self, ref):
        rows = [r for r in self.store.configs("model") if r["ref"] == ref and r["enabled"]]
        require(len(rows) == 1, "CONFIG_DISABLED", "Model unavailable")
        document = rows[0]["document"]
        profile = ModelProfile(
            **(document | {"capabilities": Capabilities(**document["capabilities"])})
        )
        return ChatModelClient(self.connection(profile), profile, secrets=self.secrets)
