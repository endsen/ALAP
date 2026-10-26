"""Private persistent simulation supervision store.

Optional Gateway/Engine adapters supply authenticated command heartbeats and maintenance
reviews. Direct Python access remains a trusted local simulation/maintenance boundary.
"""

import fcntl
import json
import math
import sqlite3
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from alap.domain.edge_policy import SimulationLossPolicy
from alap.domain.rules import DomainError


class SimulationEdgeStore:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def snapshot(self):
        with self.transaction() as db:
            state = dict(db.execute("SELECT * FROM edge_state WHERE id=1").fetchone())
            state["outputs"] = dict(db.execute("SELECT device,value FROM edge_outputs"))
            state["events"] = [
                dict(r) for r in db.execute("SELECT * FROM edge_events ORDER BY seq")
            ]
            return state

    @staticmethod
    def _event(db, kind, generation, detail):
        db.execute(
            "INSERT INTO edge_events(kind,generation,detail,recorded_at) VALUES (?,?,?,?)",
            (kind, generation, json.dumps(detail, sort_keys=True), datetime.now(UTC).isoformat()),
        )

    @classmethod
    def _trip(cls, db, state, reason):
        if state["mode"] == "TRIPPED":
            return
        incident = str(uuid4())
        before = dict(db.execute("SELECT device,value FROM edge_outputs"))
        db.execute("UPDATE edge_outputs SET value=0 WHERE device='sim-smu'")
        db.execute(
            "UPDATE edge_state SET mode='TRIPPED',incident=?,deadline=NULL WHERE id=1", (incident,)
        )
        cls._event(
            db,
            "loss_latched",
            state["generation"],
            {
                "incident": incident,
                "reason": reason,
                "policy": json.loads(state["policy"]),
                "before": before,
                "actions": {"sim-smu": "zero_output", "sim-temp": "hold", "sim-magnet": "hold"},
            },
        )

    @classmethod
    def _expire(cls, db, state, now):
        if now < state["last_scan"]:
            cls._trip(db, state, "clock_discontinuity")
            return True
        if now - state["last_scan"] >= json.loads(state["policy"])["timeout_s"]:
            cls._trip(db, state, "monitor_unavailable")
            return True
        binding = db.execute(
            "SELECT deadline_utc FROM edge_command WHERE id=1 AND running=1"
        ).fetchone()
        if binding and datetime.now(UTC) >= datetime.fromisoformat(binding[0]):
            cls._trip(db, state, "command_deadline")
            return True
        if state["mode"] == "ARMED" and now >= state["deadline"]:
            cls._trip(db, state, "heartbeat_expired")
            return True
        return False

    def heartbeat(self, generation, sequence, *, command_id=None, epoch=None):
        rejected = False
        with self.transaction() as db:
            state = db.execute("SELECT * FROM edge_state WHERE id=1").fetchone()
            now = time.monotonic()
            if command_id is not None:
                binding = db.execute(
                    "SELECT * FROM edge_command WHERE id=1 AND running=1"
                ).fetchone()
                if not binding or binding["command_id"] != command_id or binding["epoch"] != epoch:
                    raise DomainError("EDGE_HEARTBEAT_INVALID", "Active command and epoch required")
            if (
                generation != state["generation"]
                or type(sequence) is not int
                or not 0 <= sequence <= 2**63 - 1
                or sequence <= state["sequence"]
            ):
                raise DomainError(
                    "EDGE_HEARTBEAT_INVALID", "Fresh generation and increasing sequence required"
                )
            rejected = self._expire(db, state, now) or state["mode"] == "TRIPPED"
            if not rejected:
                policy = json.loads(state["policy"])
                db.execute(
                    "UPDATE edge_state SET mode='ARMED',sequence=?,deadline=? WHERE id=1",
                    (sequence, now + policy["timeout_s"]),
                )
                if state["mode"] == "WAITING":
                    self._event(db, "armed", generation, {"sequence": sequence})
        if rejected:
            raise DomainError("EDGE_LATCHED", "A heartbeat cannot clear a loss latch")

    def write_output(self, generation, device, value):
        limits = {"sim-smu": (-0.001, 0.001), "sim-temp": (290, 300), "sim-magnet": (-0.01, 0.01)}
        if (
            device not in limits
            or type(value) not in (int, float)
            or not math.isfinite(value)
            or not limits[device][0] <= value <= limits[device][1]
        ):
            raise DomainError("EDGE_OUTPUT_INVALID", "Only bounded simulation values accepted")
        denied = False
        with self.transaction() as db:
            state = db.execute("SELECT * FROM edge_state WHERE id=1").fetchone()
            expired = self._expire(db, state, time.monotonic())
            denied = expired or state["mode"] != "ARMED" or generation != state["generation"]
            if not denied:
                db.execute("UPDATE edge_outputs SET value=? WHERE device=?", (value, device))
                self._event(db, "output", generation, {"device": device, "value": value})
        if denied:
            raise DomainError(
                "EDGE_NOT_ARMED", "Fresh supervision required before simulated output"
            )

    def acknowledge(self, generation, incident, *, operator, reason, review=None):
        if (
            not isinstance(operator, str)
            or not operator.strip()
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise DomainError("EDGE_ACK_INVALID", "Local maintenance operator and reason required")
        with self.transaction() as db:
            state = db.execute("SELECT * FROM edge_state WHERE id=1").fetchone()
            if (
                state["mode"] != "TRIPPED"
                or generation != state["generation"]
                or incident != state["incident"]
            ):
                raise DomainError(
                    "EDGE_ACK_INVALID", "Exact current incident and generation required"
                )
            if db.execute("SELECT 1 FROM edge_command WHERE id=1 AND running=1").fetchone():
                raise DomainError(
                    "EDGE_BUSY", "Reconcile the interrupted command before acknowledgement"
                )
            if review is not None:
                if datetime.now(UTC) >= datetime.fromisoformat(review["expires_at"]):
                    raise DomainError("EDGE_REVIEW_EXPIRED", "Maintenance authorization expired")
                now = time.monotonic()
                policy = json.loads(state["policy"])
                outputs = dict(db.execute("SELECT device,value FROM edge_outputs"))
                if not 0 <= now - state["last_scan"] < policy["timeout_s"]:
                    raise DomainError(
                        "EDGE_MONITOR_STALE", "Live monitor required for acknowledgement"
                    )
                if (
                    outputs.get("sim-smu") != 0
                    or outputs != review["expected_outputs"]
                    or policy["version"] != review["policy_version"]
                ):
                    raise DomainError(
                        "EDGE_REVIEW_STALE", "Exact reviewed outputs and policy required"
                    )
            db.execute("DELETE FROM edge_command")
            next_generation = str(uuid4())
            db.execute(
                "UPDATE edge_state SET mode='WAITING',generation=?,sequence=-1,"
                "deadline=NULL,incident=NULL WHERE id=1",
                (next_generation,),
            )
            self._event(
                db,
                "acknowledged",
                next_generation,
                {
                    "incident": incident,
                    "operator": operator,
                    "reason": reason,
                    **({"review": review} if review is not None else {}),
                },
            )
            return next_generation


class SimulationEdgeMonitor(SimulationEdgeStore):
    def __init__(self, path, policy: SimulationLossPolicy):
        super().__init__(path)
        self._owner = open(str(path) + ".monitor.owner", "a+b")
        try:
            try:
                fcntl.flock(self._owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DomainError("EDGE_ALREADY_RUNNING", "One monitor per state file") from None
            with sqlite3.connect(path) as db:
                tables = {
                    row[0]
                    for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if tables - {
                    "edge_state",
                    "edge_outputs",
                    "edge_events",
                    "edge_command",
                    "sqlite_sequence",
                }:
                    raise DomainError(
                        "EDGE_STORE_INVALID", "Dedicated simulation monitor file required"
                    )
                db.execute("PRAGMA journal_mode=WAL")
                db.executescript("""
                CREATE TABLE IF NOT EXISTS edge_state(id INTEGER PRIMARY KEY CHECK(id=1),
                  mode TEXT, generation TEXT, sequence INTEGER, deadline REAL,
                  incident TEXT, policy TEXT, last_scan REAL);
                CREATE TABLE IF NOT EXISTS edge_command(id INTEGER PRIMARY KEY CHECK(id=1),
                  command_id TEXT,epoch TEXT,generation TEXT,deadline_utc TEXT,running INTEGER);
                CREATE TABLE IF NOT EXISTS edge_outputs(
                  device TEXT PRIMARY KEY,value REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS edge_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,
                  kind TEXT NOT NULL,generation TEXT NOT NULL,detail TEXT NOT NULL,
                  recorded_at TEXT NOT NULL);
                """)
            with self.transaction() as db:
                encoded = json.dumps(policy.document(), sort_keys=True)
                old = db.execute("SELECT * FROM edge_state WHERE id=1").fetchone()
                if old and old["policy"] != encoded:
                    raise DomainError(
                        "EDGE_POLICY_MISMATCH", "Existing policy cannot be silently replaced"
                    )
                if not old:
                    db.execute(
                        "INSERT INTO edge_state VALUES(1,'WAITING',?,-1,NULL,NULL,?,?)",
                        (str(uuid4()), encoded, time.monotonic()),
                    )
                    db.executemany(
                        "INSERT INTO edge_outputs VALUES(?,?)",
                        [("sim-smu", 0), ("sim-temp", 295), ("sim-magnet", 0)],
                    )
                else:
                    # A monitor restart is a supervision gap, never proof of a live controller.
                    self._trip(db, old, "monitor_restarted")
                    db.execute(
                        "UPDATE edge_state SET generation=?,sequence=-1,deadline=NULL,"
                        "last_scan=? WHERE id=1",
                        (str(uuid4()), time.monotonic()),
                    )
        except BaseException:
            self._owner.close()
            raise

    def scan(self):
        if self._owner.closed:
            raise DomainError("EDGE_MONITOR_CLOSED", "Closed monitors cannot resume")
        with self.transaction() as db:
            state = db.execute("SELECT * FROM edge_state WHERE id=1").fetchone()
            now = time.monotonic()
            # The monitor itself may have been suspended: expiry is latched before
            # refreshing its own progress timestamp.
            self._expire(db, state, now)
            db.execute("UPDATE edge_state SET last_scan=? WHERE id=1", (now,))

    def close(self):
        if not self._owner.closed:
            try:
                with self.transaction() as db:
                    state = db.execute("SELECT * FROM edge_state WHERE id=1").fetchone()
                    if state["mode"] == "ARMED":
                        self._trip(db, state, "monitor_stopped")
            finally:
                self._owner.close()
