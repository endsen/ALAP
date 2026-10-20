"""Short transactions with explicit row locks; no network side effects inside a unit of work."""

from contextlib import contextmanager
from datetime import timedelta

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from alap.adapters.postgres.read_locks import lock_read
from alap.domain.rules import DomainError

TABLES = frozenset(
    {
        "device_snapshots",
        "datasets",
        "provenance_edges",
        "tasks",
        "leases",
        "instruments",
        "gateways",
        "resource_controls",
        "command_ledger",
        "command_deliveries",
        "stop_requests",
        "gateway_receipts",
        "control_generation",
        "principals",
        "samples",
        "experiments",
        "plan_revisions",
        "approvals",
        "runs",
        "evidence_records",
        "transition_audit",
        "outbox_events",
    }
)
JSON_FIELDS = frozenset(
    {
        "result_json",
        "manifest_json",
        "definition",
        "raw_receipt",
        "metadata",
        "plan_json",
        "scope_json",
        "task_identities",
        "source",
        "evidence_ids",
        "effects",
        "payload",
    }
)


def table_name(name):
    if name not in TABLES:
        raise ValueError("Unknown repository table")
    return sql.Identifier(name)


class PostgresRepository:
    def __init__(self, connection, *, readonly=False):
        self.connection = connection
        self.readonly = readonly

    def now(self):
        return self.connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]

    def get(self, table, identity, *, lock=False):
        suffix = sql.SQL(" FOR UPDATE") if lock else sql.SQL("")
        if table == "principals" and not self.readonly:
            lock_read(self.connection, "principal", identity)
            suffix = sql.SQL("")
        row = self.connection.execute(
            sql.SQL("SELECT * FROM {} WHERE id = %s").format(table_name(table)) + suffix,
            (identity,),
        ).fetchone()
        if row is None:
            raise DomainError("NOT_FOUND", "Object does not exist")
        return row

    def insert(self, table, values):
        columns = list(values)
        self.connection.execute(
            sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                table_name(table),
                sql.SQL(",").join(map(sql.Identifier, columns)),
                sql.SQL(",").join(sql.Placeholder() for _ in columns),
            ),
            [Jsonb(values[k]) if k in JSON_FIELDS else values[k] for k in columns],
        )

    def update(self, table, identity, values):
        self.connection.execute(
            sql.SQL("UPDATE {} SET {} WHERE id = %s").format(
                table_name(table),
                sql.SQL(",").join(sql.SQL("{} = %s").format(sql.Identifier(k)) for k in values),
            ),
            [Jsonb(v) if k in JSON_FIELDS else v for k, v in values.items()] + [identity],
        )

    def add_owner(self, experiment, actor):
        self.connection.execute(
            """INSERT INTO experiment_memberships (experiment_id,actor_id,role,scope)
            VALUES (%s,%s,'owner',%s)""",
            (experiment, actor, Jsonb({"resources": [], "risk_levels": []})),
        )

    def membership(self, experiment, actor):
        if not self.readonly:
            lock_read(self.connection, "membership", experiment, actor)
        return self.connection.execute(
            "SELECT * FROM experiment_memberships WHERE experiment_id=%s AND actor_id=%s",
            (experiment, actor),
        ).fetchone()

    def plans(self, experiment):
        return self.connection.execute(
            "SELECT * FROM plan_revisions WHERE experiment_id=%s ORDER BY revision DESC",
            (experiment,),
        ).fetchall()

    def approvals(self, experiment):
        return self.connection.execute(
            "SELECT * FROM approvals WHERE experiment_id=%s ORDER BY id"
            + ("" if self.readonly else " FOR UPDATE"),
            (experiment,),
        ).fetchall()

    def runs(self, experiment):
        return self.connection.execute(
            "SELECT * FROM runs WHERE experiment_id=%s ORDER BY id"
            + ("" if self.readonly else " FOR UPDATE"),
            (experiment,),
        ).fetchall()

    def events(self, experiment):
        return self.connection.execute(
            "SELECT * FROM outbox_events WHERE experiment_id=%s ORDER BY experiment_seq",
            (experiment,),
        ).fetchall()

    def claim_request(self, actor, operation, scope, key, request_hash):
        inserted = self.connection.execute(
            """INSERT INTO idempotency_records
            (actor_id,operation,scope_id,key,request_hash,status,expires_at)
            VALUES (%s,%s,%s,%s,%s,'PENDING',%s) ON CONFLICT DO NOTHING RETURNING key""",
            (actor, operation, scope, key, request_hash, self.now() + timedelta(days=30)),
        ).fetchone()
        if inserted:
            return None
        row = self.connection.execute(
            """SELECT * FROM idempotency_records
            WHERE actor_id=%s AND operation=%s AND scope_id=%s AND key=%s""",
            (actor, operation, scope, key),
        ).fetchone()
        if row["request_hash"] != request_hash:
            raise DomainError("IDEMPOTENCY_CONFLICT", "Key already used for a different request")
        if row["status"] != "COMPLETE":
            raise DomainError("IDEMPOTENCY_INCOMPLETE", "Uncommitted request must not be replayed")
        # Expiry is retention eligibility, never authorization to duplicate an old side effect.
        return row["response_json"]

    def complete_request(self, actor, operation, scope, key, response):
        self.connection.execute(
            """UPDATE idempotency_records SET status='COMPLETE',response_json=%s
            WHERE actor_id=%s AND operation=%s AND scope_id=%s AND key=%s""",
            (Jsonb(response), actor, operation, scope, key),
        )

    def find(self, table, filters, *, lock=False):
        query = sql.SQL("SELECT * FROM {} WHERE {} ORDER BY id").format(
            table_name(table),
            (
                sql.SQL(" AND ").join(
                    sql.SQL("{}=%s").format(sql.Identifier(key)) for key in filters
                )
                if filters
                else sql.SQL("TRUE")
            ),
        )
        if lock:
            query += sql.SQL(" FOR UPDATE")
        return self.connection.execute(query, list(filters.values())).fetchall()

    def generation(self, *, exclusive=False):
        return self.connection.execute(
            "SELECT * FROM control_generation WHERE id='current' FOR "
            + ("UPDATE" if exclusive else "SHARE")
        ).fetchone()

    def claim(self, resource):
        return self.connection.execute(
            "SELECT * FROM resource_claims WHERE resource_id=%s", (resource,)
        ).fetchone()

    def add_claim(self, lease):
        self.connection.execute(
            """INSERT INTO resource_claims(resource_id,lease_id,holder_run_id,epoch,token)
            VALUES (%s,%s,%s,%s,%s)""",
            (
                lease["resource_id"],
                lease["id"],
                lease["holder_run_id"],
                lease["epoch"],
                lease["token"],
            ),
        )

    def remove_claim(self, lease):
        self.connection.execute(
            "DELETE FROM resource_claims WHERE resource_id=%s AND lease_id=%s",
            (lease["resource_id"], lease["id"]),
        )

    def dependency(self, run, task, parent):
        self.connection.execute(
            "INSERT INTO task_dependencies(run_id,task_id,depends_on_id) VALUES (%s,%s,%s)",
            (run, task, parent),
        )

    def claim_events(self, token, limit):
        rows = self.connection.execute(
            """SELECT o.* FROM outbox_events o LEFT JOIN event_delivery_claims c USING(event_id)
            WHERE o.published_at IS NULL AND (c.event_id IS NULL OR c.expires_at<=clock_timestamp())
            ORDER BY o.experiment_id,o.experiment_seq LIMIT %s FOR UPDATE OF o SKIP LOCKED""",
            (limit,),
        ).fetchall()
        for row in rows:
            self.connection.execute(
                """INSERT INTO event_delivery_claims
                VALUES(%s,%s,clock_timestamp()+interval '30 seconds')
                ON CONFLICT(event_id) DO UPDATE
                SET token=EXCLUDED.token,expires_at=EXCLUDED.expires_at""",
                (row["event_id"], token),
            )
        return rows

    def mark_published(self, event_id, token):
        row = self.connection.execute(
            "SELECT published_at FROM outbox_events WHERE event_id=%s FOR UPDATE", (event_id,)
        ).fetchone()
        claim = self.connection.execute(
            "SELECT token FROM event_delivery_claims WHERE event_id=%s", (event_id,)
        ).fetchone()
        if row is None or row["published_at"] is not None or not claim or claim["token"] != token:
            return False
        self.connection.execute(
            "UPDATE outbox_events SET published_at=clock_timestamp() WHERE event_id=%s", (event_id,)
        )
        return True

    def event(self, identity):
        row = self.connection.execute(
            "SELECT * FROM outbox_events WHERE event_id=%s", (identity,)
        ).fetchone()
        if row is None:
            raise DomainError("EVENT_CONFLICT", "Unknown authoritative event")
        return row

    def events_after(self, experiment, cursor, limit):
        return self.connection.execute(
            """SELECT * FROM outbox_events WHERE experiment_id=%s AND experiment_seq>%s
            ORDER BY experiment_seq LIMIT %s""",
            (experiment, cursor, limit),
        ).fetchall()

    def apply_event(self, consumer, row, payload_hash):
        inserted = self.connection.execute(
            """INSERT INTO consumer_inbox VALUES(%s,%s,%s,clock_timestamp())
            ON CONFLICT DO NOTHING RETURNING event_id""",
            (consumer, row["event_id"], payload_hash),
        ).fetchone()
        if not inserted:
            saved = self.connection.execute(
                "SELECT payload_hash FROM consumer_inbox WHERE consumer_id=%s AND event_id=%s",
                (consumer, row["event_id"]),
            ).fetchone()
            if saved["payload_hash"] != payload_hash:
                raise DomainError("EVENT_CONFLICT", "Inbox identity bound to another payload")
            return False
        self.connection.execute(
            """INSERT INTO event_projections VALUES(%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(consumer_id,experiment_id,aggregate_type,aggregate_id) DO UPDATE
            SET aggregate_seq=EXCLUDED.aggregate_seq,event_id=EXCLUDED.event_id,
            payload=EXCLUDED.payload
            WHERE event_projections.aggregate_seq<EXCLUDED.aggregate_seq""",
            (
                consumer,
                row["experiment_id"],
                row["aggregate_type"],
                row["aggregate_id"],
                row["aggregate_seq"],
                row["event_id"],
                Jsonb(row["payload"]),
            ),
        )
        return True


class PostgresUnitOfWork:
    def __init__(self, dsn):
        self.dsn = dsn

    @contextmanager
    def __call__(self):
        with psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=5) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            connection.execute("SET LOCAL lock_timeout = '10s'")
            connection.execute("SET LOCAL statement_timeout = '30s'")
            yield PostgresRepository(connection)

    @contextmanager
    def snapshot(self):
        with psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=5) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            yield PostgresRepository(connection, readonly=True)
