"""Agent storage, distinct from experiment execution. No network I/O in transactions."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from alap.adapters.postgres.read_locks import lock_read
from alap.application.experiments import digest, require
from alap.domain.rules import freeze_revision


class PostgresAgentStore:
    def __init__(self, dsn):
        self.dsn = dsn
        self._owner = ContextVar("agent_owner", default=None)

    def connect(self, **kwargs):
        return psycopg.connect(self.dsn, row_factory=dict_row, **kwargs)

    def import_version(self, kind, ref, document):
        frozen = freeze_revision(document)
        with self.connect() as db:
            db.execute(
                """INSERT INTO agent_registry(kind,ref,document,canonical_bytes,content_hash)
              VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (kind, ref, Jsonb(document), frozen.canonical_bytes, frozen.plan_hash),
            )
            row = db.execute(
                "SELECT content_hash FROM agent_registry WHERE kind=%s AND ref=%s", (kind, ref)
            ).fetchone()
            require(
                row["content_hash"] == frozen.plan_hash,
                "VERSION_CONFLICT",
                "Version content cannot change",
            )

    def version(self, kind, ref):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM agent_registry WHERE kind=%s AND ref=%s", (kind, ref)
            ).fetchone()
            require(row is not None, "NOT_FOUND", "Registry version missing")
            require(
                digest(row["document"]) == row["content_hash"], "REGISTRY_CORRUPT", "Hash mismatch"
            )
            return row

    def publish(self, kind, ref, publisher, *, bundle=None):
        require(bool(publisher), "PUBLISHER_REQUIRED", "Publisher required")
        with self.connect() as db:
            changed = db.execute(
                """UPDATE agent_registry SET state='PUBLISHED', publisher=%s,
              validated_at=clock_timestamp(), published_bundle=%s, published_hash=%s
              WHERE kind=%s AND ref=%s AND state='DRAFT'""",
                (
                    publisher,
                    Jsonb(bundle) if bundle else None,
                    digest(bundle) if bundle else None,
                    kind,
                    ref,
                ),
            ).rowcount
            require(changed == 1, "INVALID_STATE", "Only draft versions can publish")

    def disable(self, kind, ref):
        with self.connect() as db:
            changed = db.execute(
                "UPDATE agent_registry SET state='DISABLED' WHERE kind=%s AND ref=%s", (kind, ref)
            ).rowcount
            require(changed == 1, "NOT_FOUND", "Registry version missing")

    def _access(self, db, actor, experiment_id, resources, *, proposal=False):
        lock_read(db, "experiment", experiment_id)
        lock_read(db, "principal", actor)
        lock_read(db, "membership", experiment_id, actor)
        experiment = db.execute(
            "SELECT * FROM experiments WHERE id=%s", (experiment_id,)
        ).fetchone()
        principal = db.execute("SELECT * FROM principals WHERE id=%s", (actor,)).fetchone()
        membership = db.execute(
            """SELECT * FROM experiment_memberships
          WHERE experiment_id=%s AND actor_id=%s""",
            (experiment_id, actor),
        ).fetchone()
        require(
            experiment is not None and principal is not None and membership is not None,
            "FORBIDDEN",
            "Explicit experiment membership required",
        )
        require(
            principal["disabled_at"] is None and membership["revoked_at"] is None,
            "FORBIDDEN",
            "Access revoked",
        )
        require(
            not proposal or membership["role"] in {"owner", "operator"},
            "FORBIDDEN",
            "Proposal requires operator role",
        )
        require(
            set(resources) <= set(membership["scope"].get("resources", [])),
            "FORBIDDEN",
            "Resources exceed membership",
        )
        return experiment, membership

    def context(self, actor, experiment_id, resources):
        with self.connect() as db:
            exp, membership = self._access(db, actor, experiment_id, resources)
            # Preserve all safety boundaries; never summarize UNKNOWN into success.
            commands = db.execute(
                """SELECT id,state FROM command_ledger
              WHERE experiment_id=%s AND instrument_id=ANY(%s)
              AND state IN ('UNKNOWN','NEEDS_RECONCILIATION')""",
                (experiment_id, list(resources)),
            ).fetchall()
            approvals = db.execute(
                """SELECT id,state,plan_hash FROM approvals WHERE experiment_id=%s
                  AND scope_json->'resources' <@ %s""",
                (experiment_id, Jsonb(list(resources))),
            ).fetchall()
            controls = db.execute(
                """SELECT id,quarantined,reason FROM resource_controls
              WHERE id=ANY(%s) ORDER BY id""",
                (list(resources),),
            ).fetchall()
            return {
                "experiment_id": experiment_id,
                "snapshot_version": exp["revision"],
                "experiment_state": exp["state"],
                "resources": sorted(resources),
                "unknown_commands": commands,
                "approval_boundaries": approvals,
                "resource_controls": controls,
                "risk_levels": membership["scope"].get("risk_levels", []),
                "authority": "database_snapshot_not_physical_readback",
            }

    def _active(self, db, bundle, ref):
        refs = [("agent", ref), *(("skill", r) for r in bundle["skills"])]
        for kind, reference in sorted(refs):
            lock_read(db, "registry", kind, reference)
            row = db.execute(
                "SELECT state FROM agent_registry WHERE kind=%s AND ref=%s",
                (kind, reference),
            ).fetchone()
            require(
                row is not None and row["state"] == "PUBLISHED",
                "CONFIG_DISABLED",
                "Registry version unavailable",
            )

    def create(self, identity, actor, experiment_id, ref, bundle, checkpoint):
        manifest = bundle["config"]["manifest"]
        with self.connect() as db:
            self._active(db, bundle, ref)
            exp, _ = self._access(db, actor, experiment_id, manifest["scoped_instruments"])
            require(
                exp["revision"] == checkpoint["snapshot"]["snapshot_version"],
                "SNAPSHOT_STALE",
                "Snapshot changed before run creation",
            )
            if checkpoint.get("external_refs"):
                from alap.adapters.postgres.resources import check_references

                check_references(
                    db,
                    {
                        "actor_id": actor,
                        "experiment_id": experiment_id,
                        "definition_ref": ref,
                        "bundle": bundle,
                    },
                    checkpoint,
                )
            db.execute(
                """INSERT INTO agent_runs(id,actor_id,experiment_id,definition_ref,bundle,
              bundle_hash,checkpoint,deadline_at) VALUES (%s,%s,%s,%s,%s,%s,%s,
              clock_timestamp()+%s)""",
                (
                    identity,
                    actor,
                    experiment_id,
                    ref,
                    Jsonb(bundle),
                    digest(bundle),
                    Jsonb(checkpoint),
                    timedelta(seconds=manifest["max_runtime_seconds"]),
                ),
            )
        return self.load(actor, identity)

    def load(self, actor, identity):
        with self.connect() as db:
            row = db.execute(
                "SELECT *, clock_timestamp() AS now FROM agent_runs WHERE id=%s", (identity,)
            ).fetchone()
            require(row is not None and row["actor_id"] == actor, "FORBIDDEN", "Run owner required")
            self._access(
                db,
                actor,
                row["experiment_id"],
                row["bundle"]["config"]["manifest"]["scoped_instruments"],
            )
            require(
                digest(row["bundle"]) == row["bundle_hash"], "REGISTRY_CORRUPT", "Bundle mismatch"
            )
            if row["checkpoint"].get("external_refs"):
                from alap.adapters.postgres.resources import check_references

                check_references(db, row, row["checkpoint"])
            return row

    @contextmanager
    def exclusive(self, identity):
        # Session advisory lock survives short transactions, but not a crashed process.
        with self.connect(autocommit=True) as db:
            locked = db.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s,7)) AS locked", (identity,)
            ).fetchone()["locked"]
            require(locked, "RUN_BUSY", "Another worker owns this Agent run")
            token = self._owner.set((identity, db))
            try:
                yield
            finally:
                self._owner.reset(token)
                # Closing this dedicated session releases its lock, including on errors.

    @contextmanager
    def _commit_connection(self, identity):
        owner = self._owner.get()
        if owner is None:
            with self.connect() as db:
                yield db
        else:
            require(owner[0] == identity, "RUN_BUSY", "Different Agent run owns this session")
            # Use the lock session itself: a dead owner cannot reconnect to commit.
            with owner[1].transaction():
                yield owner[1]

    def authorize_worker(self, actor):
        with self.connect() as db:
            principal = db.execute("SELECT * FROM principals WHERE id=%s", (actor,)).fetchone()
            require(
                principal is not None
                and principal["disabled_at"] is None
                and principal["kind"] == "service"
                and principal["issuer"] == "alap-agents",
                "FORBIDDEN",
                "Explicit Agent worker identity required",
            )

    def worker_candidates(self, actor, experiments, *, after="", limit=20):
        require(type(limit) is int and 1 <= limit <= 100, "INVALID_LIMIT", "Batch size 1..100")
        self.authorize_worker(actor)
        with self.connect() as db:
            return db.execute(
                """SELECT id,actor_id FROM agent_runs WHERE experiment_id=ANY(%s)
                AND checkpoint->>'status' IN ('READY','RUNNING') AND id>%s
                ORDER BY id LIMIT %s""",
                (list(experiments), after, limit),
            ).fetchall()

    def commit(self, run, checkpoint, event, *, invocations=(), proposals=(), check_snapshot=False):
        with self._commit_connection(run["id"]) as db:
            manifest = run["bundle"]["config"]["manifest"]
            exp, membership = self._access(
                db,
                run["actor_id"],
                run["experiment_id"],
                manifest["scoped_instruments"],
                proposal=bool(proposals),
            )
            if check_snapshot or event["type"] == "model_reserved":
                self._active(db, run["bundle"], run["definition_ref"])
            if check_snapshot or event["type"] == "model_reserved":
                now = db.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
                require(now < run["deadline_at"], "RUNTIME_BUDGET", "Agent deadline exceeded")
            if check_snapshot:
                require(
                    exp["revision"] == checkpoint["snapshot"]["snapshot_version"],
                    "SNAPSHOT_STALE",
                    "Proposal snapshot is no longer current",
                )
            for proposal in proposals:
                require(
                    proposal["risk_level"] in membership["scope"].get("risk_levels", []),
                    "FORBIDDEN",
                    "Proposal risk exceeds membership",
                )
            if checkpoint.get("external_refs"):
                from alap.adapters.postgres.resources import check_references

                check_references(db, run, checkpoint)
            changed = db.execute(
                """UPDATE agent_runs SET checkpoint=%s,revision=revision+1
              WHERE id=%s AND revision=%s""",
                (Jsonb(checkpoint), run["id"], run["revision"]),
            ).rowcount
            require(changed == 1, "STATE_CONFLICT", "Stale Agent checkpoint")
            db.execute(
                "INSERT INTO agent_trace(run_id,seq,event) VALUES (%s,%s,%s)",
                (run["id"], run["revision"] + 1, Jsonb(event)),
            )
            for call in invocations:
                db.execute(
                    """INSERT INTO agent_tool_invocations
                  (run_id,call_id,tool_ref,input_hash,result,outcome) VALUES (%s,%s,%s,%s,%s,%s)""",
                    (
                        run["id"],
                        call["id"],
                        call["tool_ref"],
                        call["input_hash"],
                        Jsonb(call["result"]),
                        call["outcome"],
                    ),
                )
            for proposal in proposals:
                db.execute(
                    """INSERT INTO agent_proposals(id,run_id,call_id,proposal,content_hash)
                  VALUES (%s,%s,%s,%s,%s)""",
                    (
                        proposal["proposal_id"],
                        run["id"],
                        proposal["proposal_id"],
                        Jsonb(proposal),
                        digest(proposal),
                    ),
                )
                inserted = db.execute(
                    """INSERT INTO proposal_business_keys
                  (experiment_id,fingerprint,proposal_id) SELECT %s,
                  encode(sha256(convert_to((%s::jsonb-
                    ARRAY['proposal_id','source_agent_run_id','reason'])::text,'UTF8')),'hex'),%s
                  ON CONFLICT DO NOTHING""",
                    (run["experiment_id"], Jsonb(proposal), proposal["proposal_id"]),
                ).rowcount
                require(inserted == 1, "PROPOSAL_DUPLICATE", "Equivalent proposal already recorded")
        return self.load(run["actor_id"], run["id"])
