"""Bounded logical Agent steps. No physical dispatch, shell, network tools or approvals."""

from copy import deepcopy
from dataclasses import asdict
from threading import Event
from uuid import NAMESPACE_URL, uuid4, uuid5

from jsonschema.exceptions import ValidationError

from alap.application.agent_config import local_schema
from alap.application.agent_context import build_context, encode, redact
from alap.application.agent_ports import AgentStore
from alap.application.experiments import digest, require
from alap.application.models import ModelRequest, ToolDefinition
from alap.domain.rules import DomainError

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}


def built_in_tools(catalog):
    # Inline catalog references into a provider-facing local schema.
    def inline(node):
        if isinstance(node, list):
            return [inline(v) for v in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            name = node["$ref"].removesuffix(".schema.json")
            return inline(catalog.schemas[name])
        return {k: inline(v) for k, v in node.items() if k not in {"$schema", "$id"}}

    proposal = inline(catalog.schemas["plan_proposal"])
    for key in ("proposal_id", "experiment_id", "source_agent_run_id"):
        proposal["properties"].pop(key)
        proposal["required"].remove(key)
    return {
        "read_snapshot@1": {
            "name": "read_snapshot",
            "side_effect": "none",
            "scope": "read",
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
            "output_schema": {"type": "object"},
            "description": "Read scoped authoritative snapshot",
        },
        "propose_plan@1": {
            "name": "propose_plan",
            "side_effect": "proposal",
            "scope": "proposal",
            "input_schema": proposal,
            "output_schema": {"type": "object"},
            "description": "Persist a plan proposal only; never authorize execution",
        },
    }


class AgentRuntime:
    def __init__(
        self,
        store: AgentStore,
        registry,
        catalog,
        model_factory,
        *,
        execution_skills,
        resources=None,
    ):
        self.store, self.registry, self.catalog = store, registry, catalog
        self.model_factory = model_factory
        self.execution_skills = deepcopy(execution_skills)
        self.resources = resources

    def start(self, actor, experiment_id, definition_ref, goal, *, identity=None, source_refs=()):
        require(
            isinstance(goal, str) and 0 < len(goal) <= 16000,
            "INVALID_GOAL",
            "Bounded goal required",
        )
        bundle = self.registry.bundle(definition_ref)
        manifest = bundle["config"]["manifest"]
        require(
            experiment_id in manifest.get("scoped_experiments", []),
            "FORBIDDEN",
            "Agent experiment scope",
        )
        snapshot = self.store.context(actor, experiment_id, manifest["scoped_instruments"])
        bundle["execution_skills"] = deepcopy(self.execution_skills)
        checkpoint = {
            "status": "READY",
            "stage": "model",
            "goal": redact(goal),
            "snapshot": snapshot,
            "history": [],
            "pending": [],
            "iterations": 0,
            "reserved_tokens": 0,
            "tool_calls": 0,
            "seen_call_ids": [],
            "result": None,
        }
        if source_refs:
            require(self.resources is not None, "RESOURCES_UNAVAILABLE", "Source resolver required")
            provisional = {
                "actor_id": actor,
                "experiment_id": experiment_id,
                "definition_ref": definition_ref,
                "bundle": bundle,
            }
            sources = self.resources.store.materialize(provisional, list(source_refs))
            checkpoint["context_sources"] = sources
            checkpoint["external_refs"] = list(source_refs)
            checkpoint["evidence_datasets"] = [
                s["summary"]["dataset_id"] for s in sources if "summary" in s
            ]
        build_context(bundle, checkpoint)
        return self.store.create(
            identity or str(uuid4()), actor, experiment_id, definition_ref, bundle, checkpoint
        )

    def cancel(self, actor, identity):
        run = self.store.request_cancel(actor, identity)
        if run["checkpoint"]["status"] in TERMINAL:
            return run
        try:
            with self.store.exclusive(identity):
                run = self.store.load(actor, identity)
                if run["checkpoint"]["status"] in TERMINAL:
                    return run
                return self.store.commit(run, deepcopy(run["checkpoint"]), {"type": "cancelled"})
        except DomainError as exc:
            if exc.code != "RUN_BUSY":
                raise
            # The worker still owns execution. Return intent, never fabricate acknowledgement.
            return self.store.load(actor, identity)

    def step(self, actor, identity, cancel=None):
        with self.store.exclusive(identity):
            try:
                return self._step(actor, identity, cancel)
            except DomainError as exc:
                if exc.code == "SOURCE_REVOKED":
                    # Write only a terminal checkpoint/audit on the same ownership session.
                    # Do not return the revoked history, even after successful closure.
                    self.store.fail_revoked_source(actor, identity)
                elif exc.code == "FORBIDDEN":
                    # Only confirmed loss of the original submitter scope can close a run.
                    # Wrong actors and ordinary tool permission denials cannot use this path.
                    self.store.fail_revoked_access(actor, identity)
                raise

    def _step(self, actor, identity, cancel=None):
        run = self.store.load(actor, identity)
        cp = deepcopy(run["checkpoint"])
        if cp["status"] in TERMINAL:
            return run
        try:
            if run.get("cancel_requested_at") is not None:
                return self.store.commit(run, cp, {"type": "cancelled"})
            if cancel is not None and cancel.is_set():
                cp.update(status="CANCELLED", stage="done")
                return self.store.commit(run, cp, {"type": "cancelled"})
            require(run["now"] < run["deadline_at"], "RUNTIME_BUDGET", "Agent deadline exceeded")
            self.registry.assert_active(run["bundle"], run["definition_ref"])
            if cp["stage"] == "inflight":
                # Provider call may have consumed tokens; never replay after an uncommitted result.
                raise DomainError("MODEL_INTERRUPTED", "Uncommitted model call requires a new run")
            if cp["stage"] == "tools":
                return self._tools(run, cp)
            return self._model(run, cp, cancel or Event())
        except (DomainError, ValidationError) as exc:
            if isinstance(exc, DomainError) and exc.code == "STATE_CONFLICT":
                raise
            # Reload revision: model reservation may already have committed.
            run = self.store.load(actor, identity)
            cp = deepcopy(run["checkpoint"])
            code = exc.code if isinstance(exc, DomainError) else "INVALID_TOOL_ARGUMENTS"
            cp.update(status="FAILED", stage="done", error=code)
            return self.store.commit(run, cp, {"type": "blocked", "code": code})

    def _model(self, run, cp, cancel):
        bundle = run["bundle"]
        config, manifest = bundle["config"], bundle["config"]["manifest"]
        require(
            cp["iterations"] < manifest["max_iterations"],
            "ITERATION_BUDGET",
            "Iteration budget exhausted",
        )
        messages, context_trace = build_context(bundle, cp)
        remaining = config["token_budget"] - cp["reserved_tokens"]
        model_config = bundle["model"]
        reservation = min(model_config["context_tokens"], remaining)
        require(
            reservation > model_config["output_tokens"], "TOKEN_BUDGET", "Token budget exhausted"
        )
        cp["iterations"] += 1
        cp["reserved_tokens"] += reservation
        cp.update(stage="inflight", status="RUNNING")
        run = self.store.commit(
            run,
            cp,
            {
                "type": "model_reserved",
                "tokens": reservation,
                "iteration": cp["iterations"],
                "context": context_trace,
            },
        )
        if run["checkpoint"]["status"] in TERMINAL:
            return run
        client = self.model_factory(manifest["model_ref"])
        require(
            asdict(client.profile) == model_config, "MODEL_VERSION_CHANGED", "Pinned model mismatch"
        )
        tools = tuple(
            ToolDefinition(t["name"], t["description"], encode(t["input_schema"]))
            for t in bundle["tools"].values()
        )
        request = ModelRequest(
            messages,
            f"{run['id']}:{cp['iterations']}",
            tools=tools,
            token_budget=reservation,
            total_seconds=max(0.01, (run["deadline_at"] - run["now"]).total_seconds()),
        )
        final = None
        text = ""
        attempts = []
        failed = False
        try:
            for event in client.stream(request, cancel):
                if event.kind == "text_delta":
                    text += str(event.data["text"])
                elif event.kind == "attempt":
                    attempts.append(
                        {"id": event.attempt_id, "vendor": event.vendor, "model": event.model}
                    )
                elif event.kind == "error":
                    failed = not event.data.get("retrying", False)
                elif event.kind == "finish":
                    require(final is None, "MODEL_PROTOCOL", "Duplicate terminal event")
                    final = event
        except DomainError:
            raise
        except Exception:
            raise DomainError("MODEL_FAILURE", "Model failed; remote error omitted") from None
        if cancel.is_set():
            cp.update(status="CANCELLED", stage="done")
        else:
            require(final is not None and not failed, "MODEL_FAILURE", "No valid terminal result")
            pending = deepcopy(final.data["tool_proposals"])
            require(isinstance(pending, list), "MODEL_PROTOCOL", "Invalid proposals")
            cp["pending"] = pending
            cp.update(
                stage="tools" if pending else "done", status="RUNNING" if pending else "COMPLETED"
            )
            if not pending:
                cp["result"] = redact(text)
        event = {
            "type": "model_completed",
            "attempts": attempts,
            "actual_model": final.model if final else None,
            "usage": final.data.get("usage") if final else None,
            "output_hash": digest({"text": text}),
            "decision": cp["stage"],
        }
        return self.store.commit(run, cp, event)

    def _tools(self, run, cp):
        bundle = run["bundle"]
        tools = {t["name"]: (ref, t) for ref, t in bundle["tools"].items()}
        calls = cp["pending"]
        require(
            cp["tool_calls"] + len(calls) <= bundle["config"]["max_tool_calls"],
            "TOOL_BUDGET",
            "Tool invocation budget exhausted",
        )
        current = self.store.context(
            run["actor_id"],
            run["experiment_id"],
            bundle["config"]["manifest"]["scoped_instruments"],
        )
        require(
            current["snapshot_version"] == cp["snapshot"]["snapshot_version"],
            "SNAPSHOT_STALE",
            "Reload authoritative state in a new run",
        )
        invocations, proposals, results = [], [], []
        seen = set(cp["seen_call_ids"])
        for call in calls:
            if self.store.load(run["actor_id"], run["id"]).get("cancel_requested_at") is not None:
                return self.store.commit(run, cp, {"type": "cancelled"})
            require(
                isinstance(call.get("id"), str) and call["id"] and call["id"] not in seen,
                "CALL_ID_REUSED",
                "Tool call identities must be unique",
            )
            seen.add(call["id"])
            require(call["name"] in tools, "TOOL_FORBIDDEN", "Tool not granted")
            ref, tool = tools[call["name"]]
            local_schema(tool["input_schema"]).validate(call["arguments"])
            if ref == "read_snapshot@1":
                result = current
            elif tool.get("external"):
                require(
                    self.resources is not None,
                    "RESOURCES_UNAVAILABLE",
                    "External tools unavailable",
                )
                if tool["name"] == "search_knowledge":
                    require(
                        bundle["config"]["manifest"]["context_policy"] == "scoped_knowledge",
                        "CONTEXT_UNSUPPORTED",
                        "Knowledge access must be explicitly enabled",
                    )
                result, refs, evidence = self.resources.invoke(run, call, tool)
                cp.setdefault("external_refs", []).extend(
                    r for r in refs if r not in cp.get("external_refs", [])
                )
                cp["evidence_datasets"] = sorted(
                    set(cp.get("evidence_datasets", [])) | set(evidence)
                )
            elif ref == "propose_plan@1":
                proposal = deepcopy(call["arguments"])
                proposal.update(
                    proposal_id=str(uuid5(NAMESPACE_URL, run["id"] + ":" + call["id"])),
                    experiment_id=run["experiment_id"],
                    source_agent_run_id=run["id"],
                )
                require(
                    set(proposal["requested_resources"]) <= set(current["resources"]),
                    "FORBIDDEN",
                    "Plan exceeds Agent resources",
                )
                require(
                    set(proposal["evidence_dataset_ids"]) <= set(cp.get("evidence_datasets", [])),
                    "EVIDENCE_UNAVAILABLE",
                    "Proposal evidence must have been analyzed in this scoped run",
                )
                require(
                    all(
                        t["skill_ref"] in bundle["skills"]
                        and bundle["skills"][t["skill_ref"]]["kind"] == "execution"
                        for t in proposal["tasks"]
                    ),
                    "SKILL_SCOPE",
                    "Execution skill not bound",
                )
                for task in proposal["tasks"]:
                    local_schema(bundle["skills"][task["skill_ref"]]["input_schema"]).validate(
                        task["parameters"]
                    )
                self.catalog.validate_proposal(
                    proposal,
                    snapshot_version=current["snapshot_version"],
                    skills=bundle["execution_skills"],
                )
                proposals.append(proposal)
                result = {"proposal_id": proposal["proposal_id"], "state": "PROPOSED"}
            else:
                raise DomainError(
                    "TOOL_UNIMPLEMENTED", "Only built-in read/proposal tools available"
                )
            local_schema(tool["output_schema"]).validate(result)
            invocations.append(
                {
                    "id": call["id"],
                    "tool_ref": ref,
                    "input_hash": digest(call["arguments"]),
                    "result": result,
                    "outcome": "SUCCEEDED",
                }
            )
            results.append({"id": call["id"], "value": result})
        cp["history"].append({"calls": calls, "results": results})
        cp["pending"] = []
        cp["seen_call_ids"] = sorted(seen)
        cp["tool_calls"] += len(calls)
        cp.update(
            stage="done" if proposals else "model", status="COMPLETED" if proposals else "RUNNING"
        )
        if proposals:
            cp["result"] = {"proposal_ids": [p["proposal_id"] for p in proposals]}
        return self.store.commit(
            run,
            cp,
            {
                "type": "tools_completed",
                "tools": [i["tool_ref"] for i in invocations],
                "input_hashes": [i["input_hash"] for i in invocations],
            },
            invocations=invocations,
            proposals=proposals,
            check_snapshot=True,
        )
