"""Real deployed data APIs reject missing/corrupt newly acquired simulation artifacts."""

import hashlib
import json
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from check_agent import execute
from manage import ROOT
from operations import DOCKER, SERVICES, Runtime

from alap.adapters.ops.locking import maintenance_lock


def main(*, browser=False):
    runtime = Runtime(ROOT / ".local-deploy/simulation")
    services = runtime.containers()
    assert set(services) == set(SERVICES)
    assert all(c["State"]["Running"] for c in services.values())
    assert not (runtime.directory / "restored.json").exists()
    seed, dataset = None, None

    def counts():
        return json.loads(
            execute(
                runtime,
                """import json,psycopg
from alap.adapters.postgres.settings import database_url
with psycopg.connect(database_url()) as db:
 db.execute('SET TRANSACTION READ ONLY')
 print(json.dumps(dict(commands=db.execute('SELECT count(*) FROM command_ledger').fetchone()[0],
 active=db.execute("SELECT count(*) FROM runs WHERE state NOT IN "
 "('SUCCEEDED','FAILED','CANCELLED')").fetchone()[0])))
""",
            )
        )

    def artifact(mode):
        # Only the newly created experiment's single COMMITTED object may be touched.
        code = """import hashlib,psycopg
from pathlib import Path
from alap.adapters.postgres.settings import database_url
with psycopg.connect(database_url()) as db:
 db.execute('SET TRANSACTION READ ONLY')
 row=db.execute("SELECT storage_key,checksum FROM datasets WHERE id=%s "
     "AND experiment_id=%s AND state='COMMITTED'",(DATASET,EXPERIMENT)).fetchone()
 assert row is not None
 key,checksum=row
 assert key==hashlib.sha256(DATASET.encode()).hexdigest()+'.h5'
 path=Path('/artifacts')/key
 backup=path.with_suffix('.fault-backup')
 mode=MODE
 if mode=='restore':
  if backup.exists():
   assert hashlib.sha256(backup.read_bytes()).hexdigest()==checksum
   backup.replace(path)
 else:
  assert mode in ('missing','corrupt') and not backup.exists()
  assert hashlib.sha256(path.read_bytes()).hexdigest()==checksum
  path.rename(backup)
  if mode=='corrupt': path.write_bytes(b'd12d3 damaged test artifact')
"""
        code = code.replace("DATASET", repr(dataset)).replace(
            "EXPERIMENT", repr(seed["experiment"])
        )
        code = code.replace("MODE", repr(mode))
        subprocess.run(
            runtime.compose + ["exec", "-T", "engine", "python", "-"],
            env=runtime.env,
            input=code.encode(),
            check=True,
            timeout=20,
        )

    before = counts()
    assert before["active"] == 0, "Quiescent simulation required"
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
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def api(path, body=None, revision=None, expected=200, binary=False):
            headers = {"Authorization": "Bearer " + seed["owner"]}
            if body is not None:
                headers |= {"Content-Type": "application/json", "Idempotency-Key": str(uuid4())}
            if revision is not None:
                headers["If-Match"] = f'"{revision}"'
            request = urllib.request.Request(
                "http://127.0.0.1:3000/api/v1" + path,
                data=json.dumps(body).encode() if body is not None else None,
                headers=headers,
            )
            try:
                with opener.open(request, timeout=15) as response:
                    status, raw = response.status, response.read()
            except urllib.error.HTTPError as error:
                status, raw = error.code, error.read()
            assert status == expected, (path, status)
            return raw if binary else json.loads(raw)

        base = "/experiments/" + seed["experiment"]
        snap = api(base + "/snapshot")
        plan = snap["plan_summaries"][0]
        approval = api(
            base + "/approval-requests",
            {
                "plan_revision_id": plan["id"],
                "plan_hash": plan["plan_hash"],
                "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            },
            snap["experiment"]["revision"],
            201,
        )
        approved = api(
            base + "/approvals",
            {
                "approval_id": approval["id"],
                "decision": "approve",
                "state_version": 0,
            },
            approval["revision"],
            201,
        )
        run = api(base + "/runs", {"approval_id": approval["id"]}, approved["revision"], 202)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            snap = api(base + "/snapshot")
            if snap["runs"] and snap["runs"][0]["state"] == "SUCCEEDED":
                break
            time.sleep(0.5)
        else:
            raise AssertionError("Simulation run did not complete; inspect before retrying")
        assert len(snap["datasets"]) == 1 and snap["datasets"][0]["state"] == "COMMITTED"
        dataset = snap["datasets"][0]["id"]
        path = "/datasets/" + dataset
        manifest = api(path)
        original = api(path + "/download", binary=True)
        checksum = hashlib.sha256(original).hexdigest()
        series = api(path + "/series")
        results = []
        for mode in ("missing", "corrupt"):
            try:
                artifact(mode)
                errors = {}
                for suffix in ("", "/download", "/series"):
                    result = api(path + suffix, expected=422)
                    assert result["error"]["code"] == "ARTIFACT_INVALID"
                    errors[suffix or "/manifest"] = result["error"]["code"]
                unchanged = api(base + "/snapshot")
                assert unchanged["datasets"] == snap["datasets"]
                assert unchanged["commands"] == snap["commands"]
                if browser:
                    from data_browser import check_browser

                    check_browser(seed, dataset, mode, checksum, lambda: artifact("restore"))
                results.append({"fault": mode, "errors": errors})
            finally:
                artifact("restore")
            assert api(path) == manifest
            assert hashlib.sha256(api(path + "/download", binary=True)).hexdigest() == checksum
            assert api(path + "/series") == series
        after = counts()
        assert after == {"active": 0, "commands": before["commands"] + 3}
        report = {
            "completed_at": datetime.now(UTC).isoformat(),
            "experiment": seed["experiment"],
            "run_id": run["id"],
            "dataset_id": dataset,
            "sha256": checksum,
            "cases": results,
            "normal_acquisition_commands": 3,
            "fault_command_delta": 0,
            "restored_manifest_and_series": True,
            "counts": after,
            "images": {k: c["Image"] for k, c in services.items()},
        }
        report["browser_recovery_verified"] = browser
        name = "data-browser" if browser else "data-api"
        (ROOT / f"reports/d12d3-{name}-evidence.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print("PASS: missing/corrupt artifact rejected by all three APIs; restored bytes verified")
    finally:
        # Restore before revoking tokens; never delete or recreate the acquisition's metadata.
        try:
            if dataset:
                artifact("restore")
        finally:
            if seed:
                hashes = [
                    hashlib.sha256(seed[k].encode()).hexdigest() for k in ("owner", "observer")
                ]
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
