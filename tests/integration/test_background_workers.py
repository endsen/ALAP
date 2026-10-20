"""Real database ownership/recovery and independent worker processes; no paid APIs."""

import asyncio
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event

import psycopg
import pytest
from cryptography.fernet import Fernet

from alap.application.agent_worker import AgentWorker
from alap.domain.rules import DomainError

from .conftest import rows
from .test_agents import agents, call, start  # noqa: F401
from .test_engine_process import until
from .test_events import events, transport  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture
def worker(agents):  # noqa: F811
    runtime, _, _, _, _, dsn = agents
    with psycopg.connect(dsn) as db:
        db.execute("INSERT INTO principals VALUES('worker','alap-agents','worker','service',NULL)")
    return AgentWorker(runtime, "worker", ["EXP-SIM-001"], limit=1)


def test_agent_worker_advances_persisted_tools_then_model(agents, worker):  # noqa: F811
    runtime, _, model, *_ = agents
    run = start(agents)
    model.outputs = [[call()], "finished"]
    for _ in range(8):
        worker.tick()
    done = runtime.store.load("owner", run["id"])
    assert done["checkpoint"]["status"] == "COMPLETED"
    assert done["checkpoint"]["tool_calls"] == 1
    assert len(model.requests) == 2
    assert rows(agents[-1], "SELECT * FROM command_ledger") == []


def test_agent_allowlist_and_worker_identity(agents, worker):  # noqa: F811
    run = start(agents)
    worker.experiments = ["another-experiment"]
    assert worker.tick()["runs"] == []
    worker.actor = "owner"
    with pytest.raises(DomainError, match="FORBIDDEN"):
        worker.tick()
    assert agents[0].store.load("owner", run["id"])["revision"] == 0
    worker.actor = "worker"
    with psycopg.connect(agents[-1]) as db:
        db.execute("UPDATE principals SET disabled_at=clock_timestamp() WHERE id='worker'")
    with pytest.raises(DomainError, match="FORBIDDEN"):
        worker.tick()


def test_worker_keyset_progress_past_revoked_actor(agents, worker):  # noqa: F811
    runtime, _, model, *_ = agents
    for identity, actor in [("a", "owner"), ("b", "observer")]:
        runtime.start(actor, "EXP-SIM-001", "planner@1", "Read only", identity=identity)
    with psycopg.connect(agents[-1]) as db:
        db.execute(
            "UPDATE experiment_memberships SET revoked_at=clock_timestamp() WHERE actor_id='owner'"
        )
    model.outputs = ["finished"]
    assert worker.tick()["runs"][0]["code"] == "FORBIDDEN"
    assert worker.tick()["runs"][0]["status"] == "COMPLETED"
    assert len(model.requests) == 1


def test_manual_step_and_cancel_exclude_running_worker(agents, worker):  # noqa: F811
    runtime, _, model, *_ = agents
    run = start(agents)
    entered, release = Event(), Event()
    original = model.stream
    model.outputs = ["done"]

    def blocked(request, cancel):
        entered.set()
        assert release.wait(10)
        yield from original(request, cancel)

    model.stream = blocked
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(worker.tick)
        try:
            assert entered.wait(10)
            for action in (runtime.step, runtime.cancel):
                with pytest.raises(DomainError, match="RUN_BUSY"):
                    action("owner", run["id"])
        finally:
            release.set()
        assert future.result()["runs"][0]["status"] == "COMPLETED"
    assert len(model.requests) == 1


