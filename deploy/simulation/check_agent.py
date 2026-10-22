"""Isolated local TLS provider + real resident Agent + deployed browser acceptance."""

import hashlib
import json
import os
import secrets
import subprocess
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from manage import ROOT
from operations import DOCKER, SERVICES, Runtime

from alap.adapters.ops.archive import private_write
from alap.adapters.ops.locking import maintenance_lock


def certificate(directory):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ALAP offline provider drill")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("api.openai.com"), x509.DNSName("api.deepseek.com")]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    private_write(directory / "provider.crt", cert.public_bytes(serialization.Encoding.PEM))
    private_write(
        directory / "provider.key",
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )


def execute(runtime, code):
    return subprocess.check_output(
        runtime.compose + ["exec", "-T", "api", "python", "-"], env=runtime.env, input=code.encode()
    ).decode()


def evidence(runtime, state):
    code = """import json, psycopg
from alap.adapters.postgres.settings import database_url
cases=CASES
result=[]
with psycopg.connect(database_url()) as db:
    db.execute('SET TRANSACTION READ ONLY')
    for case in cases:
        exp=case['experiment']
        item={'experiment':exp,'vendor':case['vendor']}
        for table in ('runs','tasks','command_ledger','datasets'):
            item[table]=dict(db.execute('SELECT state,count(*) FROM '+table+
                ' WHERE experiment_id=%s GROUP BY state',(exp,)).fetchall())
        row=db.execute('SELECT id,checkpoint,bundle FROM agent_runs WHERE experiment_id=%s',
                       (exp,)).fetchall()
        assert len(row)==1
        identity,cp,bundle=row[0]
        item['agent_status']=cp['status']
        item['iterations']=cp['iterations']
        item['tool_calls']=cp['tool_calls']
        item['reserved_tokens']=cp['reserved_tokens']
        assert cp['status']=='COMPLETED' and cp['iterations']==2 and cp['tool_calls']==2
        assert cp['reserved_tokens']==bundle['config']['token_budget']==128000
        manifest=bundle['config']['manifest']
        assert manifest['model_ref']==case['id']+'@1'
        assert manifest['scoped_experiments']==[exp]
        assert manifest['allowed_tools']==['read_snapshot@1','propose_plan@1']
        item['proposal_count']=db.execute('SELECT count(*) FROM agent_proposals WHERE run_id=%s',
                                         (identity,)).fetchone()[0]
        assert item['proposal_count']==1
        # No device command or approval existed when the Agent committed its proposal.
        completed=db.execute("SELECT occurred_at FROM agent_trace WHERE run_id=%s "
                             "AND event->>'type'='tools_completed' ORDER BY seq DESC LIMIT 1",
                             (identity,)).fetchone()
        assert completed is not None
        item['writes_before_proposal']=db.execute(
            "SELECT count(*) FROM transition_audit WHERE experiment_id=%s "
            "AND kind IN ('approval','run','task','command') "
            "AND occurred_at <= %s", (exp,completed[0])).fetchone()[0]
        assert item['writes_before_proposal']==0
        item['unpublished']=db.execute('SELECT count(*) FROM outbox_events '
            'WHERE experiment_id=%s AND published_at IS NULL',(exp,)).fetchone()[0]
        result.append(item)
print(json.dumps(result))
""".replace("CASES", repr(state["cases"]))
    return json.loads(execute(runtime, code))


