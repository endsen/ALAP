"""Seed a source-bound READY run; no model or device calls, only simulation maintenance."""

import contextlib
import io
import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, "/app/deploy/simulation")
from agent_fixture import main  # noqa: E402

from alap.adapters.agents.bootstrap import build_agent  # noqa: E402
from alap.contracts import ContractCatalog  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()) as captured:
    main()
state = json.loads(captured.getvalue())
root = Path("/private")
settings = json.loads((root / "agent.json").read_text())
store, _, registry, _, resources, runtime = build_agent(
    (root / "deployment/components/api.dsn").read_text(),
    (root / "master.key").read_bytes(),
    ContractCatalog(Path("/app/contracts")),
    settings["execution_skills"],
    None,
)
case = state["cases"][0]
doc = deepcopy(store.version("agent", case["id"] + "@1")["document"])
doc["manifest"].update(version=2, context_policy="scoped_knowledge")
registry.import_agent(doc)
registry.publish_agent(case["id"] + "@2", "admin")
source = resources.import_source(
    "admin",
    case["experiment"],
    {
        "source_id": case["id"],
        "version": 1,
        "kind": "document",
        "resources": [],
        "content": "private deployed knowledge sentinel",
        "source_uri": "alap:private-drill",
    },
)
with store.connect() as db:
    content_hash = db.execute(
        "SELECT content_hash FROM knowledge_versions WHERE id=%s", (source,)
    ).fetchone()["content_hash"]
run = runtime.start(
    "admin",
    case["experiment"],
    case["id"] + "@2",
    "private deployed goal sentinel",
    source_refs=[{"kind": "knowledge", "id": source, "hash": content_hash}],
)
state.update(experiment=case["experiment"], run=run["id"], source=source)
print(json.dumps(state))
