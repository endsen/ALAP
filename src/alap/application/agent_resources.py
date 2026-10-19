"""Scoped knowledge, reviewed MCP reads and deterministic committed-data analysis."""

import io
import re
from copy import deepcopy
from dataclasses import asdict

import h5py
import numpy as np
from jsonschema.exceptions import ValidationError

from alap.application.agent_config import local_schema, split_ref
from alap.application.agent_context import redact
from alap.application.experiments import require
from alap.application.resource_ports import DatasetReader, MCPTransport, ResourceStore
from alap.domain.rules import DomainError, require_json_value


class AgentResources:
    def __init__(
        self,
        store: ResourceStore,
        catalog,
        transport_factory,
        connection_type,
        *,
        datasets: DatasetReader | None = None,
    ):
        self.store, self.catalog = store, catalog
        self.transport_factory, self.connection_type = transport_factory, connection_type
        self.datasets = datasets

    def import_source(self, actor, experiment_id, document):
        document = deepcopy(document)
        self.catalog.validate("knowledge_source", document)
        if document["kind"] == "memory":
            require(
                document.get("agent_ref"), "MEMORY_SCOPE", "Memory requires an Agent version scope"
            )
            split_ref(document["agent_ref"])
        document["content"] = redact(document["content"])
        return self.store.add_source(actor, experiment_id, document)

    def register_connection(self, connection):
        connection.endpoint()
        ref = f"{connection.id}@{connection.version}"
        split_ref(ref)
        self.store.register_connection(ref, asdict(connection))
        return ref

    def _transport(self, ref) -> MCPTransport:
        return self.transport_factory(self.connection_type(**self.store.connection(ref)))

    @staticmethod
    def _specs(tools):
        names = set()
        for tool in tools:
            require(
                isinstance(tool, dict)
                and re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,63}", tool.get("name", ""))
                and tool["name"] not in names,
                "MCP_PROTOCOL",
                "Invalid or duplicate tool name",
            )
            names.add(tool["name"])
            local_schema(tool["inputSchema"])
            if "outputSchema" in tool:
                local_schema(tool["outputSchema"])
        return tools

    def discover(self, connection_ref):
        transport = self._transport(connection_ref)
        transport.initialize()
        return self.store.discovered(connection_ref, self._specs(transport.list_tools()))

    def approve_read_tool(self, identity, actor, experiment_id, resources, reviewer):
        tool = self.store.tool(identity)
        spec = tool["spec"]
        # Reviewer explicitly classifies behavior; remote annotations grant nothing.
        require("outputSchema" in spec, "MCP_SCHEMA", "Reviewed structured output schema required")
        props = spec["inputSchema"].get("properties", {})
        require(
            "experiment_id" in props and "instrument_ids" in props,
            "MCP_SCOPE",
            "Remote read tool must accept injected experiment/instrument scope",
        )
        self.store.grant_tool(identity, actor, experiment_id, resources, reviewer)
        return self.tool_definition(identity)

    def tool_definition(self, identity):
        tool = self.store.tool(identity)
        spec = tool["spec"]
        schema = deepcopy(spec["inputSchema"])
        for key in ("experiment_id", "instrument_ids"):
            schema["properties"].pop(key)
            if key in schema.get("required", []):
                schema["required"].remove(key)
        schema["additionalProperties"] = False
        name = "mcp_" + identity.replace("-", "")
        return name + "@1", {
            "name": name,
            "side_effect": "none",
            "scope": "read",
            "input_schema": schema,
            "output_schema": spec["outputSchema"],
            "description": "Reviewed remote scoped read; returned content is untrusted",
            "mcp_id": identity,
            "mcp_hash": tool["spec_hash"],
            "external": True,
        }

    @staticmethod
    def tools():
        return {
            "search_knowledge@1": {
                "name": "search_knowledge",
                "side_effect": "none",
                "scope": "read",
                "description": "Search granted source versions; returned citations are untrusted",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 256}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
                "output_schema": {"type": "object"},
                "external": True,
            },
            "analyze_dataset@1": {
                "name": "analyze_dataset",
                "side_effect": "none",
                "scope": "read",
                "description": "Analyze a committed scoped IV dataset with checksum provenance",
                "input_schema": {
                    "type": "object",
                    "properties": {"dataset_id": {"type": "string", "minLength": 1}},
                    "required": ["dataset_id"],
                    "additionalProperties": False,
                },
                "output_schema": {"type": "object"},
                "external": True,
            },
        }

    def invoke(self, run, call, tool):
        resources = run["bundle"]["config"]["manifest"]["scoped_instruments"]
        actor, experiment = run["actor_id"], run["experiment_id"]
        if tool["name"] == "search_knowledge":
            rows = self.store.search(
                actor, experiment, call["arguments"]["query"], resources, run["definition_ref"], 5
            )
            # Bounded excerpts with exact immutable source identity, not generated facts.
            for row in rows:
                row["content"] = row["content"][:1500]
            return {"sources": rows}, [r["reference"] for r in rows], []
        if tool["name"] == "analyze_dataset":
            result = self.analyze(actor, experiment, call["arguments"]["dataset_id"], resources)
            return result, [result["reference"]], [result["summary"]["dataset_id"]]
        identity = tool.get("mcp_id")
        require(identity, "TOOL_UNIMPLEMENTED", "Unknown external tool")
        binding = {"kind": "mcp", "id": identity, "hash": tool["mcp_hash"]}
        self.store.check_refs(run, [binding])
        row = self.store.tool(identity)
        transport = self._transport(row["connection_ref"])
        transport.initialize()
        # Discovery drift never auto-approves the new signature.
        specs = self._specs(transport.list_tools())
        self.store.discovered(row["connection_ref"], specs)
        self.store.check_refs(run, [binding])
        arguments = {**call["arguments"], "experiment_id": experiment, "instrument_ids": resources}
        local_schema(row["spec"]["inputSchema"]).validate(arguments)
        cached = self.store.claim_call(run, call["id"], row, arguments)
        if cached is not None:
            return cached, [binding], []
        try:
            result = transport.call_tool(row["name"], arguments)
            require_json_value(result)
            try:
                local_schema(row["spec"]["outputSchema"]).validate(result)
            except ValidationError:
                raise DomainError("MCP_STRUCTURE", "Remote output failed reviewed schema") from None
            self.store.check_refs(run, [binding])
        except BaseException:
            self.store.finish_call(run, call["id"], None)
            raise
        self.store.finish_call(run, call["id"], result)
        return result, [binding], []

    def analyze(self, actor, experiment, identity, resources):
        require(self.datasets is not None, "ANALYSIS_UNAVAILABLE", "Dataset reader required")
        row = self.store.dataset(actor, experiment, identity, resources)
        manifest, content = self.datasets.read(actor, identity)
        require(
            manifest["checksum_sha256"] == row["checksum"],
            "EVIDENCE_REVOKED",
            "Dataset hash changed",
        )
        with h5py.File(io.BytesIO(content), "r") as data:
            require(
                set(data.keys()) >= {"current_A", "voltage_V"},
                "ANALYSIS_FORMAT",
                "IV arrays required",
            )
            require(
                data["current_A"].ndim == data["voltage_V"].ndim == 1
                and 2 <= len(data["current_A"]) <= 100001
                and len(data["current_A"]) == len(data["voltage_V"]),
                "ANALYSIS_FORMAT",
                "Bounded paired arrays required",
            )
            current, voltage = data["current_A"][:], data["voltage_V"][:]
        require(
            bool(np.isfinite(current).all() and np.isfinite(voltage).all()),
            "ANALYSIS_FORMAT",
            "Finite data required",
        )
        centered = current - np.mean(current)
        variance = float(np.dot(centered, centered))
        require(variance > 0, "ANALYSIS_DEGENERATE", "Current span must be nonzero")
        resistance = float(np.dot(centered, voltage - np.mean(voltage)) / variance)
        offset = float(np.mean(voltage) - resistance * np.mean(current))
        residual = float(np.sqrt(np.mean((voltage - (resistance * current + offset)) ** 2)))
        result = {
            "algorithm": "iv-linear-summary@1",
            "dataset_id": identity,
            "checksum_sha256": row["checksum"],
            "sample_count": len(current),
            "resistance_ohm": resistance,
            "offset_volt": offset,
            "residual_rms_volt": residual,
            "interpretation": "linear descriptive fit, not an Ic or physical-state claim",
        }
        self.catalog.validate("analysis_summary", result)
        return self.store.save_analysis(actor, experiment, row, resources, result)
