"""Live retrieval and in-flight revocation through the isolated HTTPS deployment drill."""

import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from uuid import uuid4

from check_agent import execute
from manage import ROOT
from model_faults import wait
from model_provider import KNOWLEDGE_TEXT


def cases(suffix):
    return [
        {
            "experiment": f"EXP-AGENT-{vendor}-{mode.replace('_', '-')}-{suffix}",
            "id": f"drill-{vendor}-{mode}-{suffix}",
            "vendor": vendor,
            "mode": mode,
            "knowledge": True,
            "guide": f"guide-{vendor}-{mode}-{suffix}",
        }
        for vendor in ("openai", "deepseek")
        for mode in ("knowledge_control", "knowledge_injection", "knowledge_revoke")
    ]


def run_knowledge(runtime, state, directory, deployed):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api(path, body=None, *, expected=200):
        request = urllib.request.Request(
            "http://127.0.0.1:3000/api/v1" + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Authorization": "Bearer " + state["owner"],
                "Content-Type": "application/json",
                "Idempotency-Key": str(uuid4()),
            },
        )
        try:
            with opener.open(request, timeout=15) as response:
                status, value = response.status, json.load(response)
        except urllib.error.HTTPError as error:
            status, value = error.code, json.load(error)
        assert status == expected, (path, status)
        return value

    records = []
    for case in state["cases"]:
        exp, mode = case["experiment"], case["mode"]
        source = api(
            "/experiments/" + exp + "/knowledge",
            {
                "source_id": case["id"],
                "version": 1,
                "kind": "document",
                "resources": ["sim-temp", "sim-magnet", "sim-smu"],
                "content": KNOWLEDGE_TEXT,
                "source_uri": "alap:injection-drill",
            },
            expected=201,
        )["id"]
        run = api(
            "/agent-runs",
            {
                "experiment_id": exp,
                "definition_ref": case["id"] + "@1",
                "goal": "D12D3:" + mode + "\nRead scoped IV literature and summarize it.",
            },
            expected=201,
        )
        path = "/agent-runs/" + run["id"]
        if mode == "knowledge_revoke":
            wait(lambda exp=exp: (directory / "control" / (exp + ".waiting")).exists(), bool)
            # This API operation completes while the HTTPS provider holds round two.
            api("/knowledge/" + source + "/share", {"actor_id": "admin", "revoked": True})
            pending = api(path)
            assert pending["status"] == "RUNNING" and pending["access_error"] == "SOURCE_REVOKED"
            assert pending["goal"] == "内容不可访问" and pending["result"] is None
            (directory / "control" / (exp + ".release")).touch()
        final = wait(
            lambda path=path: api(path),
            lambda r: r["status"] in {"COMPLETED", "FAILED", "CANCELLED"},
        )
        assert final["status"] == ("COMPLETED" if mode == "knowledge_control" else "FAILED")
        reference = json.loads((directory / "control" / (exp + ".verified")).read_text())
        assert reference["id"] == source and reference["kind"] == "knowledge"
        if mode == "knowledge_revoke":
            assert final["access_error"] == "SOURCE_REVOKED" and final["result"] is None
            for suffix in ("/trace", "/proposals"):
                assert api(path + suffix, expected=422)["error"]["code"] == "SOURCE_REVOKED"
        else:
            trace = api(path + "/trace")["items"]
            if mode == "knowledge_injection":
                # ChatModelClient rejects the undeclared tool before runtime tool dispatch.
                assert trace[-1]["event"] == {"type": "blocked", "code": "MODEL_FAILURE"}
            else:
                assert final["result"] == "Scoped literature summary; no execution."
        record = json.loads(
            execute(
                runtime,
                """import json,psycopg
from alap.adapters.postgres.settings import database_url
with psycopg.connect(database_url()) as db:
 db.execute('SET TRANSACTION READ ONLY')
 cp=db.execute('SELECT checkpoint FROM agent_runs WHERE id=%s',(RUN,)).fetchone()[0]
 event=db.execute('SELECT event FROM agent_trace WHERE run_id=%s ORDER BY seq DESC LIMIT 1',
                  (RUN,)).fetchone()[0]
 source_hash=db.execute('SELECT content_hash FROM knowledge_versions WHERE id=%s',
                        (SOURCE,)).fetchone()[0]
 calls=db.execute('SELECT tool_ref FROM agent_tool_invocations WHERE run_id=%s',
                  (RUN,)).fetchall()
 writes={t:db.execute('SELECT count(*) FROM '+t+' WHERE experiment_id=%s',(EXP,)).fetchone()[0]
         for t in ('plan_revisions','approvals','runs','tasks','command_ledger','datasets')}
 writes['proposals']=db.execute('SELECT count(*) FROM agent_proposals WHERE run_id=%s',
                                (RUN,)).fetchone()[0]
 print(json.dumps({'status':cp['status'],'stage':cp['stage'],'iterations':cp['iterations'],
    'reserved_tokens':cp['reserved_tokens'],'result_is_null':cp['result'] is None,
    'references':cp['external_refs'],'event':event,'source_hash':source_hash,
    'tools':[r[0] for r in calls],'writes':writes}))
""".replace("RUN", repr(run["id"]))
                .replace("SOURCE", repr(source))
                .replace("EXP", repr(exp)),
            )
        )
        assert record["source_hash"] == reference["hash"]
        assert record["references"] == [reference]
        assert record["tools"] == ["search_knowledge@1"]
        assert record["iterations"] == 2 and record["reserved_tokens"] > 0
        assert all(n == 0 for n in record["writes"].values())
        if mode == "knowledge_revoke":
            assert record["event"] == {
                "type": "blocked",
                "code": "SOURCE_REVOKED",
                "prior_stage": "inflight",
                "model_outcome_unknown": True,
            }
            assert record["stage"] == "done" and record["result_is_null"]
        requests = directory / "control" / (exp + ".requests")
        assert len(requests.read_text().splitlines()) == 2
        records.append(
            {
                "vendor": case["vendor"],
                "mode": mode,
                "experiment": exp,
                "run": run["id"],
                "https_requests": 2,
                "evidence": record,
            }
        )
    # Recheck every completed case after all six scenarios: no background replay.
    for case in state["cases"]:
        assert (
            len(
                (directory / "control" / (case["experiment"] + ".requests"))
                .read_text()
                .splitlines()
            )
            == 2
        )
    (ROOT / "reports/d12d3-knowledge-https-evidence.json").write_text(
        json.dumps(
            {
                "completed_at": datetime.now(UTC).isoformat(),
                "cases": records,
                "model": "isolated HTTPS/SSE substitute, no online vendor calls",
                "images": {k: c["Image"] for k, c in deployed.items()},
            },
            indent=2,
        )
        + "\n"
    )
    print("PASS: six deployed knowledge cases; real retrieval, zero proposal/device writes")
    return 0
