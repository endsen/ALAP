"""Version changes through the deployed API, with frozen run bindings and real HTTPS."""

import json
import urllib.error
import urllib.request
from copy import deepcopy
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
            "mode": "version_pin",
            "guide_content": "VERSION_PIN_OLD: Only read scoped state; never execute devices.",
            "extra_versions": [2],
        }
        for vendor in ("openai", "deepseek")
        for phase in ("model-new", "model-disabled", "skill-new")
    ]


def run_versions(runtime, state, directory, deployed):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api(path, body=None, *, method=None, expected=200, revision=None):
        headers = {
            "Authorization": "Bearer " + state["owner"],
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

    def binding(identity):
        return json.loads(
            execute(
                runtime,
                """import json,psycopg
from alap.adapters.postgres.settings import database_url
with psycopg.connect(database_url()) as db:
 db.execute('SET TRANSACTION READ ONLY')
 r=db.execute('SELECT bundle_hash,bundle FROM agent_runs WHERE id=%s',(RUN,)).fetchone()
 print(json.dumps({'hash':r[0],'model':r[1]['model'],'skills':r[1]['skills']}))
""".replace("RUN", repr(identity)),
            )
        )

    worker = deployed["agent-drill"]["Id"]
    records = []
    for case in state["cases"]:
        runtime.output([DOCKER, "stop", worker])
        exp, ident, phase = case["experiment"], case["id"], case["phase"]
        run = api(
            "/agent-runs",
            {
                "experiment_id": exp,
                "definition_ref": ident + "@1",
                "goal": "D12D3:version_pin\nRead only.",
            },
            expected=201,
        )
        path = "/agent-runs/" + run["id"]
        assert api(path)["status"] == "READY"
        before = binding(run["id"])
        if phase.startswith("model"):
            row = next(r for r in api("/models")["items"] if r["ref"] == ident + "@1")
            original = {
                k: v
                for k, v in row["document"].items()
                if k not in {"temperature", "price_reference"}
            }
            changed = deepcopy(original)
            changed["capabilities"]["tools"] = "unsupported"
            assert api("/models", changed, expected=409)["error"]["code"] == "VERSION_CONFLICT"
            new = deepcopy(original)
            new["version"] = 2
            if phase == "model-new":
                new["capabilities"]["tools"] = "unsupported"
            api("/models", new, expected=201)
            if phase == "model-new":
                definition = api("/agents/" + ident + "@1")["document"]
                definition["manifest"].update(version=2, model_ref=ident + "@2")
                api("/agents", definition, expected=201)
                denied = api("/agents/" + ident + "@2/publish", method="POST", expected=422)
                assert denied["error"]["code"] == "MODEL_UNAVAILABLE"
                assert api("/agents/" + ident + "@2")["state"] == "DRAFT"
            else:
                api("/models/" + ident + "@1/disable", method="POST", revision=row["revision"])
        else:
            original = api("/skills/" + case["guide"] + "@1")["document"]
            changed = deepcopy(original)
            changed["content"] = "VERSION_PIN_NEW: New instruction version."
            assert api("/skills", changed, expected=409)["error"]["code"] == "VERSION_CONFLICT"
            changed["version"] = 2
            api("/skills", changed, expected=201)
            api("/skills/" + case["guide"] + "@2/publish", method="POST")
            assert api("/skills/" + case["guide"] + "@2")["state"] == "PUBLISHED"
        assert binding(run["id"]) == before
        runtime.output([DOCKER, "start", worker])
        final = wait(
            lambda path=path: api(path),
            lambda r: r["status"] in {"COMPLETED", "FAILED", "CANCELLED"},
        )
        disabled = phase == "model-disabled"
        assert final["status"] == ("FAILED" if disabled else "COMPLETED")
        assert final["result"] == (None if disabled else "Read-only retry result.")
        trace = api(path + "/trace")["items"]
        if disabled:
            assert trace[-1]["event"] == {"type": "blocked", "code": "CONFIG_DISABLED"}
        else:
            completed = [t["event"] for t in trace if t["event"]["type"] == "model_completed"]
            assert len(completed) == 1 and len(completed[0]["attempts"]) == 1
        assert binding(run["id"]) == before
        writes = json.loads(
            execute(
                runtime,
                """import json,psycopg
from alap.adapters.postgres.settings import database_url
with psycopg.connect(database_url()) as db:
 db.execute('SET TRANSACTION READ ONLY')
 counts={t:db.execute('SELECT count(*) FROM '+t+' WHERE experiment_id=%s',(EXP,)).fetchone()[0]
         for t in ('plan_revisions','approvals','runs','tasks','command_ledger','datasets')}
 for t in ('agent_proposals','agent_tool_invocations'):
  counts[t]=db.execute('SELECT count(*) FROM '+t+' WHERE run_id=%s',(RUN,)).fetchone()[0]
 print(json.dumps(counts))
""".replace("RUN", repr(run["id"])).replace("EXP", repr(exp)),
            )
        )
        assert all(n == 0 for n in writes.values())
        records.append(
            {
                "vendor": case["vendor"],
                "phase": phase,
                "experiment": exp,
                "status": final["status"],
                "binding_hash": before["hash"],
                "model_version": before["model"]["version"],
                "skill_refs": list(before["skills"]),
                "writes": writes,
                "overwrite_rejected": True,
                "binding_unchanged": True,
            }
        )
    for case, record in zip(state["cases"], records, strict=True):
        request_file = directory / "control" / (case["experiment"] + ".requests")
        calls = len(request_file.read_text().splitlines()) if request_file.exists() else 0
        assert calls == (0 if case["phase"] == "model-disabled" else 1)
        record["https_requests"] = calls
    (ROOT / "reports/d12d3-version-binding-evidence.json").write_text(
        json.dumps(
            {
                "completed_at": datetime.now(UTC).isoformat(),
                "cases": records,
                "images": {k: c["Image"] for k, c in deployed.items()},
                "scope": (
                    "deployed API version changes; offline HTTPS; no live provider capability claim"
                ),
            },
            indent=2,
        )
        + "\n"
    )
    print("PASS: six deployed version-binding cases; no silent upgrade or model fallback")
    return 0
