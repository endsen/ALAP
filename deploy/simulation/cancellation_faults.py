"""Deployed durable cancellation intent and independent worker acknowledgement."""

import json
import os
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime
from uuid import uuid4

from check_agent import execute
from manage import ROOT
from model_faults import wait
from operations import DOCKER


def cases(suffix):
    return [
        {
            "experiment": f"EXP-AGENT-{vendor}-{phase}-{suffix}",
            "id": f"drill-{vendor}-{phase}-{suffix}",
            "guide": f"guide-{vendor}-{phase}-{suffix}",
            "vendor": vendor,
            "phase": phase,
            "mode": "cancel_hold",
            "timeout_seconds": 90,
        }
        for vendor in ("openai", "deepseek")
        for phase in ("before", "inflight", "browser")
    ]


def run_cancellations(runtime, state, directory, deployed):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api(path, body=None, *, method=None, key=None):
        request = urllib.request.Request(
            "http://127.0.0.1:3000/api/v1" + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Authorization": "Bearer " + state["owner"],
                "Content-Type": "application/json",
                "Idempotency-Key": key or str(uuid4()),
            },
        )
        try:
            with opener.open(request, timeout=15) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    def get(path):
        status, body = api(path)
        assert status == 200
        return body

    worker = deployed["agent-drill"]["Id"]
    records = []
    for case in state["cases"]:
        before = case["phase"] == "before"
        if before:
            runtime.output([DOCKER, "stop", worker])
        exp = case["experiment"]
        status, run = api(
            "/agent-runs",
            {
                "experiment_id": exp,
                "definition_ref": case["id"] + "@1",
                "goal": "D12D3:cancel_hold\nRead the scoped snapshot.",
            },
        )
        assert status in {200, 201}
        path = "/agent-runs/" + run["id"]
        if before:
            assert get(path)["status"] == "READY"
        else:
            wait(lambda exp=exp: (directory / "control" / (exp + ".partial")).exists(), bool)
            assert get(path)["status"] == "RUNNING"
        key = str(uuid4())
        if case["phase"] == "browser":
            browser_state = {
                "owner": state["owner"],
                "experiment": exp,
                "run": run["id"],
                "release": str(directory / "control" / (exp + ".release")),
                "pending": str(directory / (exp + ".pending.json")),
            }
            browser_file = directory / "cancel-browser.json"
            browser_file.write_text(json.dumps(browser_state))
            browser_file.chmod(0o600)
            with (ROOT / f"reports/d12d3-cancel-deploy-{case['vendor']}-browser.txt").open(
                "w"
            ) as log:
                subprocess.run(
                    [
                        "npx",
                        "playwright",
                        "test",
                        "--config",
                        "playwright.deployment.config.ts",
                        "cancellation.spec.ts",
                    ],
                    cwd=ROOT / "apps/web",
                    env=os.environ | {"ALAP_COMPOSE_BROWSER_STATE": str(browser_file)},
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=100,
                    check=True,
                )
            response = json.loads((directory / (exp + ".pending.json")).read_text())
            status = 200
        else:
            status, response = api(path + "/cancel", method="POST", key=key)
        assert status == 200 and response["cancel_requested"] is True
        if before:
            assert response["status"] == "CANCELLED"
            assert api(path + "/cancel", method="POST", key=key) == (status, response)
            runtime.output([DOCKER, "start", worker])
        else:
            assert response["status"] == "RUNNING"
            if case["phase"] == "inflight":
                assert get(path)["status"] == "RUNNING"
                assert api(path + "/cancel", method="POST", key=key) == (status, response)
                (directory / "control" / (exp + ".release")).touch()
        final = wait(
            lambda path=path: get(path),
            lambda r: r["status"] in {"COMPLETED", "FAILED", "CANCELLED"},
        )
        expected = "CANCELLED"
        assert final["status"] == expected and final["result"] is None
        trace = get(path + "/trace")["items"]
        assert final["cancel_requested"] is True
        assert trace[-1]["event"] == {
            "type": "cancelled",
            "prior_stage": "model" if before else "inflight",
            "model_outcome_unknown": not before,
        }
        assert not any(t["event"]["type"] == "model_completed" for t in trace)
        # Terminal cancellation is a no-op; the confirmed state remains authoritative.
        terminal_status, terminal = api(path + "/cancel", method="POST")
        assert terminal_status == 200 and terminal == final
        assert get(path + "/trace")["items"] == trace
        record = json.loads(
            execute(
                runtime,
                """import json,psycopg
from alap.adapters.postgres.settings import database_url
with psycopg.connect(database_url()) as db:
 db.execute('SET TRANSACTION READ ONLY')
 cp=db.execute('SELECT checkpoint FROM agent_runs WHERE id=%s',(RUN,)).fetchone()[0]
 writes={t:db.execute('SELECT count(*) FROM '+t+' WHERE experiment_id=%s',(EXP,)).fetchone()[0]
         for t in ('plan_revisions','approvals','runs','tasks','command_ledger','datasets')}
 for t in ('agent_proposals','agent_tool_invocations'):
  writes[t]=db.execute('SELECT count(*) FROM '+t+' WHERE run_id=%s',(RUN,)).fetchone()[0]
 print(json.dumps({'status':cp['status'],'stage':cp['stage'],'iterations':cp['iterations'],
    'reserved_tokens':cp['reserved_tokens'],'writes':writes}))
""".replace("RUN", repr(run["id"])).replace("EXP", repr(exp)),
            )
        )
        assert record["status"] == expected and record["stage"] == "done"
        assert record["iterations"] == (0 if before else 1)
        assert (record["reserved_tokens"] == 0) if before else (record["reserved_tokens"] > 0)
        assert all(n == 0 for n in record["writes"].values())
        records.append(
            {
                "vendor": case["vendor"],
                "phase": case["phase"],
                "experiment": exp,
                "cancel_http_status": status,
                "cancel_requested": response["cancel_requested"],
                "evidence": record,
                "trace_events": [t["event"] for t in trace],
            }
        )
    for case, record in zip(state["cases"], records, strict=True):
        request_file = directory / "control" / (case["experiment"] + ".requests")
        calls = len(request_file.read_text().splitlines()) if request_file.exists() else 0
        assert calls == (0 if case["phase"] == "before" else 1)
        record["https_requests"] = calls
    (ROOT / "reports/d12d3-cancel-deploy-evidence.json").write_text(
        json.dumps(
            {
                "completed_at": datetime.now(UTC).isoformat(),
                "cases": records,
                "scope": (
                    "durable cancellation at safe boundary; actual HTTPS; no immediate socket abort"
                ),
                "images": {k: c["Image"] for k, c in deployed.items()},
            },
            indent=2,
        )
        + "\n"
    )
    print("PASS: six deployed cancellation cases including two actual browser flows")
    return 0
