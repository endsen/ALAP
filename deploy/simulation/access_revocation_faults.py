"""Real HTTPS submitter revocation in a dedicated deployed Agent process."""

import json
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
            "experiment": f"EXP-AGENT-{v}-access-{phase}-{suffix}",
            "id": f"drill-{v}-access-{phase}-{suffix}",
            "guide": f"guide-{v}-access-{phase}-{suffix}",
            "vendor": v,
            "phase": phase,
            "mode": "cancel_hold",
            "timeout_seconds": 90,
        }
        for v in ("openai", "deepseek")
        for phase in ("before", "membership", "scope")
    ]


def run_access_revocation(runtime, state, directory, deployed):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    actor = state["permission_actors"]["operator"]
    token = state["permission_tokens"]["operator"]

    def api(path, body=None, *, admin=False, method=None, expected=200, revision=None):
        headers = {
            "Authorization": "Bearer " + (state["owner"] if admin else token),
            "Content-Type": "application/json",
            "Idempotency-Key": str(uuid4()),
        }
        if revision is not None:
            headers["If-Match"] = f'"{revision}"'
        request = urllib.request.Request(
            "http://127.0.0.1:3000/api/v1" + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers=headers,
        )
        try:
            with opener.open(request, timeout=15) as response:
                status, result = response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            status, result = exc.code, json.load(exc)
        assert status == expected, (path, status, result.get("error", {}).get("code"))
        return result

    def evidence(identity, exp):
        return json.loads(
            execute(
                runtime,
                """import json,psycopg
from alap.adapters.postgres.settings import database_url
with psycopg.connect(database_url()) as db:
 db.execute('SET TRANSACTION READ ONLY')
 r=db.execute('SELECT actor_id,checkpoint,revision FROM agent_runs WHERE id=%s',(RUN,)).fetchone()
 writes={t:db.execute('SELECT count(*) FROM '+t+' WHERE experiment_id=%s',
   (EXP,)).fetchone()[0] for t in
   ('plan_revisions','approvals','runs','tasks','command_ledger','datasets')}
 for t in ('agent_tool_invocations','agent_proposals'):
  writes[t]=db.execute('SELECT count(*) FROM '+t+' WHERE run_id=%s',(RUN,)).fetchone()[0]
 events=[e[0] for e in db.execute('SELECT event FROM agent_trace WHERE run_id=%s ORDER BY seq',
   (RUN,))]
 print(json.dumps({'actor':r[0],'checkpoint':r[1],'revision':r[2],
   'events':events,'writes':writes}))
""".replace("RUN", repr(identity)).replace("EXP", repr(exp)),
            )
        )

    worker = deployed["agent-drill"]["Id"]
    records = []
    assert api("/me")["role"] != "admin"
    for case in state["cases"]:
        exp, phase = case["experiment"], case["phase"]
        prefix = "/experiments/" + exp
        scope = {
            "resources": ["sim-temp", "sim-magnet", "sim-smu"],
            "risk_levels": ["operator_review"],
        }

        def membership(revoked=False, limited=False, *, prefix=prefix, scope=scope):
            revision = api(prefix, admin=True)["revision"]
            return api(
                prefix + "/members/" + actor,
                {
                    "role": "operator",
                    "scope": scope if not limited else {"resources": [], "risk_levels": []},
                    "revoked": revoked,
                },
                admin=True,
                method="PUT",
                revision=revision,
            )

        membership()
        before = phase == "before"
        if before:
            runtime.output([DOCKER, "stop", worker])
        run = api(
            "/agent-runs",
            {
                "experiment_id": exp,
                "definition_ref": case["id"] + "@1",
                "goal": "D12D3:cancel_hold\nRead scoped state.",
            },
            expected=201,
        )
        path = "/agent-runs/" + run["id"]
        if before:
            assert api(path)["status"] == "READY"
        else:
            wait(lambda exp=exp: (directory / "control" / (exp + ".partial")).exists(), bool)
            assert api(path)["status"] == "RUNNING"
        reserved = evidence(run["id"], exp)
        assert reserved["actor"] == actor
        assert reserved["checkpoint"]["stage"] == ("model" if before else "inflight")
        membership(revoked=phase != "scope", limited=phase == "scope")
        for suffix in ("", "/trace", "/proposals"):
            assert api(path + suffix, expected=403)["error"]["code"] == "FORBIDDEN"
        api(path + "/cancel", method="POST", expected=403)
        if before:
            runtime.output([DOCKER, "start", worker])
        else:
            # Release actual SSE only after membership mutation and access denial committed.
            (directory / "control" / (exp + ".release")).touch()
        closed = wait(
            lambda identity=run["id"], exp=exp: evidence(identity, exp),
            lambda r: r["checkpoint"]["status"] == "FAILED",
        )
        cp = closed["checkpoint"]
        assert cp == dict(
            reserved["checkpoint"],
            status="FAILED",
            stage="done",
            error="ACCESS_REVOKED",
            result=None,
        )
        assert closed["revision"] == reserved["revision"] + 1
        assert closed["events"] == reserved["events"] + [
            {
                "type": "blocked",
                "code": "ACCESS_REVOKED",
                "prior_stage": "model" if before else "inflight",
                "model_outcome_unknown": not before,
            }
        ]
        assert all(n == 0 for n in closed["writes"].values())
        api(path, expected=403)
        membership()
        assert api(path)["status"] == "FAILED"
        trace = api(path + "/trace")
        assert api(path + "/proposals")["items"] == []
        runtime.output([DOCKER, "restart", worker])
        started = json.loads(runtime.output([DOCKER, "inspect", worker]))[0]["State"]["StartedAt"]
        wait(
            lambda started=started: runtime.output([DOCKER, "logs", "--since", started, worker]),
            lambda logs: '"runs": []' in logs,
        )
        assert evidence(run["id"], exp) == closed
        assert api(path + "/trace") == trace
        log = directory / "control" / (exp + ".requests")
        count = len(log.read_text().splitlines()) if log.exists() else 0
        assert count == (0 if before else 1)
        membership(revoked=True)
        records.append(
            {
                "vendor": case["vendor"],
                "phase": phase,
                "experiment": exp,
                "status": cp["status"],
                "error": cp["error"],
                "reserved_tokens": cp["reserved_tokens"],
                "https_requests": count,
                "execution_writes": closed["writes"],
                "blocked_event": closed["events"][-1],
                "regrant_restart_no_change": True,
            }
        )
    (ROOT / "reports/d12d3-access-deploy-evidence.json").write_text(
        json.dumps(
            {
                "completed_at": datetime.now(UTC).isoformat(),
                "cases": records,
                "images": {k: c["Image"] for k, c in deployed.items()},
                "scope": (
                    "non-admin operator; API membership revoke/scope reduction; local HTTPS SSE"
                ),
            },
            indent=2,
        )
        + "\n"
    )
    print("PASS: six deployed submitter revocation cases; no output publication or replay")
    return 0
