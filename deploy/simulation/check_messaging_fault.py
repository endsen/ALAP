"""Actual Compose NATS outage/recovery; PostgreSQL remains the business authority."""

import hashlib
import json
import subprocess
import time
import urllib.request
from datetime import UTC, datetime

from manage import ROOT
from operations import DOCKER, SERVICES, Runtime

from alap.adapters.ops.locking import maintenance_lock


def wait_for(read, predicate, timeout=150):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = read()
        if predicate(result):
            return result
        time.sleep(1)
    raise AssertionError("Messaging recovery deadline exceeded")


def main():
    runtime = Runtime(ROOT / ".local-deploy/simulation")
    services = runtime.containers()
    assert set(services) == set(SERVICES)
    assert all(c["State"]["Running"] for c in services.values())
    assert not (runtime.directory / "restored.json").exists()

    def helper(code, network="database"):
        return json.loads(
            subprocess.check_output(
                [
                    DOCKER,
                    "run",
                    "--rm",
                    "-i",
                    "--network",
                    runtime.project + "_" + network,
                    "-v",
                    str(runtime.directory) + ":/private:ro",
                    "-v",
                    str(runtime.directory / "ca.crt") + ":/config/ca.crt:ro",
                    "-e",
                    "SSL_CERT_FILE=/config/ca.crt",
                    services["api"]["Image"],
                    "python",
                    "-",
                ],
                env=runtime.env,
                input=code.encode(),
                timeout=45,
            )
        )

    def counts(experiment=None):
        return helper(
            """import json,psycopg
from pathlib import Path
with psycopg.connect(Path('/private/deployment/components/api.dsn').read_text()) as db:
    db.execute('SET TRANSACTION READ ONLY')
    exp=EXPERIMENT
    where=' WHERE experiment_id=%s' if exp else ''
    args=(exp,) if exp else ()
    total,pending=db.execute('SELECT count(*),count(*) FILTER (WHERE published_at IS NULL) '
        'FROM outbox_events'+where,args).fetchone()
    commands=db.execute('SELECT count(*) FROM command_ledger').fetchone()[0]
    active=db.execute("SELECT count(*) FROM runs WHERE state NOT IN "
        "('SUCCEEDED','FAILED','CANCELLED')").fetchone()[0]
    print(json.dumps(dict(total=total,pending=pending,commands=commands,active_runs=active)))
""".replace("EXPERIMENT", repr(experiment))
        )

    def stream_count():
        return helper(
            """import asyncio,json
from pathlib import Path
from alap.adapters.messaging.nats import JetStreamPublisher
async def main():
    c=json.loads(Path('/private/outbox.json').read_text())
    async def ignore(error): pass
    pub=await JetStreamPublisher.connect(c['nats_url'],stream=c['stream'],
        subject=c['subject'],error_cb=ignore)
    try: print(json.dumps((await pub.js.stream_info(pub.stream)).state.messages))
    finally: await pub.close()
asyncio.run(main())
""",
            "events",
        )

    before = wait_for(counts, lambda c: c["pending"] == 0)
    assert before["active_runs"] == 0, "Quiescent simulation required"
    messages_before = stream_count()
    seed = None
    started = datetime.now(UTC).isoformat()
    try:
        runtime.run(runtime.compose + ["stop", "nats"])
        seed = helper((ROOT / "deploy/simulation/browser_fixture.py").read_text())
        experiment = seed["experiment"]
        pending = counts(experiment)
        assert pending["total"] >= 2 and pending["pending"] == pending["total"]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def snapshot():
            req = urllib.request.Request(
                "http://127.0.0.1:3000/api/v1/experiments/" + experiment + "/snapshot",
                headers={"Authorization": "Bearer " + seed["owner"]},
            )
            with opener.open(req, timeout=10) as response:
                return json.load(response)

        during = snapshot()
        assert during["event_cursor"] == pending["total"]
        assert during["runs"] == [] and during["approvals"] == []
        time.sleep(5)
        assert counts(experiment) == pending
        assert pending["commands"] == before["commands"]
        outbox = runtime.containers()["outbox"]
        assert outbox["State"]["Running"]
        runtime.run(runtime.compose + ["start", "nats"])
        recovered = wait_for(lambda: counts(experiment), lambda c: c["pending"] == 0)
        messages_after = stream_count()
        assert messages_after - messages_before == pending["total"]
        assert snapshot()["event_cursor"] == during["event_cursor"]
        assert recovered["commands"] == before["commands"]
        runtime.run(runtime.compose + ["restart", "outbox"])
        time.sleep(5)
        assert stream_count() == messages_after
        assert counts(experiment) == recovered
        result = {
            "started_at": started,
            "completed_at": datetime.now(UTC).isoformat(),
            "experiment": experiment,
            "outage": pending,
            "recovered": recovered,
            "jetstream_messages_before": messages_before,
            "jetstream_messages_after": messages_after,
            "duplicate_messages_after_worker_restart": 0,
            "snapshot_cursor_during_outage": during["event_cursor"],
            "device_command_delta": 0,
            "images": {k: c["Image"] for k, c in services.items()},
        }
        (ROOT / "reports/d12d3-messaging-evidence.json").write_text(
            json.dumps(result, indent=2) + "\n"
        )
        print("PASS: real NATS outage retains pending events; recovery/restart preserves counts")
    finally:
        # Never leave the normal deployment without its broker after a failed assertion.
        runtime.run(runtime.compose + ["start", "nats", "outbox"])
        if seed:
            hashes = [hashlib.sha256(seed[k].encode()).hexdigest() for k in ("owner", "observer")]
            helper(
                """import json,psycopg
from pathlib import Path
with psycopg.connect(Path('/private/deployment/components/api.dsn').read_text()) as db:
    db.execute('UPDATE api_tokens SET revoked=TRUE WHERE token_hash=ANY(%s)',(HASHES,))
print('{}')
""".replace("HASHES", repr(hashes))
            )


if __name__ == "__main__":
    with maintenance_lock(ROOT / ".local-deploy/operations.lock"):
        main()
