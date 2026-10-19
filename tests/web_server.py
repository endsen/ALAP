"""D10 isolated browser fixture: real API/PG/HDF5 and deterministic offline simulated work."""

import hashlib
import json
import os
import secrets
import signal
import threading
from pathlib import Path
from tempfile import TemporaryDirectory

import psycopg
import pytest
import uvicorn
from cryptography.fernet import Fernet

from alap.adapters.api.app import create_app
from alap.adapters.api.models import ModelManager
from alap.adapters.gateway.auth import Authenticator
from alap.adapters.gateway.journal import Gateway
from alap.adapters.gateway.simulator import Simulator, WallClock
from alap.adapters.mcp.http import MCPConnection, StreamableHTTP
from alap.adapters.postgres.api import PostgresAPIStore
from alap.adapters.secrets.encrypted import EncryptedSecrets
from alap.adapters.storage.hdf5 import Hdf5Store
from alap.application.agent_resources import AgentResources
from alap.application.api import APIService
from alap.application.control import ControlService
from alap.application.datasets import DatasetService
from alap.application.execution import ExecutionService
from alap.application.models import Capabilities, ModelEvent, ModelProfile
from tests.integration.conftest import database, rows, scenario
from tests.integration.test_agents import agents, call, plan_args
from tests.integration.test_resources import mcp_server


