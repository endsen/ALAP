"""SIGKILL a deployed resident worker during real HTTPS; recovery never replays."""

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
            "mode": "cancel_hold",
            "timeout_seconds": 90,
        }
        for vendor in ("openai", "deepseek")
        for phase in ("cancel-crash", "inflight-crash")
    ]


def run_crashes(runtime, state, directory, deployed):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api(path, body=None, *, method=None):
        request = urllib.request.Request(
            "http://127.0.0.1:3000/api/v1" + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Authorization": "Bearer " + state["owner"],
                "Content-Type": "application/json",
                "Idempotency-Key": str(uuid4()),
            },
        )
        with opener.open(request, timeout=15) as response:
            return json.load(response)

    worker = deployed["agent-drill"]["Id"]

    def inspect():
        return json.loads(runtime.output([DOCKER, "inspect", worker]))[0]["State"]

    records = []
    for case in state["cases"]:
        exp = case["experiment"]
        cancelled = case["phase"] == "cancel-crash"
        run = api(
            "/agent-runs",
            {
                "experiment_id": exp,
                "definition_ref": case["id"] + "@1",
                "goal": "D12D3:cancel_hold\nRead the scoped snapshot.",
            },
        )
        path = "/agent-runs/" + run["id"]
        wait(lambda exp=exp: (directory / "control" / (exp + ".partial")).exists(), bool)
        if cancelled:
            pending = api(path + "/cancel", method="POST")
            assert pending["status"] == "RUNNING" and pending["cancel_requested"] is True
        before = api(path)
        assert before["status"] == "RUNNING" and before["cancel_requested"] == cancelled
        trace_before = api(path + "/trace")["items"]
        assert trace_before[-1]["event"]["type"] == "model_reserved"
        runtime.output([DOCKER, "kill", "--signal", "KILL", worker])
        stopped = wait(inspect, lambda s: not s["Running"])
        assert stopped["ExitCode"] == 137 and not stopped["OOMKilled"]
        # No parent/manual advance: killing the process alone must not fabricate a terminal.
        assert api(path) == before
        assert api(path + "/trace")["items"] == trace_before
        (directory / "control" / (exp + ".release")).touch()
        runtime.output([DOCKER, "start", worker])
        final = wait(
            lambda path=path: api(path),
            lambda r: r["status"] in {"FAILED", "COMPLETED", "CANCELLED"},
        )
        assert final["status"] == ("CANCELLED" if cancelled else "FAILED")
        assert final["result"] is None and final["cancel_requested"] == cancelled
        trace = api(path + "/trace")["items"]
        assert trace[-1]["event"] == (
            {"type": "cancelled", "prior_stage": "inflight", "model_outcome_unknown": True}
            if cancelled
            else {"type": "blocked", "code": "MODEL_INTERRUPTED"}
        )
        assert len(trace) == len(trace_before) + 1
        assert not any(t["event"]["type"] == "model_completed" for t in trace)
        record = json.loads(
            execute(
                runtime,
                """import json,psycopg
from alap.adapters.postgres.settings import database_url
with psycopg.connect(database_url()) as db:
 db.execute('SET TRANSACTION READ ONLY')
 row=db.execute('SELECT checkpoint,cancel_requested_at FROM agent_runs WHERE id=%s',
                (RUN,)).fetchone()
 cp=row[0]
 writes={t:db.execute('SELECT count(*) FROM '+t+' WHERE experiment_id=%s',(EXP,)).fetchone()[0]
         for t in ('plan_revisions','approvals','runs','tasks','command_ledger','datasets')}
 for t in ('agent_proposals','agent_tool_invocations'):
  writes[t]=db.execute('SELECT count(*) FROM '+t+' WHERE run_id=%s',(RUN,)).fetchone()[0]
 print(json.dumps({'status':cp['status'],'stage':cp['stage'],'iterations':cp['iterations'],
    'reserved_tokens':cp['reserved_tokens'],'writes':writes,'cancel_requested':row[1] is not None}))
""".replace("RUN", repr(run["id"])).replace("EXP", repr(exp)),
            )
        )
        assert record["status"] == final["status"]
        assert record["stage"] == "done" and record["iterations"] == 1
        assert record["reserved_tokens"] > 0 and record["cancel_requested"] == cancelled
        assert all(n == 0 for n in record["writes"].values())
        # A second process start must not repeat closure, model I/O or tool publication.
        runtime.output([DOCKER, "restart", worker])
        restarted = inspect()
        assert restarted["Running"]
        wait(
            lambda started=restarted["StartedAt"]: runtime.output(
                [DOCKER, "logs", "--since", started, worker]
            ),
            lambda logs: any(
                line.startswith('{"event": "agent_tick"') and '"runs": []' in line
                for line in logs.splitlines()
            ),
        )
        assert api(path) == final and api(path + "/trace")["items"] == trace
        records.append(
            {
                "vendor": case["vendor"],
                "phase": case["phase"],
                "experiment": exp,
                "killed_exit_code": stopped["ExitCode"],
                "oom_killed": stopped["OOMKilled"],
                "before_status": before["status"],
                "evidence": record,
                "terminal_event": trace[-1]["event"],
                "second_restart_no_change": True,
            }
        )
    for case, record in zip(state["cases"], records, strict=True):
        calls = (
            (directory / "control" / (case["experiment"] + ".requests")).read_text().splitlines()
        )
        assert len(calls) == 1
        record["https_requests"] = len(calls)
    (ROOT / "reports/d12d3-agent-crash-evidence.json").write_text(
        json.dumps(
            {
                "completed_at": datetime.now(UTC).isoformat(),
                "cases": records,
                "images": {k: c["Image"] for k, c in deployed.items()},
                "scope": "isolated resident worker SIGKILL during HTTPS; no online models/devices",
            },
            indent=2,
        )
        + "\n"
    )
    print("PASS: four deployed SIGKILL/restart cases; cancellation durable, no model replay")
    return 0