def test_lost_agent_lock_cannot_commit_or_replay_model(agents, worker):  # noqa: F811
    runtime, _, model, *_ = agents
    run = start(agents)
    original = model.stream
    model.outputs = ["result after owner loss"]

    def lose_lock(request, cancel):
        owner = runtime.store._owner.get()[1]
        with psycopg.connect(agents[-1], autocommit=True) as db:
            db.execute("SELECT pg_terminate_backend(%s)", (owner.info.backend_pid,))
        yield from original(request, cancel)

    model.stream = lose_lock
    with pytest.raises(psycopg.OperationalError):
        worker.tick()
    assert runtime.store.load("owner", run["id"])["checkpoint"]["stage"] == "inflight"
    replacement = AgentWorker(runtime, "worker", ["EXP-SIM-001"])
    assert replacement.tick()["runs"][0]["status"] == "FAILED"
    assert runtime.store.load("owner", run["id"])["checkpoint"]["error"] == "MODEL_INTERRUPTED"
    assert len(model.requests) == 1


def test_agent_shutdown_admitted_model_cancel_and_no_next_run(agents, worker):  # noqa: F811
    runtime, _, model, *_ = agents
    stop = Event()
    worker.cancel, worker.limit = stop, 20
    for identity in ("a", "b"):
        runtime.start("owner", "EXP-SIM-001", "planner@1", "read", identity=identity)
    original = model.stream
    model.outputs = ["done"]

    def shutdown(request, cancel):
        stop.set()
        yield from original(request, cancel)

    model.stream = shutdown
    assert worker.tick()["runs"] == [{"run_id": "a", "status": "CANCELLED"}]
    assert runtime.store.load("owner", "b")["revision"] == 0


def test_agent_process_recovers_inflight_and_stops(agents, worker, scenario, tmp_path):  # noqa: F811
    runtime = agents[0]
    run = start(agents)
    cp = deepcopy(run["checkpoint"])
    cp.update(stage="inflight", status="RUNNING", iterations=1, reserved_tokens=32000)
    runtime.store.commit(run, cp, {"type": "model_reserved"})
    base = scenario[0]
    settings = {
        "mode": "simulation",
        "agent_actor": "worker",
        "experiment_ids": ["EXP-SIM-001"],
        "execution_skills": base.skills,
        "policy_versions": base.policy_versions,
        "capability_versions": base.capability_versions,
        "artifact_root": str(tmp_path / "objects"),
        "poll_s": 0.05,
    }
    config, key, log = tmp_path / "agent.json", tmp_path / "key", tmp_path / "agent.log"
    config.write_text(json.dumps(settings))
    key.write_bytes(Fernet.generate_key())
    with log.open("wb") as output:
        child = subprocess.Popen(
            [sys.executable, "-m", "alap.adapters.agents.server", "--config", str(config)],
            env={**os.environ, "ALAP_DATABASE_URL": agents[-1], "ALAP_MASTER_KEY_FILE": str(key)},
            stdout=output,
            stderr=output,
        )
    try:
        until(lambda: runtime.store.load("owner", run["id"])["checkpoint"]["status"] == "FAILED")
        assert runtime.store.load("owner", run["id"])["checkpoint"]["error"] == "MODEL_INTERRUPTED"
        child.terminate()
        assert child.wait(10) == 0
        assert '"event": "agent_stopped"' in log.read_text()
        assert agents[-1] not in log.read_text()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(10)


def test_outbox_stop_leaves_unadmitted_claims_pending(events):  # noqa: F811
    service, dsn = events
    stop, sent = Event(), []

    class Publisher:
        async def publish(self, event):
            sent.append(event)
            stop.set()

    count = asyncio.run(service.publish_once("events", Publisher(), stopping=stop.is_set))
    assert count == len(sent) == 1
    assert rows(dsn, "SELECT count(*) n FROM outbox_events WHERE published_at IS NULL")[0]["n"] > 0