def serve():
    with (
        pytest.MonkeyPatch.context() as monkeypatch,
        TemporaryDirectory(prefix="alap-web-") as temp,
    ):
        generator = database.__wrapped__(monkeypatch)
        db = next(generator)
        scenario_value = scenario.__wrapped__(db)
        base, _, example, dsn = scenario_value
        runtime, registry, scripted, _, _, _ = agents.__wrapped__(scenario_value)
        for task in example["proposal"]["tasks"]:
            for condition in task["preconditions"] + [task["success_condition"]]:
                if condition["kind"] == "stable_window":
                    condition["min_duration_s"] = 0.01
        store = PostgresAPIStore(dsn)
        runtime.store = registry.store = store
        key = Fernet.generate_key()
        vault = EncryptedSecrets(store, key)
        root = Path(temp)
        auth = Authenticator(secrets.token_bytes(32))
        simulator = Simulator(root / "physical.sqlite", WallClock())
        gateway = Gateway(
            "gw",
            root / "journal.sqlite",
            authenticator=auth,
            catalog=base.catalog,
            simulator=simulator,
            skills=base.skills,
            policy_versions=base.policy_versions,
            capability_versions=base.capability_versions,
        )
        engine = ExecutionService(base, authenticator=auth, gateways={"gw": gateway})
        datasets = DatasetService(engine, Hdf5Store(root / "objects"))
        with psycopg.connect(dsn) as conn:
            conn.execute(
                "INSERT INTO platform_roles VALUES ('owner','admin'),('observer','observer')"
            )
            conn.execute(
                "INSERT INTO principals VALUES "
                "('engine','alap-engine','engine','service',NULL),"
                "('gateway','local','gateway','service',NULL)"
            )
            conn.execute("INSERT INTO gateways(id,principal_id) VALUES ('gw','gateway')")
            for resource in example["proposal"]["requested_resources"]:
                conn.execute(
                    "INSERT INTO instruments VALUES (%s,'gw',%s,%s,%s,'{}')",
                    (
                        resource,
                        resource,
                        base.policy_versions[resource],
                        base.capability_versions[resource],
                    ),
                )
                conn.execute(
                    "INSERT INTO resource_controls(id,epoch,last_fencing_token,reason) "
                    "SELECT %s,epoch,0,'initial' FROM control_generation",
                    (resource,),
                )
            conn.execute(
                "UPDATE experiments SET title='零场 IV 响应研究',"
                "objective='验证稳定温度和零磁场下的 IV 响应' WHERE id='EXP-SIM-001'"
            )
        engine.bind_gateway("engine", "gw")
        engine.finish_recovery("engine")

        class OfflineModel:
            def __init__(self, ref):
                if ref == "test@1":
                    self.profile = scripted.profile
                else:
                    document = next(
                        r["document"] for r in store.configs("model") if r["ref"] == ref
                    )
                    self.profile = ModelProfile(
                        **(document | {"capabilities": Capabilities(**document["capabilities"])})
                    )

            def stream(self, request, cancel):
                yield ModelEvent(
                    "attempt", request.trace_id, "offline-attempt", "offline", "synthetic", {}
                )
                run = store.load("owner", request.trace_id.rsplit(":", 1)[0])
                snapshot = base.read_snapshot(
                    "owner", run["experiment_id"], base.transaction.snapshot
                )
                proposal = plan_args(example, snapshot["experiment"]["revision"])
                yield ModelEvent(
                    "finish",
                    request.trace_id,
                    "offline-attempt",
                    "offline",
                    "synthetic",
                    {"tool_proposals": [call("propose_plan", proposal)], "usage": None},
                )

        runtime.model_factory = OfflineModel
        mcp_generator = mcp_server.__wrapped__()
        _, mcp_connection = next(mcp_generator)
        resources = AgentResources(
            store,
            base.catalog,
            lambda c: StreamableHTTP(c, vault),
            MCPConnection,
            datasets=datasets,
        )
        resources.register_connection(mcp_connection)
        manager = ModelManager(store, registry, vault)
        manager.resources = resources
        service = APIService(
            base,
            store,
            registry=registry,
            runtime=runtime,
            control=ControlService(engine, engine_actor="engine"),
            datasets=datasets,
            secrets=vault,
            configure=manager,
            resources=resources,
        )
        # Console trials have a separate experiment so duplicate-proposal protection
        # remains active without contaminating the D10 scientific workflow fixture.
        base.create_experiment(
            "owner",
            experiment_id="EXP-CONSOLE",
            sample_id="sample",
            key="console-fixture",
            title="控制台测试",
            objective="offline trial",
        )
        store.set_experiment_scope(
            "owner",
            "EXP-CONSOLE",
            {
                "resources": example["proposal"]["requested_resources"],
                "risk_levels": ["operator_review"],
            },
            1,
        )
        statefile = Path(os.environ.get("ALAP_WEB_TEST_STATE", "/tmp/alap-d10-web.json"))
        state = {
            "owner": store.issue_token("owner", seconds=3600),
            "observer": store.issue_token("observer", seconds=3600),
            "dsn": dsn,
            "experiment": "EXP-SIM-001",
        }
        fd = os.open(statefile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as file:
            json.dump(state, file)
        stop = threading.Event()
        errors = []
        seen = set()

        def worker():
            while not stop.wait(0.15):
                for row in rows(dsn, "SELECT id FROM runs WHERE state='READY' ORDER BY id"):
                    if row["id"] in seen:
                        continue
                    seen.add(row["id"])
                    try:
                        engine.materialize("engine", row["id"])
                        if not engine.acquire("engine", row["id"]):
                            continue
                        for task in example["proposal"]["tasks"]:
                            command = engine.prepare("engine", row["id"], task["id"])
                            engine.dispatch("engine", command)
                            current = rows(
                                dsn, "SELECT state FROM command_ledger WHERE id=%s", (command,)
                            )[0]
                            if current["state"] == "VERIFYING":
                                receipt = rows(
                                    dsn,
                                    "SELECT id FROM gateway_receipts WHERE command_id=%s",
                                    (command,),
                                )[0]["id"]
                                dataset = datasets.stage("engine", command, receipt)
                                datasets.commit("engine", dataset)
                                datasets.finalize("engine", dataset)
                        engine.release("engine", row["id"])
                    except Exception as exc:
                        errors.append(type(exc).__name__)
                        print("Simulation worker stopped at error:", type(exc).__name__, flush=True)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        def terminate(*_):
            # Uvicorn re-raises captured SIGTERM after restoring the previous handler.
            # Convert it to SystemExit so the fixture finally block still runs.
            raise SystemExit(0)

        signal.signal(signal.SIGTERM, terminate)
        try:
            uvicorn.run(
                create_app(service, replay_key=hashlib.sha256(key).digest(), rate_limit=5000),
                host="127.0.0.1",
                port=int(os.environ.get("ALAP_WEB_TEST_API_PORT", "58000")),
                access_log=False,
                timeout_graceful_shutdown=3,
                log_level="warning",
            )
        finally:
            stop.set()
            thread.join(timeout=10)
            mcp_generator.close()
            gateway.close()
            generator.close()
            statefile.unlink(missing_ok=True)
            if errors:
                raise RuntimeError("Simulation worker failures: " + ",".join(errors))


if __name__ == "__main__":
    serve()
