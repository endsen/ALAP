"""D09 identity and API read models. Database is authoritative for every request."""

import hashlib
import secrets
from datetime import UTC, timedelta

from psycopg.types.json import Jsonb

from alap.adapters.postgres.resources import PostgresResourceStore
from alap.application.experiments import digest, require
from alap.domain.rules import DomainError


class PostgresAPIStore(PostgresResourceStore):
    def issue_token(self, actor, *, seconds=3600):
        """Trusted bootstrap/identity-provider boundary, never an anonymous HTTP endpoint."""
        require(type(seconds) is int and 1 <= seconds <= 86400, "INVALID_TTL", "Bounded token TTL")
        token = secrets.token_urlsafe(48)
        with self.connect() as db:
            principal = db.execute("SELECT * FROM principals WHERE id=%s", (actor,)).fetchone()
            require(principal and principal["disabled_at"] is None, "FORBIDDEN", "Active principal")
            db.execute(
                """INSERT INTO api_tokens VALUES (%s,%s,clock_timestamp()+%s,FALSE)""",
                (hashlib.sha256(token.encode()).hexdigest(), actor, timedelta(seconds=seconds)),
            )
        return token

    def authenticate(self, token):
        require(
            isinstance(token, str) and 32 <= len(token) <= 256,
            "UNAUTHENTICATED",
            "Bearer token required",
        )
        with self.connect() as db:
            row = db.execute(
                """SELECT p.id,p.kind,COALESCE(r.role,'observer') AS role
              FROM api_tokens t JOIN principals p ON p.id=t.actor_id
              LEFT JOIN platform_roles r ON r.actor_id=p.id
              WHERE t.token_hash=%s AND NOT t.revoked AND t.expires_at>clock_timestamp()
                AND p.disabled_at IS NULL""",
                (hashlib.sha256(token.encode()).hexdigest(),),
            ).fetchone()
        require(row is not None, "UNAUTHENTICATED", "Invalid or expired token")
        return row

    def role(self, actor, allowed):
        with self.connect() as db:
            row = db.execute(
                """SELECT r.role FROM platform_roles r JOIN principals p ON p.id=r.actor_id
              WHERE r.actor_id=%s AND p.disabled_at IS NULL""",
                (actor,),
            ).fetchone()
            require(row and row["role"] in allowed, "FORBIDDEN", "Platform role required")

    def audit(self, actor, operation, target):
        with self.connect() as db:
            db.execute(
                "INSERT INTO api_audit(actor_id,operation,target) VALUES (%s,%s,%s)",
                (actor, operation, target),
            )

    def request_claim(self, actor, operation, key, fingerprint):
        with self.connect() as db:
            inserted = db.execute(
                """INSERT INTO api_requests VALUES (%s,%s,%s,%s,'INFLIGHT',NULL,NULL)
              ON CONFLICT DO NOTHING""",
                (actor, operation, key, fingerprint),
            ).rowcount
            row = db.execute(
                "SELECT * FROM api_requests WHERE actor_id=%s AND operation=%s AND key=%s",
                (actor, operation, key),
            ).fetchone()
            require(row["request_hash"] == fingerprint, "IDEMPOTENCY_CONFLICT", "Different request")
            if inserted:
                return None
            if row["state"] == "FAILED":
                raise DomainError(row["error_code"], "Previous request failed")
            require(
                row["state"] == "DONE", "EXECUTION_UNKNOWN", "Inspect result; no automatic replay"
            )
            return row["response"]

    def request_finish(self, actor, operation, key, result=None, error=None):
        with self.connect() as db:
            db.execute(
                """UPDATE api_requests SET state=%s,response=%s,error_code=%s
              WHERE actor_id=%s AND operation=%s AND key=%s AND state='INFLIGHT' """,
                ("FAILED" if error else "DONE", Jsonb(result), error, actor, operation, key),
            )

    def experiments(self, actor, cursor, limit):
        with self.connect() as db:
            return db.execute(
                """SELECT e.* FROM experiments e JOIN experiment_memberships m
              ON m.experiment_id=e.id JOIN principals p ON p.id=m.actor_id
              WHERE m.actor_id=%s AND m.revoked_at IS NULL AND p.disabled_at IS NULL AND e.id>%s
              ORDER BY e.id LIMIT %s""",
                (actor, cursor, limit),
            ).fetchall()

    def membership_update(self, actor, experiment, recipient, role, scope, expected, revoked):
        with self.connect() as db:
            exp = db.execute(
                "SELECT * FROM experiments WHERE id=%s FOR UPDATE", (experiment,)
            ).fetchone()
            require(exp is not None, "NOT_FOUND", "Experiment missing")
            _, member = self._access(db, actor, experiment, [])
            require(member["role"] == "owner", "FORBIDDEN", "Owner required")
            require(exp["revision"] == expected, "STATE_CONFLICT", "Reload snapshot")
            require(recipient != exp["owner_id"], "FORBIDDEN", "Owner cannot be removed here")
            require(
                set(scope["resources"]) <= set(member["scope"].get("resources", []))
                and set(scope["risk_levels"]) <= set(member["scope"].get("risk_levels", [])),
                "FORBIDDEN",
                "Cannot delegate beyond own scope",
            )
            principal = db.execute("SELECT id FROM principals WHERE id=%s", (recipient,)).fetchone()
            require(principal is not None, "NOT_FOUND", "Principal missing")
            db.execute(
                """INSERT INTO experiment_memberships(experiment_id,actor_id,role,scope,revoked_at)
              VALUES (%s,%s,%s,%s,CASE WHEN %s THEN clock_timestamp() ELSE NULL END)
              ON CONFLICT(experiment_id,actor_id) DO UPDATE SET role=excluded.role,
              scope=excluded.scope,revoked_at=excluded.revoked_at""",
                (experiment, recipient, role, Jsonb(scope), revoked),
            )
            db.execute("UPDATE experiments SET revision=revision+1 WHERE id=%s", (experiment,))
            db.execute(
                "INSERT INTO api_audit(actor_id,operation,target) VALUES (%s,%s,%s)",
                (actor, "membership", experiment + ":" + recipient),
            )
            return {"revision": expected + 1}

    def registry_list(self, kind, cursor, limit):
        with self.connect() as db:
            return db.execute(
                """SELECT kind,ref,document,state,content_hash,publisher FROM agent_registry
              WHERE kind=%s AND ref>%s ORDER BY ref LIMIT %s""",
                (kind, cursor, limit),
            ).fetchall()

    def config_put(self, kind, ref, document):
        with self.connect() as db:
            db.execute(
                """INSERT INTO platform_configs(kind,ref,document,content_hash)
              VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (kind, ref, Jsonb(document), digest(document)),
            )
            row = db.execute(
                "SELECT content_hash FROM platform_configs WHERE kind=%s AND ref=%s", (kind, ref)
            ).fetchone()
            require(
                row["content_hash"] == digest(document), "VERSION_CONFLICT", "New version required"
            )
        return {"ref": ref}

    def configs(self, kind):
        with self.connect() as db:
            return db.execute(
                "SELECT ref,document,enabled,revision FROM platform_configs "
                "WHERE kind=%s ORDER BY ref LIMIT 1000",
                (kind,),
            ).fetchall()

    def config_disable(self, kind, ref, expected):
        with self.connect() as db:
            changed = db.execute(
                """UPDATE platform_configs SET enabled=FALSE,revision=revision+1
              WHERE kind=%s AND ref=%s AND revision=%s""",
                (kind, ref, expected),
            ).rowcount
            require(changed == 1, "STATE_CONFLICT", "Config version changed")
            return {"ref": ref, "revision": expected + 1}

    def visible_instruments(self, actor):
        with self.connect() as db:
            return db.execute(
                """SELECT DISTINCT i.id,i.gateway_id,i.capability_version
              FROM instruments i JOIN experiment_memberships m ON m.scope->'resources' ? i.id
              JOIN principals p ON p.id=m.actor_id WHERE m.actor_id=%s
              AND m.revoked_at IS NULL AND p.disabled_at IS NULL ORDER BY i.id LIMIT 1000""",
                (actor,),
            ).fetchall()

    def run_rows(self, actor, experiment, cursor, limit):
        with self.connect() as db:
            self._access(db, actor, experiment, [])
            rows = db.execute(
                """SELECT id FROM agent_runs WHERE experiment_id=%s AND actor_id=%s
              AND id>%s ORDER BY id LIMIT %s""",
                (experiment, actor, cursor, limit),
            ).fetchall()
        return [self.load(actor, row["id"]) for row in rows]

    def traces(self, actor, identity):
        self.load(
            actor, identity
        )  # Current source ACL and resource scope, including completed runs.
        with self.connect() as db:
            return db.execute(
                "SELECT seq,event,occurred_at FROM agent_trace "
                "WHERE run_id=%s ORDER BY seq LIMIT 1000",
                (identity,),
            ).fetchall()

    def create_sample(self, actor, body):
        with self.connect() as db:
            db.execute(
                "INSERT INTO samples(id,owner_id,metadata) VALUES (%s,%s,%s)",
                (body["id"], actor, Jsonb(body["metadata"])),
            )
        return {"id": body["id"]}

    def samples(self, actor):
        with self.connect() as db:
            return db.execute(
                "SELECT id,metadata,version FROM samples WHERE owner_id=%s ORDER BY id LIMIT 1000",
                (actor,),
            ).fetchall()

    def check_source_owner(self, actor, identity):
        with self.connect() as db:
            row = db.execute("SELECT * FROM knowledge_versions WHERE id=%s", (identity,)).fetchone()
            require(row and row["owner_id"] == actor, "FORBIDDEN", "Source owner required")
            self._access(db, actor, row["experiment_id"], row["resources"], proposal=True)

    def mcp_directory(self):
        with self.connect() as db:
            connections = db.execute(
                "SELECT ref,enabled,config FROM mcp_connections ORDER BY ref LIMIT 1000"
            ).fetchall()
            for row in connections:
                row["config"].pop("secret_ref", None)
            tools = db.execute(
                "SELECT id,connection_ref,name,spec_hash,current FROM mcp_tools "
                "ORDER BY id LIMIT 1000"
            ).fetchall()
            return {"connections": connections, "tools": tools}

    def metrics(self, actor, experiment):
        with self.connect() as db:
            self._access(db, actor, experiment, [])
            runs = db.execute(
                "SELECT id FROM agent_runs WHERE actor_id=%s AND experiment_id=%s ORDER BY id",
                (actor, experiment),
            ).fetchall()
        events, groups = [], {}
        for row in runs:
            run = self.load(actor, row["id"])
            for record in self.traces(actor, row["id"]):
                event = record["event"]
                events.append(event)
                if event["type"] != "model_completed":
                    continue
                attempts = event.get("attempts", [])
                vendor = attempts[-1]["vendor"] if attempts else None
                day = record["occurred_at"].astimezone(UTC).date().isoformat()
                model_ref = run["bundle"]["config"]["manifest"]["model_ref"]
                key = (vendor, model_ref, run["definition_ref"], day)
                group = groups.setdefault(
                    key,
                    {
                        "vendor": vendor,
                        "model_ref": model_ref,
                        "agent_ref": run["definition_ref"],
                        "utc_day": day,
                        "experiment_id": experiment,
                        "model_completions": 0,
                        "recorded_attempts": 0,
                        "unknown_usage": 0,
                        "reported_tokens": None,
                        "estimated_cost": None,
                    },
                )
                group["model_completions"] += 1
                group["recorded_attempts"] += len(attempts)
                usage = event.get("usage")
                if usage is None:
                    group["unknown_usage"] += 1
                else:
                    totals = group["reported_tokens"] or dict.fromkeys(usage, 0)
                    group["reported_tokens"] = {k: totals[k] + usage[k] for k in totals}
        completed = [e for e in events if e["type"] == "model_completed"]
        attempts = [a for e in completed for a in e.get("attempts", [])]
        known = [e["usage"] for e in completed if e.get("usage") is not None]
        unknown = len(completed) - len(known)
        # Partial usage is explicitly partial; no inferred prices or zero for absent usage.
        return {
            "groups": list(groups.values()),
            "agent_runs": len(runs),
            "model_completions": len(completed),
            "recorded_attempts": len(attempts),
            "unknown_usage_completions": unknown,
            "usage_records": known,
            "reported_tokens": {
                field: sum(u[field] for u in known) if known else None
                for field in ("prompt_tokens", "completion_tokens", "total_tokens")
            },
            "logical_requests": sum(e["type"] == "model_reserved" for e in events),
            "unresolved_requests": sum(e["type"] == "model_reserved" for e in events)
            - len(completed),
            "estimated_cost": None,
            "scope": "current_actor_experiment",
            "latency": None,
        }

    def audit_rows(self, after, limit):
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM api_audit WHERE id>%s ORDER BY id LIMIT %s", (after, limit)
            ).fetchall()

    def disable_principal(self, actor):
        with self.connect() as db:
            changed = db.execute(
                "UPDATE principals SET disabled_at=clock_timestamp() WHERE id=%s", (actor,)
            ).rowcount
            require(changed == 1, "NOT_FOUND", "Principal missing")
        return {"disabled": True}

    def revoke_tokens(self, actor):
        with self.connect() as db:
            db.execute("UPDATE api_tokens SET revoked=TRUE WHERE actor_id=%s", (actor,))
        return {"revoked": True}

    def approved_tools(self):
        with self.connect() as db:
            return [
                r["id"]
                for r in db.execute(
                    """SELECT DISTINCT t.id FROM mcp_tools t JOIN mcp_grants g ON g.tool_id=t.id
                JOIN mcp_connections c ON c.ref=t.connection_ref
                WHERE t.current AND c.enabled AND NOT g.revoked"""
                ).fetchall()
            ]

    def set_experiment_scope(self, actor, experiment, scope, expected):
        with self.connect() as db:
            principal = db.execute(
                """SELECT p.id FROM principals p JOIN platform_roles r
              ON r.actor_id=p.id WHERE p.id=%s AND p.disabled_at IS NULL AND r.role='admin'
              FOR SHARE OF p,r""",
                (actor,),
            ).fetchone()
            require(principal, "FORBIDDEN", "Administrator required")
            exp = db.execute(
                "SELECT * FROM experiments WHERE id=%s FOR UPDATE", (experiment,)
            ).fetchone()
            require(exp is not None, "NOT_FOUND", "Experiment missing")
            require(exp["revision"] == expected, "STATE_CONFLICT", "Reload snapshot")
            known = db.execute(
                "SELECT id FROM instruments WHERE id=ANY(%s)", (scope["resources"],)
            ).fetchall()
            require(
                {r["id"] for r in known} == set(scope["resources"]),
                "FORBIDDEN",
                "Registered instruments required",
            )
            db.execute(
                """UPDATE experiment_memberships SET scope=%s,version=version+1
              WHERE experiment_id=%s AND actor_id=%s""",
                (Jsonb(scope), experiment, exp["owner_id"]),
            )
            db.execute("UPDATE experiments SET revision=revision+1 WHERE id=%s", (experiment,))
            db.execute(
                "INSERT INTO api_audit(actor_id,operation,target) VALUES (%s,%s,%s)",
                (actor, "set_scope", experiment),
            )
            return {"revision": expected + 1}

    def disable_mcp(self, ref):
        with self.connect() as db:
            changed = db.execute(
                "UPDATE mcp_connections SET enabled=FALSE WHERE ref=%s", (ref,)
            ).rowcount
            require(changed == 1, "NOT_FOUND", "Connection missing")
        return {"ref": ref, "enabled": False}

    def disable_source(self, actor, identity):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM knowledge_versions WHERE id=%s FOR UPDATE", (identity,)
            ).fetchone()
            require(row and row["owner_id"] == actor, "FORBIDDEN", "Source owner required")
            self._access(db, actor, row["experiment_id"], row["resources"], proposal=True)
            db.execute("UPDATE knowledge_versions SET enabled=FALSE WHERE id=%s", (identity,))
        return {"id": identity, "enabled": False}

    def proposals(self, actor, identity):
        self.load(actor, identity)
        with self.connect() as db:
            return db.execute(
                "SELECT id,state,proposal FROM agent_proposals "
                "WHERE run_id=%s ORDER BY id LIMIT 1000",
                (identity,),
            ).fetchall()

    def identity(self, actor):
        with self.connect() as db:
            row = db.execute(
                """SELECT p.id,p.kind,COALESCE(r.role,'observer') AS role
                FROM principals p LEFT JOIN platform_roles r ON r.actor_id=p.id
                WHERE p.id=%s AND p.disabled_at IS NULL""",
                (actor,),
            ).fetchone()
            require(row is not None, "UNAUTHENTICATED", "Active identity required")
            return row

    def runnable_agents(self, actor, experiment):
        with self.connect() as db:
            _, member = self._access(db, actor, experiment, [])
            rows = db.execute(
                "SELECT ref,document FROM agent_registry "
                "WHERE kind='agent' AND state='PUBLISHED' ORDER BY ref"
            ).fetchall()
            result = []
            for row in rows:
                m = row["document"]["manifest"]
                if experiment in m["scoped_experiments"] and set(m["scoped_instruments"]) <= set(
                    member["scope"].get("resources", [])
                ):
                    result.append(
                        {"ref": row["ref"], "kind": m["kind"], "model_ref": m["model_ref"]}
                    )
            return result