def main(*, faults=False):
    runtime = Runtime(ROOT / ".local-deploy/simulation")
    services = runtime.containers()
    assert set(services) == set(SERVICES) and all(c["State"]["Running"] for c in services.values())
    assert not (runtime.directory / "restored.json").exists()
    suffix = secrets.token_hex(6)
    state = {
        "guide": "drill-guide-" + suffix,
        "cases": [
            {
                "experiment": "EXP-AGENT-" + v + "-" + suffix,
                "id": "drill-" + v + "-" + suffix,
                "vendor": v,
            }
            for v in ("openai", "deepseek")
        ],
    }
    if faults:
        from model_faults import cases

        state["cases"] = cases(suffix)
    with tempfile.TemporaryDirectory(prefix="agent-", dir=ROOT / ".local-deploy") as temp:
        directory = Path(temp)
        private_write(directory / "state.json", json.dumps(state).encode())
        certificate(directory)
        (directory / "control").mkdir(mode=0o700)
        settings = json.loads((runtime.directory / "agent.json").read_text())
        assert settings["mode"] == "simulation"
        settings["experiment_ids"] = [c["experiment"] for c in state["cases"]]
        private_write(directory / "agent.json", json.dumps(settings).encode())
        common = {
            "image": services["api"]["Image"],
            "init": True,
            "read_only": True,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "tmpfs": ["/tmp:size=32m,mode=1777"],
            "stop_grace_period": "30s",
        }
        override = {
            "services": {
                "offline-provider": common
                | {
                    "command": ["python", "/fixture/model_provider.py"],
                    "volumes": [
                        str(directory / "control") + ":/control",
                        str(directory / "provider.crt") + ":/drill/provider.crt:ro",
                        str(directory / "provider.key") + ":/drill/provider.key:ro",
                        str(ROOT / "deploy/simulation/model_provider.py")
                        + ":/fixture/model_provider.py:ro",
                    ],
                    "networks": {
                        "offline-model": {"aliases": ["api.openai.com", "api.deepseek.com"]}
                    },
                },
                "agent-drill": common
                | {
                    "command": [
                        "python",
                        "-m",
                        "alap.adapters.agents.server",
                        "--config",
                        "/config/agent.json",
                    ],
                    "environment": {
                        "ALAP_DATABASE_URL_FILE": "/run/secrets/database.dsn",
                        "ALAP_MASTER_KEY_FILE": "/run/secrets/master.key",
                        "SSL_CERT_FILE": "/drill/provider.crt",
                    },
                    "volumes": [
                        "artifacts:/artifacts:ro",
                        str(directory / "provider.crt") + ":/drill/provider.crt:ro",
                        str(directory / "agent.json") + ":/config/agent.json:ro",
                        str(runtime.directory / "deployment/components/agent.dsn")
                        + ":/run/secrets/database.dsn:ro",
                        str(runtime.directory / "master.key") + ":/run/secrets/master.key:ro",
                        str(runtime.directory / "ca.crt") + ":/config/ca.crt:ro",
                    ],
                    "networks": ["database", "offline-model"],
                },
            },
            "networks": {"offline-model": {"internal": True}},
        }
        private_write(directory / "compose.yaml", yaml.safe_dump(override).encode())
        drill = Runtime(runtime.directory, override=directory / "compose.yaml")
        token = None
        try:
            raw = subprocess.check_output(
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
                    str(directory) + ":/drill:ro",
                    "-v",
                    str(runtime.directory / "ca.crt") + ":/config/ca.crt:ro",
                    services["api"]["Image"],
                    "python",
                    "-",
                ],
                env=runtime.env,
                input=(ROOT / "deploy/simulation/agent_fixture.py").read_bytes(),
            )
            state = json.loads(raw)
            token = state["owner"]
            private_write(directory / "browser.json", raw)
            drill.run(
                drill.compose
                + ["up", "-d", "--no-build", "--pull", "never", "offline-provider", "agent-drill"]
            )
            for _ in range(30):
                if "offline-provider-ready" in drill.output(
                    drill.compose + ["logs", "offline-provider"]
                ):
                    break
                time.sleep(1)
            else:
                raise ValueError("Offline provider did not become ready")
            deployed = drill.containers()
            # DNS aliases and the test CA never enter normal services; worker has no egress.
            assert set(deployed["agent-drill"]["NetworkSettings"]["Networks"]) == {
                runtime.project + "_database",
                runtime.project + "_offline-model",
            }
            if faults:
                from model_faults import run_faults

                return run_faults(runtime, state, directory, deployed)
            result = subprocess.run(
                [
                    "npm",
                    "exec",
                    "--",
                    "playwright",
                    "test",
                    "--config",
                    "playwright.deployment.config.ts",
                    "agent.spec.ts",
                    "--output",
                    str(directory / "results"),
                ],
                cwd=ROOT / "apps/web",
                env=os.environ
                | {
                    "ALAP_COMPOSE_BROWSER_STATE": str(directory / "browser.json"),
                    "PLAYWRIGHT_BROWSERS_PATH": str(ROOT / ".local-deploy/browsers"),
                },
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            (ROOT / "reports/d12d2-compose-agent.txt").write_text(
                result.stdout.replace(token, "[REDACTED]")
            )
            if result.returncode:
                # Safe worker logs contain run IDs/codes, never model bodies or credentials.
                print(
                    drill.output(
                        drill.compose + ["logs", "--tail", "30", "agent-drill", "offline-provider"]
                    )
                )
                return result.returncode
            for _ in range(30):
                records = evidence(runtime, state)
                if all(r["unpublished"] == 0 for r in records):
                    break
                time.sleep(1)
            for record in records:
                for table, expected in {
                    "runs": {"SUCCEEDED": 1},
                    "tasks": {"SUCCEEDED": 3},
                    "command_ledger": {"SUCCEEDED": 3},
                    "datasets": {"COMMITTED": 1},
                }.items():
                    assert record[table] == expected
                assert record["unpublished"] == 0
            (ROOT / "reports/d12d2-compose-evidence.json").write_text(
                json.dumps(
                    {
                        "completed_at": datetime.now(UTC).isoformat(),
                        "provider": "local TLS/SSE substitute; no live vendor calls",
                        "cases": records,
                        "images": {k: c["Image"] for k, c in deployed.items()},
                    },
                    indent=2,
                )
                + "\n"
            )
            return 0
        finally:
            drill.run(drill.compose + ["rm", "-f", "-s", "agent-drill", "offline-provider"])
            # Cancel interrupted fixture AgentRuns via the existing audited application path.
            execute(
                runtime,
                """from alap.adapters.postgres.api import PostgresAPIStore
from alap.adapters.postgres.settings import database_url
from alap.application.agent_runtime import AgentRuntime
store=PostgresAPIStore(database_url())
runtime=AgentRuntime(store,None,None,None,execution_skills={})
with store.connect() as db:
    pending=db.execute("SELECT id,actor_id FROM agent_runs WHERE experiment_id=ANY(%s) "
        "AND checkpoint->>'status' IN ('READY','RUNNING')",(EXPS,)).fetchall()
for row in pending:
    runtime.cancel(row['actor_id'],row['id'])
""".replace("EXPS", repr([c["experiment"] for c in state["cases"]])),
            )
            # Disable even partial seed configurations. Preserve immutable audit/business history.
            ids = [c["id"] for c in state["cases"]]
            code = """import psycopg
from alap.adapters.postgres.settings import database_url
with psycopg.connect(database_url()) as db:
    db.execute("UPDATE agent_registry SET state='DISABLED' WHERE kind='agent' "
               "AND ref=ANY(%s)", (REFS,))
    db.execute("UPDATE platform_configs SET enabled=FALSE,revision=revision+1 "
               "WHERE ref=ANY(%s) AND enabled", (REFS,))
    db.execute("UPDATE api_credentials SET enabled=FALSE,revision=revision+1 "
               "WHERE ref=ANY(%s) AND enabled", (IDS,))
""".replace("REFS", repr([i + "@1" for i in ids])).replace("IDS", repr(ids))
            guides = [c["guide"] + "@1" for c in state["cases"] if "guide" in c]
            if guides:
                code += (
                    "    db.execute(\"UPDATE agent_registry SET state='DISABLED' \""
                    " \"WHERE kind='skill' AND ref=ANY(%s)\", (" + repr(guides) + ",))\n"
                )
            if token:
                code += (
                    '    db.execute("UPDATE api_tokens SET revoked=TRUE WHERE token_hash=%s", ('
                    + repr(hashlib.sha256(token.encode()).hexdigest())
                    + ",))\n"
                )
            execute(runtime, code)
            # Only the empty, uniquely scoped test network is removed, never deployment volumes.
            networks = runtime.output([DOCKER, "network", "ls", "--format", "{{.Name}}"]).split()
            if runtime.project + "_offline-model" in networks:
                runtime.run(
                    [DOCKER, "network", "rm", runtime.project + "_offline-model"],
                    stdout=subprocess.DEVNULL,
                )


if __name__ == "__main__":
    with maintenance_lock(ROOT / ".local-deploy/operations.lock"):
        raise SystemExit(main())
