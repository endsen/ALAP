"""Registry validation: importing Skill data never imports or runs executable code."""

import json
import re
from copy import deepcopy

from jsonschema import Draft202012Validator
from referencing import Registry

from alap.application.agent_ports import AgentStore
from alap.application.experiments import digest, require


def split_ref(ref):
    require(
        isinstance(ref, str) and re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]*@[1-9][0-9]*", ref),
        "UNVERSIONED_REF",
        "Explicit immutable version required",
    )
    return ref.rsplit("@", 1)


def local_schema(value):
    Draft202012Validator.check_schema(value)

    def inspect(node):
        if isinstance(node, dict):
            for k, v in node.items():
                require(
                    k not in {"$ref", "$dynamicRef"} or str(v).startswith("#"),
                    "EXTERNAL_SCHEMA",
                    "Only local references accepted",
                )
                inspect(v)
        elif isinstance(node, list):
            for child in node:
                inspect(child)

    inspect(value)
    return Draft202012Validator(value, registry=Registry())


class AgentRegistry:
    """Internal trusted admin service; HTTP identity management belongs to D09."""

    def __init__(self, store: AgentStore, catalog, tools, models):
        self.store, self.catalog = store, catalog
        self.tools = deepcopy(tools)
        self.models = deepcopy(models)

    def import_skill(self, document):
        document = deepcopy(document)
        self.catalog.validate("skill_manifest", document)
        ref = f"{document['skill_id']}@{document['version']}"
        self.store.import_version("skill", ref, document)
        return ref

    def import_agent(self, document):
        document = deepcopy(document)
        self.catalog.validate("agent_manifest", document["manifest"])
        require(
            set(document) == {"manifest", "token_budget", "context_bytes", "max_tool_calls"},
            "INVALID_CONFIG",
            "Unknown runtime configuration",
        )
        for field in ("token_budget", "context_bytes", "max_tool_calls"):
            require(
                type(document[field]) is int and 0 < document[field] <= 1_000_000,
                "INVALID_BUDGET",
                "Positive bounded budget required",
            )
        manifest = document["manifest"]
        ref = f"{manifest['agent_id']}@{manifest['version']}"
        split_ref(ref)
        self.store.import_version("agent", ref, document)
        return ref

    def _skill(self, ref, visiting, found):
        split_ref(ref)
        require(ref not in visiting, "SKILL_CYCLE", "Cyclic skill dependency")
        if ref in found:
            return
        row = self.store.version("skill", ref)
        require(row["state"] == "PUBLISHED", "SKILL_UNAVAILABLE", "Skill must be published")
        spec = row["document"]
        visiting.add(ref)
        for dep in spec["dependencies"]:
            self._skill(dep, visiting, found)
        visiting.remove(ref)
        found[ref] = spec

    def validate_skill(self, ref):
        row = self.store.version("skill", ref)
        require(row["state"] == "DRAFT", "INVALID_STATE", "Only drafts may publish")
        spec = row["document"]
        for field in ("input_schema", "output_schema"):
            local_schema(spec[field])
        require(
            (
                spec["kind"] == "instruction"
                and spec["executor"] == "context"
                and spec["side_effect"] == "none"
            )
            or (spec["kind"] == "execution" and spec["executor"] == "engine"),
            "SKILL_EXECUTOR",
            "Execution skills belong to deterministic engine",
        )
        for tool in spec["required_tools"]:
            require(tool in self.tools, "UNKNOWN_TOOL", "Unknown tool version")
        found = {}
        for dep in spec["dependencies"]:
            self._skill(dep, {ref}, found)
        return {"ref": ref, "valid": True, "execution": "not_executed"}

    def publish_skill(self, ref, publisher):
        self.validate_skill(ref)
        self.store.publish("skill", ref, publisher)

    def bundle(self, ref, *, published=True):
        row = self.store.version("agent", ref)
        require(
            row["state"] == ("PUBLISHED" if published else "DRAFT"),
            "AGENT_UNAVAILABLE",
            "Agent definition not available",
        )
        if published:
            bundle = row["published_bundle"]
            require(
                bundle is not None and digest(bundle) == row["published_hash"],
                "REGISTRY_CORRUPT",
                "Published binding mismatch",
            )
            self.assert_active(bundle, ref)
            return deepcopy(bundle)
        config = row["document"]
        m = config["manifest"]
        require(
            m["kind"] in {"planner", "instrument", "analysis"},
            "ROLE_UNSUPPORTED",
            "Unsupported Agent role",
        )
        require(m["autonomy_level"] in {"L0", "L1"}, "AUTONOMY_UNSUPPORTED", "L0/L1 only")
        require(
            m["context_policy"] in {"experiment_snapshot_only", "scoped_knowledge"},
            "CONTEXT_UNSUPPORTED",
            "Unsupported context policy",
        )
        require(
            m.get("system_prompt_ref", "alap-policy@1") == "alap-policy@1",
            "PROMPT_UNSUPPORTED",
            "Only the versioned built-in policy is supported",
        )
        if "config_hash" in m:
            require(
                m["config_hash"] == digest({k: v for k, v in m.items() if k != "config_hash"}),
                "CONFIG_HASH",
                "Manifest hash mismatch",
            )
        split_ref(m["model_ref"])
        require(m["model_ref"] in self.models, "MODEL_UNAVAILABLE", "Unknown model profile")
        skills = {}
        for skill in m["skill_refs"]:
            self._skill(skill, set(), skills)
        tools = {}
        for ref_tool in m["allowed_tools"]:
            split_ref(ref_tool)
            require(ref_tool in self.tools, "UNKNOWN_TOOL", "Unknown tool version")
            tool = self.tools[ref_tool]
            require(
                tool["side_effect"] in {"none", "proposal"},
                "PHYSICAL_WRITE_DENIED",
                "LLM cannot receive physical tools",
            )
            require(
                tool["name"] not in {t["name"] for t in tools.values()},
                "TOOL_NAME_COLLISION",
                "Tool names must be unique",
            )
            local_schema(tool["input_schema"])
            local_schema(tool["output_schema"])
            tools[ref_tool] = tool
        for skill in skills.values():
            require(
                set(skill["required_tools"]) <= set(tools),
                "SKILL_SCOPE",
                "Importing a skill does not grant tools",
            )
            require(
                set(skill["resources"]) <= set(m["scoped_instruments"]),
                "SKILL_SCOPE",
                "Skill resources exceed agent scope",
            )
            granted = {t["scope"] for t in tools.values()}
            require(set(skill["required_scopes"]) <= granted, "SKILL_SCOPE", "Missing skill scope")
        bundle = {
            "config": config,
            "skills": skills,
            "tools": tools,
            "model": self.models[m["model_ref"]],
        }
        return json.loads(json.dumps(bundle))

    def validate_agent(self, ref):
        bundle = self.bundle(ref, published=False)
        capabilities = bundle["model"]["capabilities"]
        require(
            capabilities.get("streaming") in {"declared", "tested"},
            "MODEL_UNAVAILABLE",
            "Streaming capability required",
        )
        if bundle["tools"]:
            require(
                capabilities.get("tools") in {"declared", "tested"},
                "MODEL_UNAVAILABLE",
                "Tool capability required",
            )
        return bundle

    def publish_agent(self, ref, publisher):
        bundle = self.validate_agent(ref)
        self.store.publish("agent", ref, publisher, bundle=bundle)
        return digest(bundle)

    def disable(self, kind, ref):
        self.store.disable(kind, ref)

    def assert_active(self, bundle, definition_ref):
        require(
            self.store.version("agent", definition_ref)["state"] == "PUBLISHED",
            "AGENT_DISABLED",
            "Agent disabled",
        )
        for ref in bundle["skills"]:
            require(
                self.store.version("skill", ref)["state"] == "PUBLISHED",
                "SKILL_DISABLED",
                "Skill disabled; no new invocation",
            )
