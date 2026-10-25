"""Restart a deployed worker at committed pending-tool and tool-result boundaries."""

import json
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
            "mode": "tool_recovery",
        }
        for vendor in ("openai", "deepseek")
        for phase in ("pending-tools", "committed-read")
    ]


def run_tool_recovery(runtime, state, directory, deployed):
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

    def evidence(identity, exp):
        return json.loads(
            execute(
                runtime,
                """import json,psycopg
from alap.adapters.postgres.settings import database_url
with psycopg.connect(database_url()) as db:
 db.execute('SET TRANSACTION READ ONLY')
 cp=db.execute('SELECT checkpoint FROM agent_runs WHERE id=%s',(RUN,)).fetchone()[0]
 calls=db.execute('SELECT call_id,tool_ref,input_hash FROM agent_tool_invocations '
                  'WHERE run_id=%s ORDER BY call_id',(RUN,)).fetchall()
 proposals=db.execute('SELECT id,content_hash,state FROM agent_proposals '
                      'WHERE run_id=%s ORDER BY id',(RUN,)).fetchall()
 writes={t:db.execute('SELECT count(*) FROM '+t+' WHERE experiment_id=%s',(EXP,)).fetchone()[0]
         for t in ('plan_revisions','approvals','runs','tasks','command_ledger','datasets')}
 print(json.dumps({'status':cp['status'],'stage':cp['stage'],'iterations':cp['iterations'],
   'tool_calls':cp['tool_calls'],'history_count':len(cp['history']),
   'pending_ids':[c['id'] for c in cp['pending']], 'reserved_tokens':cp['reserved_tokens'],
   'invocations':calls,'proposals':proposals,'writes':writes}))
""".replace("RUN", repr(identity)).replace("EXP", repr(exp)),
            )
        )

    worker = deployed["agent-drill"]["Id"]
    records = []
    for case in state["cases"]:
        exp = case["experiment"]
        run = api(
            "/agent-runs",
            {
                "experiment_id": exp,
                "definition_ref": case["id"] + "@1",
                "goal": "D12D3:tool_recovery\nPropose a scoped IV plan.",
            },
        )
        path = "/agent-runs/" + run["id"]
        pending = case["phase"] == "pending-tools"
        target = "tools" if pending else "model"
        boundary = wait(
            lambda identity=run["id"], exp=exp: evidence(identity, exp),
            lambda r, target=target: r["stage"] == target and r["iterations"] == 1,
        )
        assert boundary["status"] == "RUNNING"
        assert boundary["pending_ids"] == (["offline-read"] if pending else [])
        assert boundary["tool_calls"] == boundary["history_count"] == (0 if pending else 1)
        assert len(boundary["invocations"]) == (0 if pending else 1)
        assert not boundary["proposals"]
        runtime.output([DOCKER, "kill", "--signal", "KILL", worker])
        stopped = json.loads(runtime.output([DOCKER, "inspect", worker]))[0]["State"]
        assert not stopped["Running"] and stopped["ExitCode"] == 137 and not stopped["OOMKilled"]
        # If the next tick won the race, fail rather than pretend we stopped at this boundary.
        assert evidence(run["id"], exp) == boundary
        trace_before = api(path + "/trace")["items"]
        assert trace_before[-1]["event"]["type"] == (
            "model_completed" if pending else "tools_completed"
        )
        assert len((directory / "control" / (exp + ".requests")).read_text().splitlines()) == 1
        runtime.output([DOCKER, "start", worker])
        final = wait(
            lambda path=path: api(path),
            lambda r: r["status"] in {"COMPLETED", "FAILED", "CANCELLED"},
        )
        assert final["status"] == "COMPLETED"
        after = evidence(run["id"], exp)
        assert after["stage"] == "done" and after["iterations"] == 2
        assert after["tool_calls"] == after["history_count"] == 2
        assert after["pending_ids"] == [] and after["reserved_tokens"] == 128000
        assert [r[0] for r in after["invocations"]] == ["offline-propose", "offline-read"]
        assert len(after["proposals"]) == 1 and after["proposals"][0][2] == "PROPOSED"
        assert final["result"] == {"proposal_ids": [after["proposals"][0][0]]}
        assert all(n == 0 for n in after["writes"].values())
        if not pending:
            assert after["invocations"][1] == boundary["invocations"][0]
        trace = api(path + "/trace")["items"]
        assert trace[: len(trace_before)] == trace_before
        assert sum(t["event"]["type"] == "model_completed" for t in trace) == 2
        assert sum(t["event"]["type"] == "tools_completed" for t in trace) == 2
        runtime.output([DOCKER, "restart", worker])
        started = json.loads(runtime.output([DOCKER, "inspect", worker]))[0]["State"]["StartedAt"]
        wait(
            lambda started=started: runtime.output([DOCKER, "logs", "--since", started, worker]),
            lambda logs: '"runs": []' in logs,
        )
        assert evidence(run["id"], exp) == after
        assert api(path) == final and api(path + "/trace")["items"] == trace
        records.append(
            {
                "vendor": case["vendor"],
                "phase": case["phase"],
                "experiment": exp,
                "killed_exit_code": stopped["ExitCode"],
                "boundary": boundary,
                "final": after,
                "second_restart_no_change": True,
            }
        )
    for case, record in zip(state["cases"], records, strict=True):
        calls = (
            (directory / "control" / (case["experiment"] + ".requests")).read_text().splitlines()
        )
        assert len(calls) == 2
        record["https_requests"] = len(calls)
    (ROOT / "reports/d12d3-tool-recovery-evidence.json").write_text(
        json.dumps(
            {
                "completed_at": datetime.now(UTC).isoformat(),
                "cases": records,
                "images": {k: c["Image"] for k, c in deployed.items()},
                "scope": "committed boundaries, worker poll_s=5; actual HTTPS, no manual advance",
            },
            indent=2,
        )
        + "\n"
    )
    print("PASS: four deployed tool-boundary restarts; one read and one unapproved proposal each")
    return 0
