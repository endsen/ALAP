"""Scope reduction via deployed HTTP and a loaded Chromium dataset page.

Uses an existing committed simulation dataset; creates no device commands.
Short-lived identities/tokens are disabled/revoked even on browser failure.
"""

import hashlib
import json
import os
import secrets
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

from check_agent import execute
from manage import ROOT
from operations import Runtime

from alap.adapters.ops.archive import private_write


def main():
    runtime = Runtime(ROOT / ".local-deploy/simulation")
    for component in ("engine", "agent", "gateway"):
        assert (
            json.loads((runtime.directory / f"{component}.json").read_text())["mode"]
            == "simulation"
        )
    actor = "drill-acl-data-" + secrets.token_hex(6)
    owner = None
    records = []
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        state = json.loads(
            execute(
                runtime,
                """
import json, psycopg
from alap.adapters.postgres.settings import database_url
from alap.adapters.postgres.api import PostgresAPIStore
with psycopg.connect(database_url()) as db:
 row=db.execute("SELECT d.id,d.experiment_id,d.checksum,d.manifest_json->'instrument_ids' "
  "FROM datasets d JOIN experiments e ON e.id=d.experiment_id "
  "WHERE d.state='COMMITTED' AND e.owner_id='admin' ORDER BY d.id LIMIT 1").fetchone()
 assert row and row[3]
 db.execute("INSERT INTO principals(id,issuer,external_subject,kind) VALUES (%s,%s,%s,'user')",
  (ACTOR,'simulation-data-access',ACTOR))
store=PostgresAPIStore(database_url())
print(json.dumps(dict(dataset=row[0],experiment=row[1],checksum=row[2],resources=row[3],
 owner=store.issue_token('admin'),observer=store.issue_token(ACTOR))))
""".replace("ACTOR", repr(actor)),
            )
        )
        owner = state["owner"]

        def api(path, *, observer=False, body=None, revision=None, expected=200):
            headers = {
                "Authorization": "Bearer " + state["observer" if observer else "owner"],
                "Content-Type": "application/json",
                "Idempotency-Key": str(uuid4()),
            }
            if revision is not None:
                headers["If-Match"] = f'"{revision}"'
            req = urllib.request.Request(
                "http://127.0.0.1:3000/api/v1" + path,
                headers=headers,
                method="GET" if body is None else "PUT",
                data=None if body is None else json.dumps(body).encode(),
            )
            try:
                with opener.open(req, timeout=20) as response:
                    status, raw = response.status, response.read()
            except urllib.error.HTTPError as exc:
                status, raw = exc.code, exc.read()
            assert status == expected, (path, status, expected)
            if status == 403:
                result = json.loads(raw)
                assert result["error"]["code"] == "FORBIDDEN"
                assert not {"result", "items", "checksum_sha256", "instrument_ids"} & result.keys()
            records.append({"path": path, "observer": observer, "status": status})
            return raw

        def membership(resources, revoked=False):
            path = "/experiments/" + state["experiment"]
            revision = json.loads(api(path))["revision"]
            api(
                path + "/members/" + actor,
                revision=revision,
                body={
                    "role": "observer",
                    "scope": {"resources": resources, "risk_levels": ["operator_review"]},
                    "revoked": revoked,
                },
            )

        membership(state["resources"])
        path = "/datasets/" + state["dataset"]
        manifest = json.loads(api(path, observer=True))
        assert "storage_key" not in manifest
        api(path + "/series", observer=True)
        assert (
            hashlib.sha256(api(path + "/download", observer=True)).hexdigest() == state["checksum"]
        )
        with tempfile.TemporaryDirectory(prefix="data-access-", dir=ROOT / ".local-deploy") as temp:
            directory = Path(temp)
            private_write(
                directory / "state.json", json.dumps(state | {"directory": temp}).encode()
            )
            with (directory / "browser.log").open("w+") as output:
                child = subprocess.Popen(
                    [
                        "npm",
                        "exec",
                        "--",
                        "playwright",
                        "test",
                        "--config",
                        "playwright.deployment.config.ts",
                        "data-access.spec.ts",
                        "--output",
                        str(directory / "results"),
                    ],
                    cwd=ROOT / "apps/web",
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    env=os.environ
                    | {
                        "ALAP_COMPOSE_BROWSER_STATE": str(directory / "state.json"),
                        "PLAYWRIGHT_BROWSERS_PATH": str(ROOT / ".local-deploy/browsers"),
                    },
                )
                reduced = restored = False
                try:
                    deadline = time.monotonic() + 130
                    while child.poll() is None and time.monotonic() < deadline:
                        if not reduced and (directory / "ready").exists():
                            membership(state["resources"][:-1])
                            for suffix in ("", "/series", "/download"):
                                api(path + suffix, observer=True, expected=403)
                            visible = json.loads(api("/instruments", observer=True))
                            assert {r["instrument_id"] for r in visible} == set(
                                state["resources"][:-1]
                            )
                            api(
                                "/instruments/" + state["resources"][-1],
                                observer=True,
                                expected=403,
                            )
                            reduced = True
                            (directory / "revoked").touch()
                        if not restored and (directory / "hidden").exists():
                            membership(state["resources"])
                            restored = True
                            (directory / "restored").touch()
                        time.sleep(0.1)
                    assert child.poll() == 0 and reduced and restored, (
                        "Dataset access browser check failed"
                    )
                finally:
                    if child.poll() is None:
                        child.terminate()
                        try:
                            child.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait()
                    output.seek(0)
                    text = output.read()
                    for key in ("owner", "observer"):
                        text = text.replace(state[key], "[REDACTED]")
                    (ROOT / "reports/d12d3-data-access-browser.txt").write_text(text)
    finally:
        execute(
            runtime,
            """
import psycopg
from alap.adapters.postgres.settings import database_url
with psycopg.connect(database_url()) as db:
 db.execute('UPDATE api_tokens SET revoked=TRUE WHERE actor_id=%s', (ACTOR,))
 db.execute('UPDATE principals SET disabled_at=clock_timestamp() WHERE id=%s', (ACTOR,))
 db.execute('UPDATE experiment_memberships SET revoked_at=clock_timestamp() WHERE actor_id=%s',
  (ACTOR,))
 db.execute('UPDATE api_tokens SET revoked=TRUE WHERE token_hash=%s', (HASH,))
""".replace("ACTOR", repr(actor)).replace(
                "HASH", repr(hashlib.sha256(owner.encode()).hexdigest() if owner else "")
            ),
        )
        (ROOT / "reports/d12d3-data-access-http.json").write_text(
            json.dumps(records, indent=2) + "\n"
        )


if __name__ == "__main__":
    main()
