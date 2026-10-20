"""Session-bound engine ownership. Loss is terminal; reacquisition needs a new owner.

The same dedicated connection holds the advisory lock and performs engine
transactions. This is not compatible with transaction-mode connection pooling.
Gateway epoch/fencing remain necessary across the database/network boundary.
"""

import hashlib
from contextlib import contextmanager
from threading import RLock

import psycopg
from psycopg.rows import dict_row

from alap.adapters.postgres.repository import PostgresRepository
from alap.domain.rules import DomainError


class PostgresEngineOwner:
    def __init__(self, dsn):
        self.dsn = dsn
        self._connection = None
        self._used = False
        self._active = False
        self._mutex = RLock()

    def __enter__(self):
        with self._mutex:
            if self._used:
                raise DomainError("ENGINE_OWNER_CLOSED", "Ownership objects cannot reconnect")
            self._used = True
            try:
                self._connection = psycopg.connect(
                    self.dsn, autocommit=True, row_factory=dict_row, connect_timeout=5
                )
                self._connection.execute("SET statement_timeout = '5s'")
                schema = self._connection.execute("SELECT current_schema() AS name").fetchone()[
                    "name"
                ]
                if schema is None:
                    raise DomainError("ENGINE_SCHEMA_REQUIRED", "Explicit migrated schema required")
                raw = hashlib.sha256((schema + ":alap-engine-owner-v1").encode()).digest()[:8]
                self._key = int.from_bytes(raw, signed=True)
                locked = self._connection.execute(
                    "SELECT pg_try_advisory_lock(%s) AS acquired", (self._key,)
                ).fetchone()["acquired"]
                if not locked:
                    raise DomainError("ENGINE_ALREADY_RUNNING", "Another engine owns this schema")
                self._active = True
                return self
            except BaseException:
                self.close()
                raise

    def check(self):
        with self._mutex:
            if not self._active:
                raise DomainError("ENGINE_OWNERSHIP_LOST", "Engine is closed or lost ownership")
            try:
                # Do not call pg_try_advisory_lock again: session locks are reentrant.
                locked = self._connection.execute(
                    """SELECT EXISTS (
                        SELECT 1 FROM pg_locks WHERE locktype='advisory'
                        AND pid=pg_backend_pid() AND granted
                        AND classid::bigint=%s AND objid::bigint=%s AND objsubid=1
                    ) AS owned""",
                    ((self._key >> 32) & 0xFFFFFFFF, self._key & 0xFFFFFFFF),
                ).fetchone()["owned"]
            except psycopg.Error as exc:
                self.close()
                raise DomainError(
                    "ENGINE_OWNERSHIP_LOST", "Database ownership unavailable"
                ) from exc
            if not locked:
                self.close()
                raise DomainError("ENGINE_OWNERSHIP_LOST", "Database ownership was released")

    @contextmanager
    def transaction(self):
        with self._mutex:
            self.check()
            try:
                with self._connection.transaction():
                    self._connection.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                    self._connection.execute("SET LOCAL lock_timeout = '5s'")
                    self._connection.execute("SET LOCAL statement_timeout = '30s'")
                    yield PostgresRepository(self._connection)
            except psycopg.OperationalError as exc:
                self.close()
                raise DomainError(
                    "ENGINE_OWNERSHIP_LOST", "Database transaction unavailable"
                ) from exc

    def close(self):
        with self._mutex:
            self._active = False
            if self._connection is not None:
                self._connection.close()

    def __exit__(self, *args):
        self.close()


class OwnedGateway:
    """Check central ownership before every outbound call; never retry on loss.

    A loss during IO remains possible. Epoch/fencing at the remote Gateway and
    recovery reconciliation, not this local check, protect that race.
    """

    def __init__(self, owner, gateway):
        self.owner, self.gateway = owner, gateway

    def _call(self, method, *args):
        self.owner.check()
        return getattr(self.gateway, method)(*args)

    def accept(self, signed):
        return self._call("accept", signed)

    def query(self, command_id):
        return self._call("query", command_id)

    def confirm_dataset(self, signed):
        return self._call("confirm_dataset", signed)

    def stop(self, signed):
        return self._call("stop", signed)

    def recover_command(self, signed):
        return self._call("recover_command", signed)

    def telemetry(self, condition):
        return self._call("telemetry", condition)

    def challenge(self):
        return self._call("challenge")

    def bind_epoch(self, signed):
        return self._call("bind_epoch", signed)