def test_outbox_process_delivery_restart_and_sigterm(events, tmp_path):  # noqa: F811
    service, dsn = events

    async def run():
        pub = await transport()
        config, log = tmp_path / "outbox.json", tmp_path / "outbox.log"
        config.write_text(
            json.dumps(
                {
                    "events_actor": "events",
                    "nats_url": os.environ["ALAP_TEST_NATS_URL"],
                    "stream": pub.stream,
                    "subject": pub.subject,
                    "poll_s": 0.05,
                }
            )
        )
        children = []
        try:
            for _ in range(2):
                with log.open("ab") as output:
                    child = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "alap.adapters.messaging.server",
                            "--config",
                            str(config),
                        ],
                        env={**os.environ, "ALAP_DATABASE_URL": dsn},
                        stdout=output,
                        stderr=output,
                    )
                children.append(child)
                await asyncio.to_thread(
                    until,
                    lambda: (
                        rows(
                            dsn, "SELECT count(*) n FROM outbox_events WHERE published_at IS NULL"
                        )[0]["n"]
                        == 0
                    ),
                )
                # Wait for the restarted process to run, rather than terminating before startup.
                await asyncio.to_thread(
                    until, lambda: log.read_text().count('"event": "outbox_tick"') >= len(children)
                )
                child.terminate()
                assert await asyncio.to_thread(child.wait, 10) == 0
            total = rows(dsn, "SELECT count(*) n FROM outbox_events")[0]["n"]
            assert (await pub.js.stream_info(pub.stream)).state.messages == total
            assert dsn not in log.read_text()
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.wait(10)
            await pub.js.delete_stream(pub.stream)
            await pub.close()

    asyncio.run(run())


def test_worker_revocation_stops_remaining_batch(agents, worker):  # noqa: F811
    runtime, _, model, *_ = agents
    worker.limit = 20
    for identity in ("a", "b"):
        runtime.start("owner", "EXP-SIM-001", "planner@1", "read", identity=identity)
    original = model.stream
    model.outputs = ["done"]

    def revoke(request, cancel):
        with psycopg.connect(agents[-1]) as db:
            db.execute("UPDATE principals SET disabled_at=clock_timestamp() WHERE id='worker'")
        yield from original(request, cancel)

    model.stream = revoke
    with pytest.raises(DomainError, match="FORBIDDEN"):
        worker.tick()
    assert runtime.store.load("owner", "a")["checkpoint"]["status"] == "COMPLETED"
    assert runtime.store.load("owner", "b")["revision"] == 0


def test_outbox_loop_reconnects_after_lost_ack(events, monkeypatch, capsys):  # noqa: F811
    from alap.adapters.messaging.nats import JetStreamPublisher
    from alap.adapters.messaging.server import serve

    service, dsn = events

    async def run():
        pub = await transport()
        stop = asyncio.Event()
        original = JetStreamPublisher.publish
        attempts = []
        total = rows(dsn, "SELECT count(*) n FROM outbox_events")[0]["n"]

        async def lost_ack(self, value):
            await original(self, value)
            attempts.append(value["event_id"])
            if len(attempts) == 1:
                # Fault injection advances only the claim expiry; it is not a long-duration test.
                with psycopg.connect(dsn) as db:
                    db.execute(
                        "UPDATE event_delivery_claims "
                        "SET expires_at=clock_timestamp()-interval '1 second'"
                    )
                raise ConnectionError("simulated lost ACK")
            if len(set(attempts)) == total:
                stop.set()

        monkeypatch.setattr(JetStreamPublisher, "publish", lost_ack)
        try:
            await asyncio.wait_for(
                serve(
                    service,
                    {
                        "events_actor": "events",
                        "nats_url": os.environ["ALAP_TEST_NATS_URL"],
                        "stream": pub.stream,
                        "subject": pub.subject,
                        "poll_s": 0.05,
                    },
                    stop,
                ),
                timeout=15,
            )
            assert attempts[0] == attempts[1]
            assert (await pub.js.stream_info(pub.stream)).state.messages == total
            assert (
                rows(dsn, "SELECT count(*) n FROM outbox_events WHERE published_at IS NULL")[0]["n"]
                == 0
            )
            assert '"event": "outbox_retry"' in capsys.readouterr().out
        finally:
            await pub.js.delete_stream(pub.stream)
            await pub.close()

    asyncio.run(run())
