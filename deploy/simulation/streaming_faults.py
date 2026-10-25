"""Malformed usage and actual stalled HTTPS streams on an independent resident worker."""

import json
import urllib.request
from datetime import UTC, datetime
from uuid import uuid4

from check_agent import execute
from manage import ROOT
from model_faults import wait

MODES = ("usage_negative", "usage_boolean", "usage_inconsistent", "read_timeout")


def cases(suffix, *, retries=False):
    return [
        {
            "experiment": f"EXP-AGENT-{vendor}-{mode.replace('_', '-')}-{suffix}",
            "id": f"drill-{vendor}-{mode}-{suffix}",
            "vendor": vendor,
            "mode": mode,
            "guide": f"guide-{vendor}-{mode}-{suffix}",
            "timeout_seconds": 2,
            "max_attempts": 3 if retries else 1,
            "expected_requests": 3 if retries and mode == "rate_limit" else 1,
        }
        for vendor in ("openai", "deepseek")
        for mode in (("rate_limit", "read_timeout") if retries else MODES)
    ]


def run_streaming(runtime, state, directory, deployed, *, retries=False):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api(path, body=None):
        request = urllib.request.Request(
            "http://127.0.0.1:3000/api/v1" + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Authorization": "Bearer " + state["owner"],
                "Content-Type": "application/json",
                "Idempotency-Key": str(uuid4()),
            },
        )
        with opener.open(request, timeout=15) as response:
            return json.load(response)

    records = []
    for case in state["cases"]:
        exp = case["experiment"]
        run = api(
            "/agent-runs",
            {
                "experiment_id": exp,
                "definition_ref": case["id"] + "@1",
                "goal": "D12D3:" + case["mode"] + "\nRead the scoped snapshot.",
            },
        )
        path = "/agent-runs/" + run["id"]
        final = wait(
            lambda path=path: api(path),
            lambda r: r["status"] in {"FAILED", "COMPLETED", "CANCELLED"},
        )
        assert final["status"] == "FAILED" and final["result"] is None
        trace = api(path + "/trace")["items"]
        assert trace[-1]["event"] == {"type": "blocked", "code": "MODEL_FAILURE"}
        assert not any(t["event"]["type"] == "model_completed" for t in trace)
        expected_requests = case["expected_requests"]
        assert (
            len((directory / "control" / (exp + ".requests")).read_text().splitlines())
            == expected_requests
        )
        if case["mode"] == "read_timeout":
            assert (directory / "control" / (exp + ".partial")).exists()
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
        assert record["status"] == "FAILED" and record["stage"] == "done"
        assert record["iterations"] == 1 and record["reserved_tokens"] > 0
        assert all(n == 0 for n in record["writes"].values())
        usage = api("/experiments/" + exp + "/usage")
        # Failure never fabricates a successful completion or publishes invalid usage.
        assert usage["unknown_usage_completions"] == 0
        records.append(
            {
                "vendor": case["vendor"],
                "mode": case["mode"],
                "experiment": exp,
                "https_requests": expected_requests,
                "max_attempts": case["max_attempts"],
                "evidence": record,
                "usage": usage,
            }
        )
    for case in state["cases"]:
        assert (
            len(
                (directory / "control" / (case["experiment"] + ".requests"))
                .read_text()
                .splitlines()
            )
            == case["expected_requests"]
        )
    name = "retry" if retries else "streaming"
    (ROOT / f"reports/d12d3-{name}-https-evidence.json").write_text(
        json.dumps(
            {
                "completed_at": datetime.now(UTC).isoformat(),
                "cases": records,
                "scope": (
                    "isolated HTTPS substitute; timeout profile 2s; "
                    f"max_attempts {3 if retries else 1}; no online calls"
                ),
                "images": {k: c["Image"] for k, c in deployed.items()},
            },
            indent=2,
        )
        + "\n"
    )
    print(f"PASS: {len(records)} deployed {name} cases; no tool/device writes")
    return 0
