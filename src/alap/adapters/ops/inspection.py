"""Read-only maintenance observations. Unknown/unavailable signals are never reported as healthy."""

import shutil
import sqlite3
import tempfile
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from alap.adapters.storage.hdf5 import Hdf5Store


def metrics(dsn):
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=5) as db:
        db.execute("SET TRANSACTION READ ONLY")
        db.execute("SET LOCAL statement_timeout = '5s'")
        result = {"database_reachable": True}
        result["control"] = db.execute("SELECT mode FROM control_generation").fetchone()
        for table in ("runs", "tasks", "command_ledger", "datasets"):
            # Fixed local table names; never interpolate caller-supplied identifiers.
            result[table] = {
                r["state"]: r["n"]
                for r in db.execute(
                    f"SELECT state,count(*) AS n FROM {table} GROUP BY state"
                ).fetchall()
            }
        result["outbox"] = db.execute(
            "SELECT count(*) AS pending, "
            "extract(epoch FROM clock_timestamp()-min(occurred_at))::float AS oldest_age_s "
            "FROM outbox_events WHERE published_at IS NULL"
        ).fetchone()
        result["agent_runs"] = {
            r["status"]: r["n"]
            for r in db.execute(
                "SELECT checkpoint->>'status' AS status,count(*) AS n FROM agent_runs GROUP BY 1"
            ).fetchall()
        }
        result["stop_requests_pending"] = db.execute(
            "SELECT count(*) AS n FROM stop_requests WHERE state<>'CONFIRMED'"
        ).fetchone()["n"]
        result["alerts"] = []
        if result["control"]["mode"] != "ACTIVE":
            result["alerts"].append("RECOVERY_GATE_CLOSED")
        if any(result["command_ledger"].get(s, 0) for s in ("UNKNOWN", "NEEDS_RECONCILIATION")):
            result["alerts"].append("COMMAND_RECONCILIATION_REQUIRED")
        if result["datasets"].get("CORRUPT", 0):
            result["alerts"].append("DATASET_CORRUPT")
        if (result["outbox"]["oldest_age_s"] or 0) > 60:
            result["alerts"].append("OUTBOX_OLDER_THAN_60S")
        return result


def audit(dsn, artifacts, gateway):
    """Audit a quiescent Gateway snapshot; caller must stop its writer first."""
    store = Hdf5Store(artifacts)
    verified = 0
    with psycopg.connect(dsn, row_factory=dict_row) as db:
        db.execute("SET TRANSACTION READ ONLY")
        for row in db.execute("SELECT * FROM datasets WHERE state='COMMITTED'").fetchall():
            manifest = row["manifest_json"]
            if (
                row["storage_key"] != store.key(row["id"])
                or manifest["checksum_sha256"] != row["checksum"]
            ):
                raise ValueError("Committed dataset identity/checksum mismatch")
            store.read(row["storage_key"], row["checksum"])
            edge = db.execute(
                "SELECT command_id FROM provenance_edges WHERE dataset_id=%s", (row["id"],)
            ).fetchone()
            if not edge or edge["command_id"] != row["command_id"]:
                raise ValueError("Committed dataset provenance missing")
            verified += 1
    databases = {}
    for name in ("journal.sqlite", "physical.sqlite"):
        path = Path(gateway) / name
        if not path.is_file() or path.is_symlink():
            raise ValueError("Gateway state file missing or invalid")
        # WAL-mode SQLite may need to create an SHM file even for a read-only
        # connection. Inspect a private copy of the stopped writer's DB/WAL,
        # never grant the maintenance container write access to the real journal.
        with tempfile.TemporaryDirectory(prefix="alap-sqlite-audit-") as directory:
            copied = Path(directory) / name
            shutil.copyfile(path, copied)
            wal = path.with_name(name + "-wal")
            if wal.exists():
                if not wal.is_file() or wal.is_symlink():
                    raise ValueError("Gateway WAL file invalid")
                shutil.copyfile(wal, copied.with_name(name + "-wal"))
            with sqlite3.connect(copied.as_uri() + "?mode=ro", uri=True) as db:
                if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise ValueError("Gateway SQLite integrity check failed")
            databases[name] = "ok"
    return {"committed_datasets_verified": verified, "gateway_integrity": databases}
