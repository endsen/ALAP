"""D08 scoped resource persistence. Every read and cached use rechecks current grants."""

from uuid import uuid4

from psycopg.types.json import Jsonb

from alap.adapters.postgres.agents import PostgresAgentStore
from alap.adapters.postgres.read_locks import lock_read
from alap.application.experiments import digest, require


def check_references(db, run, checkpoint):
    allowed = set(run["bundle"]["config"]["manifest"]["scoped_instruments"])
    for ref in checkpoint.get("external_refs", []):
        kind = ref["kind"]
        if kind == "knowledge":
            lock_read(db, "knowledge", ref["id"], run["actor_id"])
            row = db.execute(
                """SELECT k.* FROM knowledge_versions k JOIN knowledge_grants g
              ON g.source_version_id=k.id WHERE k.id=%s AND g.actor_id=%s
              AND NOT g.revoked AND k.enabled""",
                (ref["id"], run["actor_id"]),
            ).fetchone()
            require(
                row is not None
                and row["experiment_id"] == run["experiment_id"]
                and set(row["resources"]) <= allowed
                and row["content_hash"] == ref["hash"]
                and (row["agent_ref"] is None or row["agent_ref"] == run["definition_ref"]),
                "SOURCE_REVOKED",
                "Knowledge version no longer accessible",
            )
        elif kind == "analysis":
            lock_read(db, "analysis", ref["id"])
            row = db.execute(
                """SELECT a.*,d.state,d.manifest_json,d.checksum AS current_checksum
              FROM dataset_analyses a JOIN datasets d ON a.dataset_id=d.id
              WHERE a.id=%s""",
                (ref["id"],),
            ).fetchone()
            require(
                row is not None
                and row["experiment_id"] == run["experiment_id"]
                and row["state"] == "COMMITTED"
                and row["checksum"] == row["current_checksum"]
                and digest(row["result"]) == ref["hash"]
                and set(row["manifest_json"]["instrument_ids"]) <= allowed,
                "EVIDENCE_REVOKED",
                "Analysis source unavailable or outside scope",
            )
        elif kind == "mcp":
            lock_read(db, "mcp", ref["id"], run["actor_id"], run["experiment_id"])
            row = db.execute(
                """SELECT t.*,c.enabled,g.resources,g.revoked FROM mcp_tools t
              JOIN mcp_connections c ON c.ref=t.connection_ref JOIN mcp_grants g ON g.tool_id=t.id
              WHERE t.id=%s AND g.actor_id=%s AND g.experiment_id=%s""",
                (ref["id"], run["actor_id"], run["experiment_id"]),
            ).fetchone()
            require(
                row is not None
                and row["current"]
                and row["enabled"]
                and not row["revoked"]
                and allowed <= set(row["resources"])
                and row["spec_hash"] == ref["hash"],
                "MCP_REVOKED",
                "MCP binding changed or grant unavailable",
            )
        else:
            require(False, "SOURCE_TYPE", "Unknown external reference")


