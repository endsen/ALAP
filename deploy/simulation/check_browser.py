"""Browser acceptance against running Compose services, with an unapproved simulation plan."""

import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from manage import ROOT
from operations import DOCKER, Runtime

from alap.adapters.ops.archive import private_write
from alap.adapters.ops.locking import maintenance_lock


def main():
    runtime = Runtime(ROOT / ".local-deploy/simulation")
    services = runtime.containers()
    if set(services) != {"web", "api", "agent", "engine", "outbox", "gateway", "nats", "postgres"}:
        raise ValueError("All eight simulation services required")
    if not all(c["State"]["Running"] for c in services.values()):
        raise ValueError("Simulation services must be running")
    if (runtime.directory / "restored.json").exists():
        raise ValueError("Do not run browser workload on a restore drill")
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
        str(runtime.directory / "ca.crt") + ":/config/ca.crt:ro",
        services["api"]["Image"],
        "python",
        "-",
    ]
    raw = subprocess.check_output(
        command, env=runtime.env, input=(ROOT / "deploy/simulation/browser_fixture.py").read_bytes()
    )
    state = json.loads(raw)
    tokens = [state["owner"], state["observer"]]

    def api(code):
        return subprocess.check_output(
            runtime.compose + ["exec", "-T", "api", "python", "-"],
            env=runtime.env,
            input=code.encode(),
        ).decode()

    try:
        with tempfile.TemporaryDirectory(prefix="browser-", dir=ROOT / ".local-deploy") as temp:
            private_write(Path(temp) / "state.json", raw)
            env = os.environ | {
                "ALAP_COMPOSE_BROWSER_STATE": str(Path(temp) / "state.json"),
                "PLAYWRIGHT_BROWSERS_PATH": str(ROOT / ".local-deploy/browsers"),
            }
            result = subprocess.run(
                [
                    "npm",
                    "exec",
                    "--",
                    "playwright",
                    "test",
                    "--config",
                    "playwright.deployment.config.ts",
                    "--output",
                    str(Path(temp) / "results"),
                ],
                cwd=ROOT / "apps/web",
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            text = result.stdout
            for token in tokens:
                text = text.replace(token, "[REDACTED]")
            (ROOT / "reports/d12d1-compose-browser.txt").write_text(text)
        if result.returncode:
            return result.returncode
        code = """import json, psycopg
from alap.adapters.postgres.settings import database_url
with psycopg.connect(database_url()) as db:
    db.execute('SET TRANSACTION READ ONLY')
    exp=EXPERIMENT
    result={}
    for table in ('runs','tasks','command_ledger','datasets'):
        query='SELECT state,count(*) FROM '+table+' WHERE experiment_id=%s GROUP BY state'
        result[table]=dict(db.execute(query,(exp,)).fetchall())
    query=('SELECT count(*) FROM outbox_events WHERE experiment_id=%s '
           'AND published_at IS NULL')
    result['unpublished']=db.execute(query,(exp,)).fetchone()[0]
    print(json.dumps(result))
""".replace("EXPERIMENT", repr(state["experiment"]))
        for _ in range(30):
            evidence = json.loads(api(code))
            if evidence["unpublished"] == 0:
                break
            time.sleep(1)
        assert evidence == {
            "runs": {"SUCCEEDED": 1},
            "tasks": {"SUCCEEDED": 3},
            "command_ledger": {"SUCCEEDED": 3},
            "datasets": {"COMMITTED": 1},
            "unpublished": 0,
        }, evidence
        evidence["experiment"] = state["experiment"]
        evidence["images"] = {name: c["Image"] for name, c in services.items()}
        (ROOT / "reports/d12d1-compose-evidence.json").write_text(
            json.dumps(evidence, indent=2) + "\n"
        )
        return 0
    finally:
        hashes = [hashlib.sha256(t.encode()).hexdigest() for t in tokens]
        api(
            "import psycopg\nfrom alap.adapters.postgres.settings import database_url\n"
            "with psycopg.connect(database_url()) as db:\n"
            '    db.execute("UPDATE api_tokens SET revoked=TRUE WHERE token_hash=ANY(%s)",'
            f"({hashes!r},))\n"
        )


if __name__ == "__main__":
    with maintenance_lock(ROOT / ".local-deploy/operations.lock"):
        raise SystemExit(main())
