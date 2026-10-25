"""Deploy-only status projection and independent worker closure; seeded context, no LLM."""

import hashlib
import json
import os
import secrets
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from check_agent import execute
from manage import ROOT
from operations import DOCKER, Runtime

from alap.adapters.ops.locking import maintenance_lock


def main():
    runtime = Runtime(ROOT / ".local-deploy/simulation")
    services = runtime.containers()
    assert all(c["State"]["Running"] for c in services.values())
    suffix = secrets.token_hex(6)
    ident = "drill-view-" + suffix
    state = {
        "guide": "guide-view-" + suffix,
        "cases": [
            {
                "id": ident,
                "experiment": "EXP-AGENT-view-" + suffix,
                "vendor": "openai",
            }
        ],
    }
    with tempfile.TemporaryDirectory(prefix="revocation-view-", dir=ROOT / ".local-deploy") as temp:
        directory = Path(temp)
        (directory / "state.json").write_text(json.dumps(state))
        command = [
            DOCKER,
            "run",
            "--rm",
            "-i",
            "--network",
            runtime.project + "_database",
            "-v",
            str(runtime.directory) + ":/private:ro",
            "-v",
            str(directory) + ":/drill:ro",
            "-v",
            str(runtime.directory / "ca.crt") + ":/config/ca.crt:ro",
            services["api"]["Image"],
            "python",
            "-",
        ]
        browser = None
        token = None
        try:
            raw = subprocess.check_output(
                command,
                env=runtime.env,
                timeout=60,
                input=(ROOT / "deploy/simulation/revocation_view_fixture.py").read_bytes(),
            )
            state = json.loads(raw)
            token = state["owner"]
            state["waiting"] = str(directory / "waiting")
            (directory / "browser.json").write_text(json.dumps(state))
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

            def api(path, body=None, expected=200):
                request = urllib.request.Request(
                    "http://127.0.0.1:3000/api/v1" + path,
                    data=None if body is None else json.dumps(body).encode(),
                    headers={
                        "Authorization": "Bearer " + token,
                        "Content-Type": "application/json",
                        "Idempotency-Key": secrets.token_hex(16),
                    },
                )
                try:
                    with opener.open(request, timeout=15) as response:
                        status, value = response.status, json.load(response)
                except urllib.error.HTTPError as error:
                    status, value = error.code, json.load(error)
                assert status == expected, (path, status)
                return value

            path = "/agent-runs/" + state["run"]
            assert api(path)["goal"] == "private deployed goal sentinel"
            api("/knowledge/" + state["source"] + "/share", {"actor_id": "admin", "revoked": True})
            waiting = api(path)
            assert waiting["status"] == "READY" and waiting["access_error"] == "SOURCE_REVOKED"
            assert waiting["goal"] == "内容不可访问" and waiting["result"] is None
            assert "sentinel" not in json.dumps(
                api("/experiments/" + state["experiment"] + "/agent-runs")
            )
            for suffix_path in ("/trace", "/proposals"):
                assert api(path + suffix_path, expected=422)["error"]["code"] == "SOURCE_REVOKED"
            with (ROOT / "reports/d12d3-revocation-view-browser.txt").open("w") as log:
                browser = subprocess.Popen(
                    [
                        "npx",
                        "playwright",
                        "test",
                        "--config",
                        "playwright.deployment.config.ts",
                        "revocation.spec.ts",
                    ],
                    cwd=ROOT / "apps/web",
                    env=os.environ
                    | {"ALAP_COMPOSE_BROWSER_STATE": str(directory / "browser.json")},
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            deadline = time.monotonic() + 60
            while not Path(state["waiting"]).exists():
                assert browser.poll() is None and time.monotonic() < deadline, (
                    "Browser barrier failed"
                )
                time.sleep(0.2)
            # One independent, DB-only container tick under the actual Agent component role.
            # The source was revoked before admission; no model request can occur.
            code = """import json
from pathlib import Path
from threading import Event
from alap.adapters.agents.server import build_worker
root=Path('/private')
settings=json.loads((root/'agent.json').read_text())
settings['experiment_ids']=[EXP]
settings['artifact_root']='/tmp/artifacts'
worker=build_worker((root/'deployment/components/agent.dsn').read_text(),
    (root/'master.key').read_bytes(),settings,Event())
print(json.dumps(worker.tick()))
assert worker.tick()['runs']==[]
""".replace("EXP", repr(state["experiment"]))
            result = json.loads(
                subprocess.check_output(command, input=code.encode(), env=runtime.env, timeout=45)
            )
            assert result["runs"] == [{"run_id": state["run"], "code": "SOURCE_REVOKED"}]
            final = api(path)
            assert final["status"] == "FAILED" and final["access_error"] == "SOURCE_REVOKED"
            assert browser.wait(timeout=75) == 0
            evidence = json.loads(
                execute(
                    runtime,
                    """import json,psycopg
from alap.adapters.postgres.settings import database_url
with psycopg.connect(database_url()) as db:
 db.execute('SET TRANSACTION READ ONLY')
 counts={t:db.execute('SELECT count(*) FROM '+t+' WHERE experiment_id=%s',(EXP,)).fetchone()[0]
         for t in ('plan_revisions','approvals','runs','tasks','command_ledger','datasets')}
 counts['model_reserved']=db.execute("SELECT count(*) FROM agent_trace WHERE run_id=%s "
     "AND event->>'type'='model_reserved'",(RUN,)).fetchone()[0]
 counts['proposals']=db.execute('SELECT count(*) FROM agent_proposals WHERE run_id=%s',
     (RUN,)).fetchone()[0]
 print(json.dumps(counts))
""".replace("EXP", repr(state["experiment"])).replace("RUN", repr(state["run"])),
                )
            )
            assert all(v == 0 for v in evidence.values())
            report = {
                "checked_at": datetime.now(UTC).isoformat(),
                "experiment": state["experiment"],
                "seeded_context": True,
                "worker": "independent DB-only container, one tick",
                "before": waiting,
                "after": final,
                "business_writes": evidence,
                "images": {k: c["Image"] for k, c in services.items()},
            }
            (ROOT / "reports/d12d3-revocation-view-evidence.json").write_text(
                json.dumps(report, indent=2) + "\n"
            )
            print("PASS: restricted view and worker closure; zero model/device calls")
        finally:
            if browser is not None and browser.poll() is None:
                browser.terminate()
                browser.wait(timeout=10)
            if token:
                execute(
                    runtime,
                    """from alap.adapters.postgres.api import PostgresAPIStore
from alap.adapters.postgres.settings import database_url
from alap.application.agent_runtime import AgentRuntime
from alap.domain.rules import DomainError
store=PostgresAPIStore(database_url())
runtime=AgentRuntime(store,None,None,None,execution_skills={})
try:
 runtime.cancel('admin',RUN)
except DomainError as exc:
 if exc.code!='SOURCE_REVOKED': raise
 with store.exclusive(RUN): store.fail_revoked_source('admin',RUN)
""".replace("RUN", repr(state["run"])),
                )
                # Runs retain their audit; revoke the fixture credential and disable configurations.
                execute(
                    runtime,
                    """import psycopg
from alap.adapters.postgres.settings import database_url
with psycopg.connect(database_url()) as db:
 db.execute("UPDATE agent_registry SET state='DISABLED' WHERE ref=ANY(%s)",(REFS,))
 db.execute("UPDATE platform_configs SET enabled=FALSE,revision=revision+1 "
            "WHERE ref=%s AND enabled",(REF,))
 db.execute("UPDATE api_credentials SET enabled=FALSE,revision=revision+1 "
            "WHERE ref=%s AND enabled",(IDENT,))
 db.execute("UPDATE api_tokens SET revoked=TRUE WHERE token_hash=%s",(TOKEN,))
""".replace("REFS", repr([ident + "@1", ident + "@2", state["guide"] + "@1"]))
                    .replace("REF", repr(ident + "@1"))
                    .replace("IDENT", repr(ident))
                    .replace("TOKEN", repr(hashlib.sha256(token.encode()).hexdigest())),
                )


if __name__ == "__main__":
    with maintenance_lock(ROOT / ".local-deploy/operations.lock"):
        main()