class PostgresResourceStore(PostgresAgentStore):
    def add_source(self, actor, experiment_id, document):
        with self.connect() as db:
            self._access(db, actor, experiment_id, document["resources"], proposal=True)
            value = {**document, "experiment_id": experiment_id, "owner_id": actor}
            identity = str(uuid4())
            db.execute(
                """INSERT INTO knowledge_versions
              (id,experiment_id,source_id,version,kind,owner_id,agent_ref,resources,content,source_uri,content_hash)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    identity,
                    experiment_id,
                    document["source_id"],
                    document["version"],
                    document["kind"],
                    actor,
                    document.get("agent_ref"),
                    Jsonb(document["resources"]),
                    document["content"],
                    document["source_uri"],
                    digest(value),
                ),
            )
            db.execute(
                "INSERT INTO knowledge_grants(source_version_id,actor_id) VALUES (%s,%s)",
                (identity, actor),
            )
            return identity

    def share_source(self, actor, identity, recipient, *, revoked=False):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM knowledge_versions WHERE id=%s FOR SHARE", (identity,)
            ).fetchone()
            require(
                row is not None and row["owner_id"] == actor, "FORBIDDEN", "Source owner required"
            )
            self._access(db, actor, row["experiment_id"], row["resources"], proposal=True)
            if not revoked:
                self._access(db, recipient, row["experiment_id"], row["resources"])
            db.execute(
                """INSERT INTO knowledge_grants(source_version_id,actor_id,revoked)
              VALUES (%s,%s,%s) ON CONFLICT(source_version_id,actor_id)
              DO UPDATE SET revoked=EXCLUDED.revoked""",
                (identity, recipient, revoked),
            )

    def source(self, actor, experiment_id, identity, resources, agent_ref):
        with self.connect() as db:
            self._access(db, actor, experiment_id, resources)
            row = db.execute("SELECT * FROM knowledge_versions WHERE id=%s", (identity,)).fetchone()
            require(row is not None, "SOURCE_REVOKED", "Source missing")
            run = {
                "actor_id": actor,
                "experiment_id": experiment_id,
                "definition_ref": agent_ref,
                "bundle": {"config": {"manifest": {"scoped_instruments": resources}}},
            }
            ref = {"kind": "knowledge", "id": identity, "hash": row["content_hash"]}
            check_references(db, run, {"external_refs": [ref]})
            return {
                "reference": ref,
                "source_uri": row["source_uri"],
                "source_id": row["source_id"],
                "version": row["version"],
                "kind": row["kind"],
                "content": row["content"],
                "trust": "untrusted_source_not_authority",
            }

    def search(self, actor, experiment_id, query, resources, agent_ref, limit):
        with self.connect() as db:
            self._access(db, actor, experiment_id, resources)
            rows = db.execute(
                """SELECT k.id FROM knowledge_versions k JOIN knowledge_grants g
              ON k.id=g.source_version_id WHERE g.actor_id=%s AND NOT g.revoked AND k.enabled
              AND k.experiment_id=%s AND k.resources <@ %s
              AND (k.agent_ref IS NULL OR k.agent_ref=%s) AND strpos(lower(k.content),lower(%s))>0
              ORDER BY k.source_id,k.version DESC LIMIT %s""",
                (actor, experiment_id, Jsonb(list(resources)), agent_ref, query, limit),
            ).fetchall()
        return [self.source(actor, experiment_id, r["id"], resources, agent_ref) for r in rows]

    def register_connection(self, ref, config):
        with self.connect() as db:
            db.execute(
                """INSERT INTO mcp_connections(ref,config,config_hash) VALUES (%s,%s,%s)
              ON CONFLICT DO NOTHING""",
                (ref, Jsonb(config), digest(config)),
            )
            row = db.execute(
                "SELECT config_hash FROM mcp_connections WHERE ref=%s", (ref,)
            ).fetchone()
            require(
                row["config_hash"] == digest(config),
                "VERSION_CONFLICT",
                "Connection version changed",
            )

    def connection(self, ref):
        with self.connect() as db:
            row = db.execute("SELECT * FROM mcp_connections WHERE ref=%s", (ref,)).fetchone()
            require(
                row is not None and row["enabled"], "MCP_DISABLED", "MCP connection unavailable"
            )
            return row["config"]

    def discovered(self, ref, tools):
        with self.connect() as db:
            entries = [{"id": str(uuid4()), "spec": tool, "hash": digest(tool)} for tool in tools]
            return [
                row["id"]
                for row in db.execute(
                    "SELECT refresh_mcp_discovery(%s,%s) AS id", (ref, Jsonb(entries))
                ).fetchall()
            ]

    def tool(self, identity):
        with self.connect() as db:
            row = db.execute("SELECT * FROM mcp_tools WHERE id=%s", (identity,)).fetchone()
            require(
                row is not None and row["current"], "MCP_CHANGED", "Tool requires discovery/review"
            )
            return row

    def grant_tool(self, identity, actor, experiment_id, resources, reviewer, *, revoked=False):
        require(bool(reviewer), "REVIEW_REQUIRED", "Trusted admin reviewer required")
        with self.connect() as db:
            self._access(db, actor, experiment_id, resources)
            db.execute(
                """INSERT INTO mcp_grants(tool_id,actor_id,experiment_id,resources,reviewer,revoked)
              VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(tool_id,actor_id,experiment_id)
              DO UPDATE SET resources=EXCLUDED.resources,reviewer=EXCLUDED.reviewer,
              revoked=EXCLUDED.revoked""",
                (identity, actor, experiment_id, Jsonb(list(resources)), reviewer, revoked),
            )

    def check_refs(self, run, refs):
        with self.connect() as db:
            self._access(
                db,
                run["actor_id"],
                run["experiment_id"],
                run["bundle"]["config"]["manifest"]["scoped_instruments"],
            )
            check_references(db, run, {"external_refs": refs})

    def claim_call(self, run, call_id, tool, arguments):
        with self.connect() as db:
            self._access(
                db,
                run["actor_id"],
                run["experiment_id"],
                run["bundle"]["config"]["manifest"]["scoped_instruments"],
            )
            check_references(
                db,
                run,
                {"external_refs": [{"kind": "mcp", "id": tool["id"], "hash": tool["spec_hash"]}]},
            )
            created = db.execute(
                """INSERT INTO mcp_calls(run_id,call_id,tool_id,input_hash,state)
              VALUES (%s,%s,%s,%s,'INFLIGHT') ON CONFLICT DO NOTHING""",
                (run["id"], call_id, tool["id"], digest(arguments)),
            ).rowcount
            row = db.execute(
                "SELECT * FROM mcp_calls WHERE run_id=%s AND call_id=%s FOR UPDATE",
                (run["id"], call_id),
            ).fetchone()
            require(
                row["tool_id"] == tool["id"] and row["input_hash"] == digest(arguments),
                "CALL_CONFLICT",
                "MCP call identity reused",
            )
            if not created:
                require(
                    row["state"] == "SUCCEEDED",
                    "MCP_UNKNOWN",
                    "Do not replay uncertain remote call",
                )
                return row["result"]
            return None

    def finish_call(self, run, call_id, result):
        with self.connect() as db:
            db.execute(
                """UPDATE mcp_calls SET state=%s,result=%s
              WHERE run_id=%s AND call_id=%s AND state='INFLIGHT'""",
                (
                    "SUCCEEDED" if result is not None else "UNKNOWN",
                    Jsonb(result),
                    run["id"],
                    call_id,
                ),
            )

    def dataset(self, actor, experiment_id, identity, resources):
        with self.connect() as db:
            self._access(db, actor, experiment_id, resources)
            lock_read(db, "dataset", identity)
            row = db.execute("SELECT * FROM datasets WHERE id=%s", (identity,)).fetchone()
            require(
                row is not None
                and row["experiment_id"] == experiment_id
                and row["state"] == "COMMITTED",
                "DATASET_NOT_COMMITTED",
                "Only scoped committed data may be analyzed",
            )
            require(
                set(row["manifest_json"]["instrument_ids"]) <= set(resources),
                "FORBIDDEN",
                "Dataset exceeds Agent resources",
            )
            return row

    def save_analysis(self, actor, experiment_id, dataset, resources, result):
        with self.connect() as db:
            self._access(db, actor, experiment_id, resources)
            lock_read(db, "dataset", dataset["id"])
            row = db.execute("SELECT * FROM datasets WHERE id=%s", (dataset["id"],)).fetchone()
            require(
                row["state"] == "COMMITTED" and row["checksum"] == dataset["checksum"],
                "EVIDENCE_REVOKED",
                "Dataset changed during analysis",
            )
            value = db.execute(
                """INSERT INTO dataset_analyses
              (id,experiment_id,dataset_id,checksum,algorithm,result) VALUES (%s,%s,%s,%s,%s,%s)
              ON CONFLICT(dataset_id,checksum,algorithm) DO NOTHING
              RETURNING *""",
                (
                    str(uuid4()),
                    experiment_id,
                    dataset["id"],
                    dataset["checksum"],
                    result["algorithm"],
                    Jsonb(result),
                ),
            ).fetchone()
            if value is None:
                value = db.execute(
                    """SELECT * FROM dataset_analyses
                  WHERE dataset_id=%s AND checksum=%s AND algorithm=%s""",
                    (dataset["id"], dataset["checksum"], result["algorithm"]),
                ).fetchone()
            return {
                "reference": {
                    "kind": "analysis",
                    "id": value["id"],
                    "hash": digest(value["result"]),
                },
                "summary": value["result"],
            }

    def materialize(self, run, refs):
        self.check_refs(run, refs)
        values = []
        for ref in refs:
            if ref["kind"] == "knowledge":
                source = self.source(
                    run["actor_id"],
                    run["experiment_id"],
                    ref["id"],
                    run["bundle"]["config"]["manifest"]["scoped_instruments"],
                    run["definition_ref"],
                )
                source["content"] = source["content"][:1500]
                values.append(source)
            elif ref["kind"] == "analysis":
                with self.connect() as db:
                    row = db.execute(
                        "SELECT result FROM dataset_analyses WHERE id=%s", (ref["id"],)
                    ).fetchone()
                values.append({"reference": ref, "summary": row["result"]})
            else:
                require(False, "SOURCE_TYPE", "MCP references are bound through tools only")
        self.check_refs(run, refs)
        return values

    def dataset_event(self, actor, event_id, resources):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM outbox_events WHERE event_id=%s", (event_id,)
            ).fetchone()
            require(
                row is not None and row["event_type"] == "dataset.committed.v1",
                "EVENT_UNSUPPORTED",
                "Authoritative committed-data event required",
            )
            self._access(db, actor, row["experiment_id"], resources)
            return row

    def claim_collaboration(self, actor, experiment, definition, evidence_hash, max_runs, cooldown):
        with self.connect() as db:
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,8))",
                (experiment + ":" + actor + ":" + definition,),
            )
            row = db.execute(
                """SELECT * FROM collaboration_claims WHERE experiment_id=%s
              AND actor_id=%s AND definition_ref=%s AND evidence_hash=%s""",
                (experiment, actor, definition, evidence_hash),
            ).fetchone()
            if row:
                return row
            counts = db.execute(
                """SELECT count(*) AS n,
              COALESCE(extract(epoch FROM clock_timestamp()-max(created_at)),1e9) AS elapsed
              FROM collaboration_claims WHERE experiment_id=%s
              AND actor_id=%s AND definition_ref=%s""",
                (experiment, actor, definition),
            ).fetchone()
            require(
                counts["n"] < max_runs and counts["elapsed"] >= cooldown,
                "COLLABORATION_BUDGET",
                "Replan count or cooldown exhausted",
            )
            return db.execute(
                """INSERT INTO collaboration_claims
              (experiment_id,actor_id,definition_ref,evidence_hash)
              VALUES (%s,%s,%s,%s) RETURNING *""",
                (experiment, actor, definition, evidence_hash),
            ).fetchone()

    def bind_collaboration(self, actor, experiment, definition, evidence_hash, identity):
        with self.connect() as db:
            db.execute(
                """UPDATE collaboration_claims SET run_id=%s WHERE experiment_id=%s
              AND actor_id=%s AND definition_ref=%s AND evidence_hash=%s AND run_id IS NULL""",
                (identity, experiment, actor, definition, evidence_hash),
            )

    def has_run(self, identity):
        with self.connect() as db:
            return (
                db.execute("SELECT id FROM agent_runs WHERE id=%s", (identity,)).fetchone()
                is not None
            )
