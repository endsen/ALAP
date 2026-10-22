"""Compose API acceptance: a superseded plan cannot reuse its previous approval."""

import hashlib
import json
import subprocess
import time
import urllib.error
import urllib.request
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from check_agent import execute
from manage import ROOT
from operations import DOCKER, SERVICES, Runtime

from alap.adapters.ops.locking import maintenance_lock


def main():
    runtime = Runtime(ROOT / ".local-deploy/simulation")
    services = runtime.containers()
    assert set(services) == set(SERVICES)
    assert all(c["State"]["Running"] for c in services.values())
    assert not (runtime.directory / "restored.json").exists()

    def evidence(experiment):
        return json.loads(
            execute(
                runtime,
                """import json,psycopg
from alap.adapters.postgres.settings import database_url
with psycopg.connect(database_url()) as db:
 db.execute('SET TRANSACTION READ ONLY')
 result={table:db.execute('SELECT count(*) FROM '+table+' WHERE experiment_id=%s',
     (EXP,)).fetchone()[0] for table in ('runs','tasks','command_ledger','datasets')}
 result['global_commands']=db.execute('SELECT count(*) FROM command_ledger').fetchone()[0]
 result['active_runs']=db.execute("SELECT count(*) FROM runs WHERE state NOT IN "
     "('SUCCEEDED','FAILED','CANCELLED')").fetchone()[0]
 result['pending']=db.execute('SELECT count(*) FROM outbox_events '
     'WHERE published_at IS NULL').fetchone()[0]
 print(json.dumps(result))
""".replace("EXP", repr(experiment)),
            )
        )

    before = evidence("")
    assert before["active_runs"] == before["pending"] == 0, "Quiescent simulation required"
    seed = None
    try:
        seed = json.loads(
            subprocess.check_output(
                [
                    DOCKER,
                    "run",
                    "--rm",
                    "-i",
                    "--network",
                    runtime.project + "_database",
                    "-v",
                    str(runtime.directory) + ":/private:ro",
                    "-v",
                    str(runtime.directory / "ca.crt") + ":/config/ca.crt:ro",
                    services["api"]["Image"],
                    "python",
                    "-",
                ],
                env=runtime.env,
                input=(ROOT / "deploy/simulation/browser_fixture.py").read_bytes(),
                timeout=45,
            )
        )
        exp = seed["experiment"]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def api(path, body=None, revision=None, expected=200):
            headers = {"Authorization": "Bearer " + seed["owner"]}
            if body is not None:
                headers |= {"Content-Type": "application/json", "Idempotency-Key": str(uuid4())}
            if revision is not None:
                headers["If-Match"] = f'"{revision}"'
            request = urllib.request.Request(
                "http://127.0.0.1:3000/api/v1/experiments/" + exp + path,
                data=json.dumps(body).encode() if body is not None else None,
                headers=headers,
            )
            try:
                with opener.open(request, timeout=15) as response:
                    status, result = response.status, json.load(response)
            except urllib.error.HTTPError as error:
                status, result = error.code, json.load(error)
            assert status == expected, (path, status, result.get("error"))
            return result

        snapshot = api("/snapshot")
        original = snapshot["plan_summaries"][0]
        approval = api(
            "/approval-requests",
            {
                "plan_revision_id": original["id"],
                "plan_hash": original["plan_hash"],
                "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            },
            snapshot["experiment"]["revision"],
            201,
        )
        approved = api(
            "/approvals",
            {"approval_id": approval["id"], "decision": "approve", "state_version": 0},
            approval["revision"],
            201,
        )
        assert api("/snapshot")["approvals"][0]["state"] == "APPROVED"
        changed = deepcopy(snapshot["plans"][0])
        changed["plan_revision_id"] += "-changed"
        changed["revision"] += 1
        changed["proposal"]["proposal_id"] += "-changed"
        changed["proposal"]["based_on_snapshot_version"] = approved["revision"]
        changed["proposal"]["reason"] = "Deployment approval binding drill"
        # Change an actual bounded setpoint and all matching readback conditions.
        changed["proposal"]["tasks"][0]["parameters"]["target_kelvin"] = 296.0
        for task in changed["proposal"]["tasks"]:
            for condition in task["preconditions"] + [task["success_condition"]]:
                if condition.get("quantity") == "temperature":
                    condition["target"] = 296.0
        saved = api("/proposals", changed, approved["revision"], 201)
        assert saved["plan_hash"] != original["plan_hash"]
        stale_version = api("/runs", {"approval_id": approval["id"]}, approved["revision"], 409)
        assert stale_version["error"]["code"] == "STATE_CONFLICT"
        stale_plan = api("/runs", {"approval_id": approval["id"]}, saved["revision"], 409)
        assert stale_plan["error"]["code"] == "PLAN_STALE"
        final = api("/snapshot")
        assert final["approvals"][0]["state"] == "SUPERSEDED"
        assert len(final["plans"]) == 2 and len(final["approvals"]) == 1
        assert final["experiment"]["revision"] == saved["revision"]
        assert final["event_cursor"] > snapshot["event_cursor"]
        # Observe multiple resident Engine polls, never manually advance or dispatch.
        time.sleep(5)
        after = evidence(exp)
        assert all(
            after[k] == 0 for k in ("runs", "tasks", "command_ledger", "datasets", "active_runs")
        )
        assert after["global_commands"] == before["global_commands"]
        assert api("/snapshot")["event_cursor"] == final["event_cursor"]
        report = {
            "completed_at": datetime.now(UTC).isoformat(),
            "experiment": exp,
            "old_plan_hash": original["plan_hash"],
            "new_plan_hash": saved["plan_hash"],
            "old_approval_state": "SUPERSEDED",
            "stale_snapshot_error": stale_version["error"]["code"],
            "current_snapshot_old_approval_error": stale_plan["error"]["code"],
            "evidence": after,
            "device_command_delta": 0,
            "images": {k: c["Image"] for k, c in services.items()},
        }
        (ROOT / "reports/d12d3-plan-evidence.json").write_text(json.dumps(report, indent=2) + "\n")
        print(
            "PASS: changed plan supersedes approval; stale requests rejected; zero execution writes"
        )
    finally:
        if seed:
            hashes = [hashlib.sha256(seed[k].encode()).hexdigest() for k in ("owner", "observer")]
            execute(
                runtime,
                """import psycopg
from alap.adapters.postgres.settings import database_url
with psycopg.connect(database_url()) as db:
 db.execute('UPDATE api_tokens SET revoked=TRUE WHERE token_hash=ANY(%s)',(HASHES,))
""".replace("HASHES", repr(hashes)),
            )


if __name__ == "__main__":
    with maintenance_lock(ROOT / ".local-deploy/operations.lock"):
        main()
