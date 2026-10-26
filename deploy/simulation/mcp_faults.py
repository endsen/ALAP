"""Deployed MCP control and revoke-before-dispatch, without weakening endpoint policy."""

import json
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime
from uuid import uuid4

from check_agent import execute
from manage import ROOT
from model_faults import wait
from operations import DOCKER


def cases(suffix, *, advanced=False, cache=False):
    return [
        {
            "experiment": f"EXP-AGENT-{v}-mcp-{phase}-{suffix}",
            "id": f"drill-{v}-mcp-{phase}-{suffix}",
            "guide": f"guide-{v}-mcp-{phase}-{suffix}",
            "vendor": v,
            "phase": phase,
            "mode": "mcp_revoke"
            if phase == "drift"
            else "mcp_control"
            if phase in {"inflight", "cache", "cache-revoke"}
            else "mcp_" + phase,
            "timeout_seconds": 90,
            "extra_versions": [2],
        }
        for v in ("openai", "deepseek")
        for phase in (
            ("cache", "cache-revoke")
            if cache
            else ("drift", "inflight")
            if advanced
            else ("control", "revoke")
        )
    ]


def run_mcp(runtime, state, directory, deployed, *, advanced=False, cache=False):
    worker = deployed["agent-drill"]["Id"]
    # Discovery runs via real application/transport inside the worker network namespace.
    # It is maintenance setup, not evidence of HTTP API discovery.
    seed = """import json,os
from pathlib import Path
from alap.adapters.agents.bootstrap import build_agent
from alap.adapters.postgres.settings import database_url
from alap.adapters.mcp.http import MCPConnection
from alap.contracts import ContractCatalog
settings=json.loads(Path('/config/agent.json').read_text())
store,_,_,_,resources,_=build_agent(database_url(),
 Path(os.environ['ALAP_MASTER_KEY_FILE']).read_bytes().strip(),ContractCatalog(Path('/app/contracts')),
 settings['execution_skills'],None)
result={}
for case in CASES:
 ref=resources.register_connection(MCPConnection(case['id'],1,'http://127.0.0.1:8877/mcp',
   '127.0.0.1',allow_loopback=True,timeout=TIMEOUT))
 identity=resources.discover(ref)[0]
 with store.connect() as db:
  assert db.execute('SELECT count(*) FROM mcp_grants WHERE tool_id=%s',
    (identity,)).fetchone()['count']==0
 result[case['id']]=identity
print(json.dumps(result))
""".replace("CASES", repr(state["cases"])).replace("TIMEOUT", "60" if advanced or cache else "15")
    identities = json.loads(
        subprocess.check_output(
            [
                DOCKER,
                "run",
                "--rm",
                "-i",
                "--network",
                "container:" + worker,
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "-e",
                "ALAP_DATABASE_URL_FILE=/run/secrets/database.dsn",
                "-e",
                "ALAP_MASTER_KEY_FILE=/run/secrets/master.key",
                "-v",
                str(runtime.directory / "deployment/components/api.dsn")
                + ":/run/secrets/database.dsn:ro",
                "-v",
                str(runtime.directory / "master.key") + ":/run/secrets/master.key:ro",
                "-v",
                str(runtime.directory / "ca.crt") + ":/config/ca.crt:ro",
                "-v",
                str(directory / "agent.json") + ":/config/agent.json:ro",
                deployed["agent-drill"]["Image"],
                "python",
                "-",
            ],
            env=runtime.env,
            input=seed.encode(),
        )
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api(path, body=None, *, method=None, expected=200):
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
 cp=db.execute('SELECT checkpoint FROM agent_runs WHERE id=%s',(RUN,)).fetchone()[0]
 calls=db.execute('SELECT state,result FROM mcp_calls WHERE run_id=%s',(RUN,)).fetchall()
 inv=db.execute('SELECT count(*) FROM agent_tool_invocations WHERE run_id=%s',(RUN,)).fetchone()[0]
 writes={t:db.execute('SELECT count(*) FROM '+t+' WHERE experiment_id=%s',(EXP,)).fetchone()[0]
   for t in ('plan_revisions','approvals','runs','tasks','command_ledger','datasets')}
 writes['proposals']=db.execute('SELECT count(*) FROM agent_proposals WHERE run_id=%s',
   (RUN,)).fetchone()[0]
 print(json.dumps({'status':cp['status'],'error':cp.get('error'), 'history':cp['history'],
   'tool_calls':cp['tool_calls'],'calls':calls,'invocations':inv,'writes':writes}))
""".replace("RUN", repr(identity)).replace("EXP", repr(exp)),
            )
        )

    records, terminals = [], []
    for case in state["cases"]:
        exp, ident = case["experiment"], case["id"]
        tool_id = identities[ident]
        grant = {
            "actor_id": "admin",
            "experiment_id": exp,
            "resources": ["sim-temp", "sim-magnet", "sim-smu"],
        }
        approved = api("/mcp/tools/" + tool_id + "/grant", grant)
        definition = api("/agents/" + ident + "@1")["document"]
        definition["manifest"]["version"] = 2
        definition["manifest"]["allowed_tools"].append(approved["ref"])
        api("/agents", definition, expected=201)
        api("/agents/" + ident + "@2/publish", method="POST")
        if case["phase"] in {"inflight", "cache", "cache-revoke"}:
            (directory / "control" / (exp + ".mcp-hold")).touch()
        run = api(
            "/agent-runs",
            {
                "experiment_id": exp,
                "definition_ref": ident + "@2",
                "goal": "D12D3:" + case["mode"] + "\nRead reviewed MCP data.",
            },
            expected=201,
        )
        path = "/agent-runs/" + run["id"]
        phase = case["phase"]
        revoked = phase not in {"control", "cache"}
        recovery = None
        if cache:
            from mcp_cache import interrupt_success

            recovery = interrupt_success(
                runtime,
                directory,
                deployed,
                run["id"],
                exp,
                (
                    lambda tool_id=tool_id, grant=grant: api(
                        "/mcp/tools/" + tool_id + "/revoke", grant
                    )
                )
                if revoked
                else None,
            )
        elif phase == "inflight":
            wait(lambda exp=exp: (directory / "control" / (exp + ".mcp-started")).exists(), bool)
            assert evidence(run["id"], exp)["calls"] == [["INFLIGHT", None]]
            api("/mcp/tools/" + tool_id + "/revoke", grant)
            (directory / "control" / (exp + ".mcp-release")).touch()
        elif revoked:
            wait(lambda exp=exp: (directory / "control" / (exp + ".partial")).exists(), bool)
            assert api(path)["status"] == "RUNNING"
            if phase == "drift":
                (directory / "control" / "mcp-drift").touch()
            else:
                api("/mcp/tools/" + tool_id + "/revoke", grant)
            (directory / "control" / (exp + ".release")).touch()
        final = wait(
            lambda path=path: api(path),
            lambda r: r["status"] in {"COMPLETED", "FAILED", "CANCELLED"},
        )
        assert final["status"] == ("FAILED" if revoked else "COMPLETED")
        ev = evidence(run["id"], exp)
        assert all(n == 0 for n in ev["writes"].values())
        assert ev["invocations"] == ev["tool_calls"] == (0 if revoked else 1)
        assert ev["calls"] == (
            [["UNKNOWN", None]]
            if phase == "inflight"
            else [["SUCCEEDED", {"value": 3}]]
            if cache
            else []
            if revoked
            else [["SUCCEEDED", {"value": 3}]]
        )
        if phase == "drift":
            review = json.loads(
                execute(
                    runtime,
                    """import json,psycopg
from alap.adapters.postgres.settings import database_url
with psycopg.connect(database_url()) as db:
 db.execute('SET TRANSACTION READ ONLY')
 tools=db.execute('SELECT id,current,spec_hash FROM mcp_tools WHERE connection_ref=%s',
   (REF,)).fetchall()
 old=next(t for t in tools if t[0]==TOOL)
 new=next(t for t in tools if t[0]!=TOOL)
 assert len(tools)==2 and not old[1] and new[1] and old[2]!=new[2]
 assert db.execute('SELECT revoked FROM mcp_grants WHERE tool_id=%s',(TOOL,)).fetchone()[0]
 assert db.execute('SELECT count(*) FROM mcp_grants WHERE tool_id=%s',(new[0],)).fetchone()[0]==0
 print(json.dumps({'old_current':old[1],'new_current':new[1],'hash_changed':True,
                  'old_grant_revoked':True,'new_grants':0}))
""".replace("REF", repr(ident + "@1")).replace("TOOL", repr(tool_id)),
                )
            )
            (directory / "control" / "mcp-drift").unlink()
        elif phase == "inflight":
            # Restoring a grant after terminal closure must not replay an UNKNOWN call.
            api("/mcp/tools/" + tool_id + "/grant", grant)
        if revoked:
            assert ev["error"] == "MCP_REVOKED" and ev["history"] == []
        else:
            assert final["result"] == "Read-only retry result."
        if cache:
            from mcp_cache import cached_state

            recovered = cached_state(runtime, run["id"])
            assert recovered["calls"] == recovery["boundary"]["calls"]
            assert recovered["checkpoint"]["iterations"] == (1 if revoked else 2)
            assert recovered["checkpoint"]["reserved_tokens"] == (64000 if revoked else 128000)
            assert len(ev["history"]) == (0 if revoked else 1)
            recovery["cache_identity_and_result_preserved"] = True
        trace = api(path + "/trace")
        terminals.append((path, final, trace, run["id"], exp, ev))
        records.append(
            {
                "vendor": case["vendor"],
                "phase": case["phase"],
                "experiment": exp,
                "evidence": ev,
                "discovery_grants": 0,
                **({"recovery": recovery} if cache else {}),
                **({"review": review} if phase == "drift" else {}),
                **({"grant_restored_after_failure": True} if phase == "inflight" else {}),
            }
        )
    runtime.output([DOCKER, "restart", worker])
    started = json.loads(runtime.output([DOCKER, "inspect", worker]))[0]["State"]["StartedAt"]
    wait(
        lambda: runtime.output([DOCKER, "logs", "--since", started, worker]),
        lambda logs: '"runs": []' in logs,
    )
    for record, (path, final, trace, identity, exp, ev) in zip(records, terminals, strict=True):
        assert api(path) == final and api(path + "/trace") == trace
        assert evidence(identity, exp) == ev
        revoked = record["phase"] not in {"control", "cache"}
        calls_file = directory / "control" / (exp + ".mcp-calls")
        remote = (
            [json.loads(line) for line in calls_file.read_text().splitlines()]
            if calls_file.exists()
            else []
        )
        assert len(remote) == (
            1 if record["phase"] in {"control", "inflight", "cache", "cache-revoke"} else 0
        )
        if remote:
            assert remote[0] == {
                "query": "fixture",
                "experiment_id": exp,
                "instrument_ids": ["sim-temp", "sim-magnet", "sim-smu"],
            }
        requests = len((directory / "control" / (exp + ".requests")).read_text().splitlines())
        assert requests == (1 if revoked else 2)
        record.update(mcp_requests=len(remote), https_requests=requests, restart_no_change=True)
    report = "mcp-cache" if cache else "mcp-runtime" if advanced else "mcp-grant"
    (ROOT / f"reports/d12d3-{report}-evidence.json").write_text(
        json.dumps(
            {
                "completed_at": datetime.now(UTC).isoformat(),
                "cases": records,
                "images": {k: c["Image"] for k, c in deployed.items()},
                "scope": "maintenance discovery; API grant/revoke; loopback MCP; real HTTPS model",
            },
            indent=2,
        )
        + "\n"
    )
    print(f"PASS: four deployed {report} cases; no unauthorized publication or replay")
    return 0
