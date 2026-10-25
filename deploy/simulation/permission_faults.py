"""Deployed Agent read isolation and membership revocation over authenticated HTTP."""

import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from uuid import uuid4

from check_agent import execute
from manage import ROOT
from model_faults import wait


def cases(suffix):
    return [
        {
            "experiment": f"EXP-AGENT-{v}-acl-{suffix}",
            "id": f"drill-{v}-acl-{suffix}",
            "guide": f"guide-{v}-acl-{suffix}",
            "vendor": v,
        }
        for v in ("openai", "deepseek")
    ]


def run_permissions(runtime, state, directory, deployed):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    records = []

    def api(path, body=None, *, actor="owner", method=None, expected=200, revision=None):
        headers = {"Content-Type": "application/json", "Idempotency-Key": str(uuid4())}
        if actor != "anonymous":
            headers["Authorization"] = "Bearer " + (
                state["owner"] if actor == "owner" else state["permission_tokens"][actor]
            )
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
        assert status == expected, (path, actor, status, result.get("error", {}).get("code"))
        if expected in (401, 403):
            assert "error" in result and "result" not in result and "items" not in result
        return result

    for case in state["cases"]:
        exp = case["experiment"]
        prefix = "/experiments/" + exp
        scope = {
            "resources": ["sim-temp", "sim-magnet", "sim-smu"],
            "risk_levels": ["operator_review"],
        }

        def membership(role, revoked=False, *, prefix=prefix, scope=scope):
            current = api(prefix)
            return api(
                prefix + "/members/" + state["permission_actors"][role],
                {"role": role, "scope": scope, "revoked": revoked},
                method="PUT",
                revision=current["revision"],
            )

        for role in ("observer", "operator", "approver"):
            membership(role)
        run = api(
            "/agent-runs",
            {
                "experiment_id": exp,
                "definition_ref": case["id"] + "@1",
                "goal": "D12D3:tool_recovery\nPropose a scoped IV plan.",
            },
            expected=201,
        )
        path = "/agent-runs/" + run["id"]
        final = wait(lambda path=path: api(path), lambda r: r["status"] in {"COMPLETED", "FAILED"})
        assert final["status"] == "COMPLETED"
        trace = api(path + "/trace")
        proposals = api(path + "/proposals")
        assert len(proposals["items"]) == 1 and proposals["items"][0]["state"] == "PROPOSED"
        assert api(prefix + "/agent-runs")["items"][0]["id"] == run["id"]
        assert api(prefix + "/usage")["agent_runs"] == 1
        checks = []
        for actor in ("observer", "operator", "approver", "outsider", "anonymous"):
            denied = 401 if actor == "anonymous" else 403
            for suffix in ("", "/trace", "/proposals"):
                api(path + suffix, actor=actor, expected=denied)
                checks.append([actor, "GET", "run" + suffix, denied])
            for suffix in ("/cancel", "/advance"):
                api(path + suffix, actor=actor, method="POST", expected=denied)
                checks.append([actor, "POST", "run" + suffix, denied])
            for suffix in ("/agent-runs", "/usage", "/dashboard"):
                allowed = actor in {"observer", "operator", "approver"}
                result = api(prefix + suffix, actor=actor, expected=200 if allowed else denied)
                if allowed:
                    if suffix == "/agent-runs":
                        assert result["items"] == []
                    else:
                        usage = result["usage"] if suffix == "/dashboard" else result
                        assert usage["agent_runs"] == 0 and usage["groups"] == []
                    assert run["id"] not in json.dumps(result)
                checks.append([actor, "GET", suffix, 200 if allowed else denied])
        # A fresh HTTP request must observe the committed membership revocation.
        for role in ("observer", "operator", "approver"):
            membership(role, True)
            for suffix in ("/agent-runs", "/usage", "/dashboard"):
                api(prefix + suffix, actor=role, expected=403)
                checks.append([role, "GET", "revoked" + suffix, 403])
        assert api(path) == final and api(path + "/trace") == trace
        assert api(path + "/proposals") == proposals
        counts = json.loads(
            execute(
                runtime,
                """import json,psycopg
from alap.adapters.postgres.settings import database_url
with psycopg.connect(database_url()) as db:
 db.execute('SET TRANSACTION READ ONLY')
 print(json.dumps({t:db.execute('SELECT count(*) FROM '+t+' WHERE experiment_id=%s',
   (EXP,)).fetchone()[0]
  for t in ('plan_revisions','approvals','runs','tasks','command_ledger','datasets')}))
""".replace("EXP", repr(exp)),
            )
        )
        assert all(n == 0 for n in counts.values())
        requests = (directory / "control" / (exp + ".requests")).read_text().splitlines()
        assert len(requests) == 2
        records.append(
            {
                "vendor": case["vendor"],
                "experiment": exp,
                "checks": checks,
                "https_requests": len(requests),
                "execution_writes": counts,
                "owner_state_trace_proposals_unchanged": True,
            }
        )
    (ROOT / "reports/d12d3-permissions-evidence.json").write_text(
        json.dumps(
            {
                "completed_at": datetime.now(UTC).isoformat(),
                "cases": records,
                "images": {k: c["Image"] for k, c in deployed.items()},
                "scope": (
                    "HTTP read isolation, non-owner control denial, membership revoke; "
                    "no MCP or in-flight owner revoke"
                ),
            },
            indent=2,
        )
        + "\n"
    )
    print("PASS: deployed permissions matrix; 98 HTTP assertions across two vendors")
    return 0
