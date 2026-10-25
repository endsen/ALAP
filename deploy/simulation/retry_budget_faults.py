"""Real HTTPS attempts, runtime budgets and stable usage aggregation."""

import json
import urllib.request
from datetime import UTC, datetime
from uuid import uuid4

from check_agent import execute
from manage import ROOT
from model_faults import wait
from operations import DOCKER

BUDGETS = {"retry_success": 128000, "retry_budget": 48000, "budget_preflight": 4096}


def cases(suffix):
    return [
        {
            "experiment": f"EXP-AGENT-{vendor}-{mode.replace('_', '-')}-{suffix}",
            "id": f"drill-{vendor}-{mode}-{suffix}",
            "guide": f"guide-{vendor}-{mode}-{suffix}",
            "vendor": vendor,
            "mode": mode,
            "token_budget": budget,
            "timeout_seconds": 2,
            "max_attempts": 3,
        }
        for vendor in ("openai", "deepseek")
        for mode, budget in BUDGETS.items()
    ]


def run_budgets(runtime, state, directory, deployed):
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
        exp, mode = case["experiment"], case["mode"]
        success, preflight = mode == "retry_success", mode == "budget_preflight"
        goal = "D12D3:" + mode + "\nRead only."
        if mode == "retry_budget":
            goal += "\n" + "x" * 15000
        run = api(
            "/agent-runs", {"experiment_id": exp, "definition_ref": case["id"] + "@1", "goal": goal}
        )
        path = "/agent-runs/" + run["id"]
        final = wait(
            lambda path=path: api(path),
            lambda r: r["status"] in {"FAILED", "COMPLETED", "CANCELLED"},
        )
        assert final["status"] == ("COMPLETED" if success else "FAILED")
        assert final["result"] == ("Read-only retry result." if success else None)
        trace = api(path + "/trace")["items"]
        completed = [t["event"] for t in trace if t["event"]["type"] == "model_completed"]
        request_file = directory / "control" / (exp + ".requests")
        calls = len(request_file.read_text().splitlines()) if request_file.exists() else 0
        reservations = (
            []
            if preflight
            else [
                int(v)
                for v in (directory / "control" / (exp + ".reservations")).read_text().splitlines()
            ]
        )
        if success:
            assert calls == 2 and len(completed) == 1
            attempts = completed[0]["attempts"]
            assert len(attempts) == 2 and len({a["id"] for a in attempts}) == 2
            assert len(set(reservations)) == 1
        else:
            assert not completed
            assert trace[-1]["event"] == {
                "type": "blocked",
                "code": "TOKEN_BUDGET" if preflight else "MODEL_FAILURE",
            }
            if preflight:
                assert calls == 0
            else:
                assert 1 <= calls < case["max_attempts"]
                assert len(set(reservations)) == 1
                amount = reservations[0]
                assert calls * amount <= case["token_budget"] < (calls + 1) * amount
        usage_path = "/experiments/" + exp + "/usage"
        usage = api(usage_path)
        assert all(api(usage_path) == usage for _ in range(3))
        assert usage["agent_runs"] == 1
        assert usage["logical_requests"] == (0 if preflight else 1)
        assert usage["model_completions"] == (1 if success else 0)
        assert usage["recorded_attempts"] == (2 if success else 0)
        assert usage["unresolved_requests"] == (1 if mode == "retry_budget" else 0)
        assert usage["estimated_cost"] is None
        assert usage["reported_tokens"] == (
            {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
            if success
            else dict.fromkeys(("prompt_tokens", "completion_tokens", "total_tokens"))
        )
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
        assert record["status"] == final["status"] and record["stage"] == "done"
        assert record["iterations"] == (0 if preflight else 1)
        assert record["reserved_tokens"] == (0 if preflight else min(64000, case["token_budget"]))
        assert all(n == 0 for n in record["writes"].values())
        records.append(
            {
                "vendor": case["vendor"],
                "mode": mode,
                "experiment": exp,
                "run": run["id"],
                "https_requests": calls,
                "attempt_reservations": reservations,
                "runtime_budget": case["token_budget"],
                "usage": usage,
                "evidence": record,
                "trace": trace,
            }
        )
    worker = deployed["agent-drill"]["Id"]
    runtime.output([DOCKER, "restart", worker])
    started = json.loads(runtime.output([DOCKER, "inspect", worker]))[0]["State"]["StartedAt"]
    wait(
        lambda: runtime.output([DOCKER, "logs", "--since", started, worker]),
        lambda logs: '"runs": []' in logs,
    )
    for record in records:
        exp = record["experiment"]
        assert api("/experiments/" + exp + "/usage") == record["usage"]
        assert api("/agent-runs/" + record["run"] + "/trace")["items"] == record.pop("trace")
        request_file = directory / "control" / (exp + ".requests")
        calls = len(request_file.read_text().splitlines()) if request_file.exists() else 0
        assert calls == record["https_requests"]
    (ROOT / "reports/d12d3-retry-budget-evidence.json").write_text(
        json.dumps(
            {
                "completed_at": datetime.now(UTC).isoformat(),
                "cases": records,
                "images": {k: c["Image"] for k, c in deployed.items()},
                "scope": "HTTPS substitute; cumulative reservation bounds, not provider billing",
            },
            indent=2,
        )
        + "\n"
    )
    print("PASS: six deployed retry success/budget cases; usage stable across reads/restart")
    return 0
