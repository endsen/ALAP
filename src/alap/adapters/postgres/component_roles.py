"""Explicit database capabilities; new tables receive no component privileges by default."""

from psycopg import sql

CORE = set(
    "principals samples experiments experiment_memberships plan_revisions approvals runs "
    "idempotency_records evidence_records transition_audit outbox_events gateways instruments "
    "control_generation resource_controls leases resource_claims tasks task_dependencies "
    "command_ledger command_deliveries stop_requests gateway_receipts device_snapshots "
    "datasets provenance_edges".split()
)
AGENT = set(
    "agent_registry agent_runs agent_trace agent_proposals agent_tool_invocations "
    "knowledge_versions knowledge_grants mcp_connections mcp_tools mcp_grants mcp_calls "
    "dataset_analyses collaboration_claims proposal_business_keys".split()
)
ADMIN = set(
    "platform_roles api_tokens api_credentials platform_configs api_requests api_audit".split()
)
EVENTS = set("event_delivery_claims consumer_inbox event_projections".split())
ALL = CORE | AGENT | ADMIN | EVENTS | {"alembic_version"}

# API is the trusted management/control backend, not a browser database account.
# It may update existing command states for cancel/reconcile, but cannot insert commands.
API_INSERT = (CORE | AGENT | ADMIN) - {
    "command_ledger",
    "command_deliveries",
    "task_dependencies",
    "gateways",
    "instruments",
    "control_generation",
    "resource_controls",
    "gateway_receipts",
    "device_snapshots",
    "datasets",
    "provenance_edges",
    "resource_claims",
    "leases",
    "tasks",
}
ENGINE_WRITE = CORE - {
    "principals",
    "samples",
    "experiment_memberships",
    "plan_revisions",
    "approvals",
    "gateways",
    "instruments",
}
AGENT_WRITE = {
    "agent_runs",
    "agent_trace",
    "agent_proposals",
    "agent_tool_invocations",
    "mcp_calls",
    "dataset_analyses",
    "collaboration_claims",
    "proposal_business_keys",
}
PERMISSIONS = {
    "api": {
        "SELECT": ALL,
        "INSERT": API_INSERT,
        "UPDATE": (CORE | AGENT | ADMIN) - {"gateways", "instruments", "device_snapshots"},
        "DELETE": {"resource_claims"},
    },
    "engine": {
        "SELECT": CORE | {"alembic_version"},
        "INSERT": ENGINE_WRITE,
        # FOR UPDATE on immutable plan/approval rows is required by the current engine.
        # Their immutable-field triggers still apply; no INSERT grant permits new approvals.
        "UPDATE": ENGINE_WRITE | {"approvals", "plan_revisions"},
        "DELETE": {"resource_claims"},
    },
    "agent": {
        "SELECT": AGENT
        | {
            "principals",
            "experiments",
            "experiment_memberships",
            "approvals",
            "command_ledger",
            "resource_controls",
            "datasets",
            "outbox_events",
            "platform_configs",
            "api_credentials",
            "alembic_version",
        },
        "INSERT": AGENT_WRITE,
        "UPDATE": {"agent_runs", "mcp_calls", "collaboration_claims"},
    },
    "outbox": {
        "SELECT": {
            "principals",
            "outbox_events",
            "event_delivery_claims",
            "consumer_inbox",
            "event_projections",
            "alembic_version",
        },
        "INSERT": EVENTS,
        "UPDATE": EVENTS,
    },
}


def apply_components(db, manifest):
    """Run as schema owner in the same transaction as migration grants."""
    # PostgreSQL keeps column ACLs separately from table ACLs. Reset both so
    # reapplying this policy also removes stale column-specific write grants.
    columns = db.execute(
        "SELECT table_name, array_agg(column_name::text ORDER BY ordinal_position) "
        "FROM information_schema.columns WHERE table_schema='alap' GROUP BY table_name"
    ).fetchall()
    for component, operations in PERMISSIONS.items():
        role = sql.Identifier(manifest["database"] + "_" + component)
        db.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(manifest["database"]), role
            )
        )
        db.execute(sql.SQL("GRANT USAGE ON SCHEMA alap TO {}").format(role))
        # Reset table/sequence/function ACLs before applying the explicit allowlist.
        for kind in ("TABLES", "SEQUENCES", "FUNCTIONS"):
            db.execute(
                sql.SQL("REVOKE ALL ON ALL {} IN SCHEMA alap FROM {}").format(sql.SQL(kind), role)
            )
        for table, names in columns:
            db.execute(
                sql.SQL("REVOKE ALL ({}) ON {} FROM {}").format(
                    sql.SQL(",").join(map(sql.Identifier, names)),
                    sql.Identifier("alap", table),
                    role,
                )
            )
        for operation, tables in operations.items():
            db.execute(
                sql.SQL("GRANT {} ON {} TO {}").format(
                    sql.SQL(operation),
                    sql.SQL(",").join(sql.Identifier("alap", t) for t in sorted(tables)),
                    role,
                )
            )
        db.execute(
            sql.SQL(
                "GRANT EXECUTE ON FUNCTION alap.lock_read_record(text,text,text,text) TO {}"
            ).format(role)
        )
        if component in {"api", "agent"}:
            db.execute(
                sql.SQL(
                    "GRANT EXECUTE ON FUNCTION alap.refresh_mcp_discovery(text,jsonb) TO {}"
                ).format(role)
            )
        # Only API audit uses a generated identity sequence in the current schema.
        for row in db.execute(
            "SELECT sequence_name FROM information_schema.sequences WHERE sequence_schema='alap'"
        ).fetchall():
            if component == "api" and row[0].startswith("api_audit_"):
                db.execute(
                    sql.SQL("GRANT USAGE,SELECT ON SEQUENCE {} TO {}").format(
                        sql.Identifier("alap", row[0]), role
                    )
                )
        if component == "engine":
            db.execute(
                sql.SQL("GRANT UPDATE(epoch,reconciliation_ref) ON alap.gateways TO {}").format(
                    role
                )
            )
        if component == "outbox":
            db.execute(
                sql.SQL("GRANT UPDATE(published_at) ON alap.outbox_events TO {}").format(role)
            )
    legacy = sql.Identifier(manifest["runtime"])
    for kind in ("TABLES", "SEQUENCES", "FUNCTIONS"):
        db.execute(
            sql.SQL("REVOKE ALL ON ALL {} IN SCHEMA alap FROM {}").format(sql.SQL(kind), legacy)
        )
    db.execute(sql.SQL("REVOKE ALL ON SCHEMA alap FROM {}").format(legacy))
    db.execute(
        sql.SQL("REVOKE ALL ON DATABASE {} FROM {}").format(
            sql.Identifier(manifest["database"]), legacy
        )
    )
