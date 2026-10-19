"""Durable near-device single-writer journal. Crashes never cause implicit re-execution."""

import fcntl
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from threading import RLock
from uuid import uuid4

from jsonschema import Draft202012Validator

from alap.domain.rules import DomainError, freeze_revision
from alap.domain.stability import check_stable

TERMINAL = {"SUCCEEDED", "REJECTED_BEFORE_EXECUTE", "CANCELLED", "FAILED_CONFIRMED"}


def serialized(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._operation:
            return method(self, *args, **kwargs)

    return guarded


class Gateway:
    def __init__(
        self,
        identity,
        path,
        *,
        authenticator,
        catalog,
        simulator,
        skills,
        policy_versions,
        capability_versions,
    ):
        self._operation = RLock()
        self.identity, self.path = identity, path
        self._owner = open(str(path) + ".owner", "a+b")
        try:
            fcntl.flock(self._owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._owner.close()
            raise DomainError(
                "GATEWAY_ALREADY_RUNNING", "One executor process per journal"
            ) from None
        self.auth, self.catalog, self.simulator = authenticator, catalog, simulator
        self.skills, self.policies, self.capabilities = skills, policy_versions, capability_versions
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS config(
              id INTEGER PRIMARY KEY CHECK(id=1),epoch TEXT,nonce TEXT);
            INSERT OR IGNORE INTO config VALUES(1,NULL,NULL);
            CREATE TABLE IF NOT EXISTS fences(device TEXT PRIMARY KEY,token INTEGER,
              lease TEXT,run TEXT,plan_hash TEXT);
            CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY,device TEXT,payload_hash TEXT,
              package_hash TEXT,state TEXT,command TEXT,task TEXT,result TEXT);
            CREATE TABLE IF NOT EXISTS stop_results(
              id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, response TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS receipts(seq INTEGER PRIMARY KEY AUTOINCREMENT,
              command_id TEXT NOT NULL,body TEXT NOT NULL);
            """)
        with self.connect() as db:
            self._recoverable = {r["id"] for r in db.execute("SELECT id FROM commands")}
        # Opening a journal never dispatches anything.

    @serialized
    def close(self):
        if not self._owner.closed:
            fcntl.flock(self._owner.fileno(), fcntl.LOCK_UN)
            self._owner.close()

    @contextmanager
    def connect(self):
        if self._owner.closed:
            raise DomainError("GATEWAY_CLOSED", "Executor has relinquished journal ownership")
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    @serialized
    def challenge(self):
        with self.connect() as db:
            nonce = str(uuid4())
            db.execute("UPDATE config SET nonce=? WHERE id=1", (nonce,))
            states = [dict(r) for r in db.execute("SELECT id,state FROM commands")]
            tokens = {r["device"]: r["token"] for r in db.execute("SELECT * FROM fences")}
            return self.auth.seal(
                {
                    "gateway_id": self.identity,
                    "nonce": nonce,
                    "states": states,
                    "max_tokens": tokens,
                    "observed_at": self.simulator.clock.now().isoformat(),
                    "epoch": db.execute("SELECT epoch FROM config").fetchone()[0],
                }
            )

    @serialized
    def bind_epoch(self, signed):
        value = self.auth.open(signed)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            config = db.execute("SELECT * FROM config").fetchone()
            if (
                value.get("operation") != "bind_epoch"
                or value["gateway_id"] != self.identity
                or not config["nonce"]
                or value["nonce"] != config["nonce"]
            ):
                raise DomainError(
                    "HANDSHAKE_INVALID", "Fresh authenticated recovery challenge required"
                )
            busy = db.execute(
                "SELECT id FROM commands WHERE state NOT IN "
                "('SUCCEEDED','REJECTED_BEFORE_EXECUTE','CANCELLED','FAILED_CONFIRMED')"
            ).fetchone()
            if busy:
                raise DomainError(
                    "RECONCILIATION_REQUIRED", "Unresolved journal entries block epoch switch"
                )
            if config["epoch"] != value["epoch"]:
                db.execute("DELETE FROM fences")
            db.execute("UPDATE config SET epoch=?,nonce=NULL WHERE id=1", (value["epoch"],))
        return self.auth.seal(
            {
                "gateway_id": self.identity,
                "epoch": value["epoch"],
                "nonce": value["nonce"],
                "quiescent": True,
            }
        )

    @serialized
    def telemetry(self, request):
        conditions = request.get("conditions", [request])
        windows = self.simulator.windows(conditions)
        return self.auth.seal(
            {
                "gateway_id": self.identity,
                "windows": [
                    {"condition": condition, "samples": samples}
                    for condition, samples in zip(conditions, windows, strict=True)
                ],
            }
        )

    @serialized
    def recover_command(self, signed):
        request = self.auth.open(signed)
        command_id = request["command_id"]
        if request.get("operation") != "reconcile" or request["gateway_id"] != self.identity:
            raise DomainError(
                "RECONCILIATION_FORBIDDEN", "Explicit authenticated recovery required"
            )
        if command_id not in self._recoverable:
            raise DomainError(
                "RESTART_REQUIRED", "Only previous-process journal entries may be recovered"
            )
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM commands WHERE id=?", (command_id,)).fetchone()
            if row["state"] in TERMINAL:
                return self._receipt(db, row)
            task = json.loads(row["task"])
            result = self.simulator.durable_result(command_id)
            if result is None:
                # Simulator adapter proves no action; this is not a generic hardware inference.
                state = "REJECTED_BEFORE_EXECUTE"
                result = {
                    "never_executed": True,
                    "basis": "exclusive restarted simulator action log",
                }
            else:
                state = "VERIFYING"
                if task["success_condition"]["kind"] == "stable_window":
                    result["samples"] = self.simulator.window(task["success_condition"])
                    check_stable(
                        task["success_condition"], result["samples"], self.simulator.clock.now()
                    )
                    state = "SUCCEEDED"
            result["completed_at"] = self.simulator.clock.now().isoformat()
            db.execute(
                "UPDATE commands SET state=?,result=? WHERE id=?",
                (state, json.dumps(result), command_id),
            )
            return self._receipt(
                db, db.execute("SELECT * FROM commands WHERE id=?", (command_id,)).fetchone()
            )

    def _receipt(self, db, row):
        command = json.loads(row["command"])
        payload = {
            "gateway_id": self.identity,
            "epoch": command["control_epoch"],
            "command_id": row["id"],
            "payload_hash": row["payload_hash"],
            "state": row["state"],
            "result": json.loads(row["result"]) if row["result"] else None,
            "observed_at": (
                json.loads(row["result"])["completed_at"]
                if row["result"]
                else self.simulator.clock.now().isoformat()
            ),
        }
        cursor = db.execute("INSERT INTO receipts(command_id,body) VALUES (?,?)", (row["id"], "{}"))
        payload["receipt_seq"] = cursor.lastrowid
        signed = self.auth.seal(payload)
        db.execute("UPDATE receipts SET body=? WHERE seq=?", (json.dumps(signed), cursor.lastrowid))
        return signed

    @serialized
    def query(self, command_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM commands WHERE id=?", (command_id,)).fetchone()
            if row is None:
                # Absence alone is not proof that a previously sent packet cannot arrive later.
                raise DomainError("JOURNAL_MISSING", "No journal entry; do not resend")
            return self._receipt(db, row)

    @serialized
    def stop(self, signed):
        """Finite simulator boundary stop, durably tombstones even not-yet-arrived commands."""
        request = self.auth.open(signed)
        if request.get("operation") != "stop" or request.get("gateway_id") != self.identity:
            raise DomainError("STOP_INVALID", "Authenticated stop identity required")
        package = request["package"]
        command, task = package["command"], package["task"]
        self.catalog.validate_command(command)
        self.catalog.validate("plan_task", task)
        request_hash = freeze_revision(request).plan_hash
        payload_hash = freeze_revision(command).plan_hash
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT * FROM stop_results WHERE id=?", (request["stop_id"],)
            ).fetchone()
            if previous:
                if previous["request_hash"] != request_hash:
                    raise DomainError("STOP_CONFLICT", "Stop ID already bound to another request")
                return json.loads(previous["response"])
            if db.execute("SELECT epoch FROM config").fetchone()[0] != command["control_epoch"]:
                raise DomainError("OLD_EPOCH", "Stop must address the original current epoch")
            row = db.execute(
                "SELECT * FROM commands WHERE id=?", (command["command_id"],)
            ).fetchone()
            package_hash = freeze_revision(package).plan_hash
            if row and (row["payload_hash"] != payload_hash or row["package_hash"] != package_hash):
                raise DomainError("STOP_CONFLICT", "Original command bytes differ")
            if not row:
                result = {
                    "safe_stop_confirmed": True,
                    "never_executed": True,
                    "completed_at": self.simulator.clock.now().isoformat(),
                }
                db.execute(
                    "INSERT INTO commands VALUES(?,?,?,?,?,?,?,?)",
                    (
                        command["command_id"],
                        command["instrument_id"],
                        payload_hash,
                        package_hash,
                        "CANCELLED",
                        json.dumps(command),
                        json.dumps(task),
                        json.dumps(result),
                    ),
                )
            elif row["state"] not in TERMINAL | {"VERIFYING"}:
                result = self.simulator.durable_result(command["command_id"])
                if result is None:
                    state = "CANCELLED"
                    result = {"safe_stop_confirmed": True, "never_executed": True}
                else:
                    # This adapter owns an exclusive finite simulator; no real-instrument inference.
                    state = "VERIFYING"
                    if task["success_condition"]["kind"] == "stable_window":
                        result["samples"] = self.simulator.window(task["success_condition"])
                        check_stable(
                            task["success_condition"], result["samples"], self.simulator.clock.now()
                        )
                        state = "SUCCEEDED"
                result["completed_at"] = self.simulator.clock.now().isoformat()
                db.execute(
                    "UPDATE commands SET state=?,result=? WHERE id=?",
                    (state, json.dumps(result), command["command_id"]),
                )
            row = db.execute(
                "SELECT * FROM commands WHERE id=?", (command["command_id"],)
            ).fetchone()
            response = self.auth.seal(
                {
                    "stop_id": request["stop_id"],
                    "gateway_id": self.identity,
                    "command_id": command["command_id"],
                    "payload_hash": payload_hash,
                    "epoch": command["control_epoch"],
                    "quiescent": True,
                    "receipt": self._receipt(db, row),
                }
            )
            db.execute(
                "INSERT INTO stop_results VALUES(?,?,?)",
                (request["stop_id"], request_hash, json.dumps(response)),
            )
            return response

    @serialized
    def confirm_dataset(self, signed):
        """Trusted central publication acknowledgment, distinct from physical execution."""
        value = self.auth.open(signed)
        if value.get("operation") != "confirm_dataset" or value.get("gateway_id") != self.identity:
            raise DomainError("DATASET_ACK_INVALID", "Authenticated publication receipt required")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM commands WHERE id=?", (value["command_id"],)).fetchone()
            if row is None:
                raise DomainError("JOURNAL_MISSING", "No acquisition journal entry")
            command = json.loads(row["command"])
            result = json.loads(row["result"]) if row["result"] else {}
            task = json.loads(row["task"])
            if (
                row["payload_hash"] != value["payload_hash"]
                or command["control_epoch"] != value["epoch"]
                or task["success_condition"]["kind"] != "dataset_committed"
                or row["state"] not in ("VERIFYING", "SUCCEEDED")
                or not result.get("artifact")
                or freeze_revision(result["artifact"]).plan_hash != value["artifact_hash"]
            ):
                raise DomainError("DATASET_ACK_INVALID", "Acquisition identity or result differs")
            proof = {"dataset_id": value["dataset_id"], "checksum_sha256": value["checksum_sha256"]}
            if "dataset" in result and result["dataset"] != proof:
                raise DomainError(
                    "DATASET_ACK_INVALID", "Publication already bound to another result"
                )
            result["dataset"] = proof
            db.execute(
                "UPDATE commands SET state='SUCCEEDED',result=? WHERE id=?",
                (json.dumps(result), row["id"]),
            )
            return self._receipt(
                db, db.execute("SELECT * FROM commands WHERE id=?", (row["id"],)).fetchone()
            )

    @serialized
    def accept(self, signed, *, crash_at=None):
        package = self.auth.open(signed)
        command, task = package["command"], package["task"]
        self.catalog.validate_command(command)
        self.catalog.validate("plan_task", task)
        snapshot = freeze_revision(command)
        package_hash = freeze_revision(package).plan_hash
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            config = db.execute("SELECT * FROM config").fetchone()
            if config["epoch"] != command["control_epoch"]:
                raise DomainError("OLD_EPOCH", "Epoch must be explicitly handshaken")
            existing = db.execute(
                "SELECT * FROM commands WHERE id=?", (command["command_id"],)
            ).fetchone()
            if existing:
                if (
                    existing["payload_hash"] != snapshot.plan_hash
                    or existing["package_hash"] != package_hash
                ):
                    raise DomainError("COMMAND_CONFLICT", "Command ID bound to different bytes")
                return self._receipt(db, existing)
            now = self.simulator.clock.now()
            if (
                not datetime.fromisoformat(command["issued_at"])
                <= now
                < datetime.fromisoformat(command["deadline_at"])
            ):
                raise DomainError("DEADLINE_EXPIRED", "Command outside its authorization window")
            resource = command["instrument_id"]
            ref = command["skill_id"] + "@" + command["skill_version"]
            spec = self.skills.get(ref)
            if (
                spec is None
                or self.policies.get(resource) != command["policy_version"]
                or self.capabilities.get(resource) != command["capability_version"]
                or task["skill_ref"] != ref
                or task["parameters"] != command["parameters"]
                or task["resource_id"] != resource
                or task["kind"] != spec["kind"]
                or task["success_condition"]["kind"] != spec["success_kind"]
            ):
                raise DomainError("POLICY_MISMATCH", "Device, capability, skill or policy mismatch")
            Draft202012Validator(spec["input_schema"]).validate(command["parameters"])
            setpoint = spec.get("setpoint")
            if setpoint and (
                task["success_condition"].get("target")
                != command["parameters"][setpoint["parameter"]]
                or task["success_condition"].get("unit") != setpoint["unit"]
                or task["success_condition"].get("quantity") != setpoint["quantity"]
            ):
                raise DomainError(
                    "SETPOINT_MISMATCH", "Success condition differs from approved target"
                )
            preconditions = task["preconditions"]
            for condition, samples in zip(
                preconditions, self.simulator.windows(preconditions), strict=True
            ):
                check_stable(condition, samples, self.simulator.clock.now())
            if self.simulator.clock.now() >= datetime.fromisoformat(command["deadline_at"]):
                raise DomainError(
                    "DEADLINE_EXPIRED", "Authorization expired during precondition sampling"
                )
            fence = db.execute("SELECT * FROM fences WHERE device=?", (resource,)).fetchone()
            if fence and (
                command["fencing_token"] < fence["token"]
                or (
                    command["fencing_token"] == fence["token"]
                    and (command["lease_id"], command["run_id"], command["authorized_plan_hash"])
                    != (fence["lease"], fence["run"], fence["plan_hash"])
                )
            ):
                raise DomainError("STALE_FENCE", "Old token or conflicting lease owner")
            busy = db.execute(
                "SELECT id FROM commands WHERE device=? AND state NOT IN "
                "('SUCCEEDED','REJECTED_BEFORE_EXECUTE','CANCELLED','FAILED_CONFIRMED')",
                (resource,),
            ).fetchone()
            if busy:
                raise DomainError("DEVICE_BUSY", "A previous command still owns the device")
            db.execute(
                "INSERT OR REPLACE INTO fences VALUES (?,?,?,?,?)",
                (
                    resource,
                    command["fencing_token"],
                    command["lease_id"],
                    command["run_id"],
                    command["authorized_plan_hash"],
                ),
            )
            db.execute(
                "INSERT INTO commands VALUES (?,?,?,?,?,?,?,?)",
                (
                    command["command_id"],
                    resource,
                    snapshot.plan_hash,
                    package_hash,
                    "ACCEPTED",
                    json.dumps(command),
                    json.dumps(task),
                    None,
                ),
            )
        if crash_at == "after_accept":
            raise ConnectionError("injected gateway crash after ACCEPTED")
        with self.connect() as db:
            db.execute("UPDATE commands SET state='RUNNING' WHERE id=?", (command["command_id"],))
        if crash_at == "before_execute":
            raise ConnectionError("injected gateway crash after write-ahead RUNNING")
        result = self.simulator.execute(command, task)
        if crash_at == "after_execute":
            raise ConnectionError("injected gateway crash after physical simulation")
        result["completed_at"] = self.simulator.clock.now().isoformat()
        state = "VERIFYING"
        if task["success_condition"]["kind"] == "stable_window":
            check_stable(task["success_condition"], result["samples"], self.simulator.clock.now())
            state = "SUCCEEDED"
        with self.connect() as db:
            db.execute(
                "UPDATE commands SET state=?,result=? WHERE id=?",
                (state, json.dumps(result), command["command_id"]),
            )
            row = db.execute(
                "SELECT * FROM commands WHERE id=?", (command["command_id"],)
            ).fetchone()
            receipt = self._receipt(db, row)
        if crash_at == "after_result":
            raise ConnectionError("injected lost ACK after durable result")
        return receipt
