"""D09 application facade. Transport supplies authenticated actor, never client actor IDs."""

from collections import Counter
from copy import deepcopy
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from alap.application.api_ports import APIStore, CredentialManager
from alap.application.events import EventService
from alap.application.experiments import require
from alap.application.series import dataset_series
from alap.domain.rules import DomainError

ADMIN = {
    "setExperimentScope",
    "disableMCP",
    "listSkills",
    "importSkill",
    "publishSkill",
    "disableSkill",
    "listAgents",
    "importAgent",
    "publishAgent",
    "disableAgent",
    "listConnections",
    "putConnection",
    "disableConnection",
    "listModels",
    "putModel",
    "disableModel",
    "listCredentials",
    "putCredential",
    "disableCredential",
    "listMCP",
    "putMCP",
    "discoverMCP",
    "grantMCP",
    "revokeMCP",
    "listAudit",
    "disablePrincipal",
    "revokeToken",
}


def run_view(row):
    cp = row["checkpoint"]
    return {k: row[k] for k in ("id", "experiment_id", "definition_ref", "revision")} | {
        "goal": cp["goal"],
        "status": cp["status"],
        "result": cp.get("result"),
    }


class APIService:
    def __init__(
        self,
        foundation,
        store: APIStore,
        *,
        registry=None,
        runtime=None,
        resources=None,
        control=None,
        datasets=None,
        secrets: CredentialManager | None = None,
        configure=None,
    ):
        self.base, self.store = foundation, store
        self.events = EventService(foundation)
        self.registry, self.runtime, self.resources = registry, runtime, resources
        self.control, self.datasets, self.secrets = control, datasets, secrets
        self.configure = configure

    def access(self, actor, experiment, *, write=False):
        with self.base.transaction() as repo:
            exp = repo.get("experiments", experiment)
            self.base._access(repo, actor, exp, "write" if write else "read")
            return repo.membership(experiment, actor)

    def authorize(self, actor, op, path, body):
        if op in ADMIN:
            self.store.role(actor, {"admin"})
        if op in {"createExperiment", "createSample"}:
            self.store.role(actor, {"admin", "researcher"})
        experiment = path.get("experiment_id")
        if experiment and op != "setExperimentScope":
            self.access(
                actor,
                experiment,
                write=op in {"createProposal", "requestApproval", "startRun", "importKnowledge"},
            )
            if op == "approvePlan":
                with self.base.transaction() as repo:
                    self.base._access(repo, actor, repo.get("experiments", experiment), "approve")
        if "run_id" in path:
            with self.base.transaction() as repo:
                row = repo.get("runs", path["run_id"])
                self.base._access(
                    repo,
                    actor,
                    repo.get("experiments", row["experiment_id"]),
                    "write" if op == "requestRunAction" else "read",
                    repo.get("plan_revisions", row["plan_revision_id"])["plan_json"],
                )
        if "agent_run_id" in path:
            run = self.store.load(actor, path["agent_run_id"])
            if op in {"advanceAgentRun", "cancelAgentRun"}:
                self.access(actor, run["experiment_id"], write=True)
        if op == "createAgentRun":
            self.access(actor, body["experiment_id"], write=True)
        if op in {"searchKnowledge", "analyzeDataset"}:
            self.access(actor, body["experiment_id"])
        if op in {"shareKnowledge", "disableKnowledge"}:
            # Source owner is rechecked inside the use case, also on idempotent replay.
            self.store.check_source_owner(actor, path["source_id"])
        if op == "updateMembership":
            member = self.access(actor, experiment, write=True)
            require(member["role"] == "owner", "FORBIDDEN", "Owner required")

    def execute(self, actor, op, path, body, query, expected, key):
        self.authorize(actor, op, path, body)
        e = path.get("experiment_id")
        ref = path.get("ref")
        if op == "getMe":
            return self.store.identity(actor)
        if op == "createSample":
            return self.store.create_sample(actor, body)
        if op == "listSamples":
            return {"items": self.store.samples(actor)}
        if op == "createExperiment":
            identity = str(uuid5(NAMESPACE_URL, actor + ":experiment:" + key))
            self.base.create_experiment(
                actor,
                experiment_id=identity,
                sample_id=body["sample_id"],
                key=key,
                title=body["title"],
                objective=body["objective"],
            )
            return self.snapshot(actor, identity)["experiment"]
        if op == "listExperiments":
            limit = query.get("limit", 20)
            rows = self.store.experiments(actor, query.get("cursor", ""), limit + 1)
            return {
                "items": [self.experiment_view(r) for r in rows[:limit]],
                "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None,
            }
        if op == "getExperiment":
            return self.snapshot(actor, e)["experiment"]
        if op == "listRunnableAgents":
            return {"items": self.store.runnable_agents(actor, e)}
        if op == "getPlanContext":
            self.access(actor, e, write=True)
            snapshot = self.snapshot(actor, e)
            scope = set(snapshot["permissions"]["resources"])
            return {
                "snapshot_version": snapshot["experiment"]["revision"],
                "next_revision": max((p["revision"] for p in snapshot["plans"]), default=0) + 1,
                "policy_versions": {
                    k: v for k, v in self.base.policy_versions.items() if k in scope
                },
                "capability_versions": {
                    k: v for k, v in self.base.capability_versions.items() if k in scope
                },
            }
        if op == "getDatasetSeries":
            require(self.datasets is not None, "SERVICE_UNAVAILABLE", "Data reader unavailable")
            return dataset_series(self.datasets, actor, path["dataset_id"])
        if op == "getSnapshot":
            return self.snapshot(actor, e)
        if op == "createProposal":
            body = deepcopy(body)
            # Direct HTTP submission is a human/service submission, never an asserted Agent run.
            body["proposal"]["source_agent_run_id"] = "principal:" + actor
            return self.base.save_plan(
                actor, experiment_id=e, revision=body, expected_revision=expected, key=key
            )
        if op == "requestApproval":
            return self.base.request_approval(
                actor,
                experiment_id=e,
                plan_id=body["plan_revision_id"],
                plan_hash=body["plan_hash"],
                expires_at=datetime.fromisoformat(body["expires_at"]),
                expected_revision=expected,
                key=key,
            )
        if op == "approvePlan":
            return self.base.decide_approval(
                actor,
                experiment_id=e,
                approval_id=body["approval_id"],
                event=body["decision"],
                expected_revision=expected,
                expected_version=body["state_version"],
                key=key,
            )
        if op == "startRun":
            return self.base.start_run(
                actor,
                experiment_id=e,
                approval_id=body["approval_id"],
                expected_revision=expected,
                key=key,
            )
        if op == "requestRunAction":
            require(self.control is not None, "SERVICE_UNAVAILABLE", "Control not configured")
            if body["action"] == "resume":
                require(
                    self.control.execution.gateways,
                    "SERVICE_UNAVAILABLE",
                    "Gateway reads not configured",
                )
            getattr(self.control, body["action"])(actor, path["run_id"], expected_version=expected)
            return self.run_record(actor, path["run_id"])
        if op == "getRun":
            return self.run_record(actor, path["run_id"])
        if op == "setExperimentScope":
            return self.store.set_experiment_scope(actor, e, body, expected)
        if op == "disableMCP":
            return self.store.disable_mcp(ref)
        if op == "disableKnowledge":
            return self.store.disable_source(actor, path["source_id"])
        if op == "listKnowledge":
            member = self.access(actor, e)
            return {
                "items": self.store.search(
                    actor,
                    e,
                    "",
                    member["scope"].get("resources", []),
                    query.get("agent_ref"),
                    query.get("limit", 20),
                )
            }
        if op == "updateMembership":
            return self.store.membership_update(
                actor, e, path["actor_id"], body["role"], body["scope"], expected, body["revoked"]
            )
        if op in {"listInstruments", "getInstrument"}:
            items = [
                dict(r, instrument_id=r["id"], status="UNKNOWN", observed_at=None)
                for r in self.store.visible_instruments(actor)
            ]
            if op == "listInstruments":
                return items
            found = [r for r in items if r["id"] == path["instrument_id"]]
            require(found, "FORBIDDEN", "Instrument outside scope")
            return found[0]
        if op in {"getDatasetManifest", "downloadDataset"}:
            require(self.datasets is not None, "SERVICE_UNAVAILABLE", "Data reader unavailable")
            manifest, data = self.datasets.read(actor, path["dataset_id"])
            return data if op == "downloadDataset" else manifest
        if op in {"listSkills", "listAgents"}:
            return {
                "items": self.store.registry_list(
                    "skill" if op == "listSkills" else "agent",
                    query.get("cursor", ""),
                    query.get("limit", 20),
                )
            }
        if op in {"importSkill", "importAgent"}:
            method = (
                self.registry.import_skill if op == "importSkill" else self.registry.import_agent
            )
            return {"ref": method(body)}
        if op in {"publishSkill", "publishAgent"}:
            if self.configure:
                self.configure()
            method = (
                self.registry.publish_skill if op == "publishSkill" else self.registry.publish_agent
            )
            method(ref, actor)
            return {"ref": ref, "state": "PUBLISHED"}
        if op in {"disableSkill", "disableAgent"}:
            self.registry.disable("skill" if op == "disableSkill" else "agent", ref)
            return {"ref": ref, "state": "DISABLED"}
        if op == "createAgentRun":
            return run_view(
                self.runtime.start(
                    actor, body["experiment_id"], body["definition_ref"], body["goal"]
                )
            )
        if op == "getAgentRun":
            return run_view(self.store.load(actor, path["agent_run_id"]))
        if op == "listAgentRuns":
            return {
                "items": [
                    run_view(r)
                    for r in self.store.run_rows(
                        actor, e, query.get("cursor", ""), query.get("limit", 20)
                    )
                ]
            }
        if op in {"advanceAgentRun", "cancelAgentRun"}:
            require(self.runtime is not None, "SERVICE_UNAVAILABLE", "Agent unavailable")
            method = self.runtime.step if op == "advanceAgentRun" else self.runtime.cancel
            return run_view(method(actor, path["agent_run_id"]))
        if op == "getAgentProposals":
            return {"items": self.store.proposals(actor, path["agent_run_id"])}
        if op == "getTrace":
            return {"items": self.store.traces(actor, path["agent_run_id"])}
        if op == "getUsage":
            return self.store.metrics(actor, e)
        if op == "getDashboard":
            snapshot = self.snapshot(actor, e)
            member = self.access(actor, e)
            visible = set(member["scope"].get("resources", []))
            instruments = [
                dict(r, status="UNKNOWN", observed_at=None)
                for r in self.store.visible_instruments(actor)
                if r["id"] in visible
            ]
            return {
                "experiment": snapshot["experiment"],
                "event_cursor": snapshot["event_cursor"],
                "runs_by_state": dict(Counter(r["state"] for r in snapshot["runs"])),
                "approvals_by_state": dict(Counter(r["state"] for r in snapshot["approvals"])),
                "datasets_by_state": dict(Counter(r["state"] for r in snapshot["datasets"])),
                "instruments": instruments,
                "usage": self.store.metrics(actor, e),
            }
        if op in {"listConnections", "listModels"}:
            rows = self.store.configs("connection" if op == "listConnections" else "model")
            for row in rows:
                row["document"].pop("secret_ref", None)
            return {"items": rows}
        if op in {"putConnection", "putModel"}:
            require(self.configure is not None, "SERVICE_UNAVAILABLE", "Model manager unavailable")
            return self.configure("connection" if op == "putConnection" else "model", body)
        if op in {"disableConnection", "disableModel"}:
            return self.store.config_disable(
                "connection" if op == "disableConnection" else "model", ref, expected
            )
        if op == "listCredentials":
            return {"items": self.secrets.list()}
        if op == "putCredential":
            return self.secrets.put(ref, body["value"], expected)
        if op == "disableCredential":
            return self.secrets.disable(ref, expected)
        if op == "listMCP":
            return self.store.mcp_directory()
        if op == "putMCP":
            return {
                "ref": self.resources.register_connection(self.resources.connection_type(**body))
            }
        if op == "discoverMCP":
            return {"tools": self.resources.discover(ref)}
        if op == "grantMCP":
            tool_ref, tool = self.resources.approve_read_tool(
                path["tool_id"], body["actor_id"], body["experiment_id"], body["resources"], actor
            )
            self.registry.tools[tool_ref] = tool
            return {"ref": tool_ref, "tool": tool}
        if op == "revokeMCP":
            self.store.grant_tool(
                path["tool_id"],
                body["actor_id"],
                body["experiment_id"],
                body["resources"],
                actor,
                revoked=True,
            )
            return {"revoked": True}
        if op == "importKnowledge":
            return {"id": self.resources.import_source(actor, e, body)}
        if op == "searchKnowledge":
            return {
                "items": self.store.search(
                    actor,
                    body["experiment_id"],
                    body["query"],
                    body["resources"],
                    body.get("agent_ref"),
                    5,
                )
            }
        if op == "shareKnowledge":
            self.store.share_source(
                actor, path["source_id"], body["actor_id"], revoked=body["revoked"]
            )
            return {"revoked": body["revoked"]}
        if op == "analyzeDataset":
            return self.resources.analyze(
                actor, body["experiment_id"], path["dataset_id"], body["resources"]
            )
        if op == "listAudit":
            return {"items": self.store.audit_rows(query.get("after", 0), query.get("limit", 20))}
        if op == "disablePrincipal":
            require(path["actor_id"] != actor, "FORBIDDEN", "Cannot disable self")
            return self.store.disable_principal(path["actor_id"])
        if op == "revokeToken":
            return self.store.revoke_tokens(path["actor_id"])
        raise DomainError("NOT_FOUND", "Unsupported operation")

    @staticmethod
    def experiment_view(row):
        return {
            k: row[k]
            for k in (
                "id",
                "title",
                "sample_id",
                "objective",
                "state",
                "revision",
                "created_at",
                "event_cursor",
            )
        }

    def snapshot(self, actor, experiment):
        value = self.base.read_snapshot(actor, experiment, self.base.transaction.snapshot)
        member = self.access(actor, experiment)
        resources = set(member["scope"].get("resources", []))
        require(
            all(set(p["proposal"]["requested_resources"]) <= resources for p in value["plans"]),
            "FORBIDDEN",
            "Full snapshot exceeds resource scope",
        )
        value["permissions"] = {
            "write": member["role"] in {"owner", "operator"},
            "approve": member["role"] in {"owner", "approver"}
            and self.store.identity(actor)["kind"] == "user",
            "resources": sorted(resources),
            "role": member["role"],
        }
        value["experiment"] = self.experiment_view(value["experiment"])
        # Only public business fields; no receipt bodies, filesystem paths or service credentials.
        value.pop("events")
        value["approvals"] = [
            {
                k: r[k]
                for k in (
                    "id",
                    "plan_revision_id",
                    "plan_hash",
                    "state",
                    "state_version",
                    "expires_at",
                )
            }
            for r in value["approvals"]
        ]
        value["runs"] = [
            {k: r[k] for k in ("id", "plan_revision_id", "state", "state_version")}
            for r in value["runs"]
        ]
        value["tasks"] = [
            {k: r[k] for k in ("id", "run_id", "state", "state_version")} for r in value["tasks"]
        ]
        return value

    def run_record(self, actor, identity):
        with self.base.transaction.snapshot() as repo:
            row = repo.get("runs", identity)
            self.base._access(
                repo,
                actor,
                repo.get("experiments", row["experiment_id"]),
                "read",
                repo.get("plan_revisions", row["plan_revision_id"])["plan_json"],
            )
            return {
                k: row[k]
                for k in ("id", "experiment_id", "plan_revision_id", "state", "state_version")
            }
