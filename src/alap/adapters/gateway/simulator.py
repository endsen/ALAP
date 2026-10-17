"""Three persistent simulated devices, distinct from the gateway command journal.

No real device transport is imported. Simulation clock advancement is explicit and test-only.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from alap.domain.rules import DomainError


class WallClock:
    def now(self):
        return datetime.now(UTC)

    def advance(self, seconds):
        import time

        time.sleep(seconds)


class SimulationClock:
    def __init__(self, now=None):
        self.value = now or datetime.now(UTC)

    def now(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


class Simulator:
    def __init__(self, path, clock):
        self.path, self.clock = path, clock
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS devices (id TEXT PRIMARY KEY, value REAL NOT NULL)"
            )
            db.execute("""CREATE TABLE IF NOT EXISTS actions
              (seq INTEGER PRIMARY KEY, command_id TEXT NOT NULL,
               device TEXT NOT NULL, result TEXT)""")
            for identity, value in [("sim-temp", 295.0), ("sim-magnet", 0.0), ("sim-smu", 0.0)]:
                db.execute("INSERT OR IGNORE INTO devices VALUES (?,?)", (identity, value))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def observe(self, condition):
        with self.connect() as db:
            row = db.execute(
                "SELECT value FROM devices WHERE id=?", (condition["resource_id"],)
            ).fetchone()
        if row is None:
            raise DomainError("UNKNOWN_DEVICE", "Unknown simulator resource")
        return {
            "resource_id": condition["resource_id"],
            "quantity": condition["quantity"],
            "unit": condition["unit"],
            "value": row["value"],
            "quality": "GOOD",
            "observed_at": self.clock.now().isoformat(),
        }

    def window(self, condition):
        return self.windows([condition])[0]

    def windows(self, conditions):
        if not conditions:
            return []
        samples = [[self.observe(condition)] for condition in conditions]
        remaining = max(c["min_duration_s"] for c in conditions)
        step_limit = min(c["max_age_s"] for c in conditions) / 2
        while remaining > 0:
            step = min(remaining, step_limit)
            self.clock.advance(step)
            remaining -= step
            for condition, window in zip(conditions, samples, strict=True):
                window.append(self.observe(condition))
        return samples

    def durable_result(self, command_id):
        with self.connect() as db:
            rows = db.execute(
                "SELECT result FROM actions WHERE command_id=?", (command_id,)
            ).fetchall()
            if len(rows) > 1:
                raise DomainError(
                    "DUPLICATE_PHYSICAL_ACTION", "Simulator action history inconsistent"
                )
            return json.loads(rows[0]["result"]) if rows else None

    def execute(self, command, task):
        identity = command["instrument_id"]
        expected = {
            "set_temperature": "sim-temp",
            "set_field": "sim-magnet",
            "iv_measurement": "sim-smu",
        }
        if expected.get(command["skill_id"]) != identity:
            raise DomainError("DEVICE_SKILL_MISMATCH", "Skill not supported by simulated device")
        with self.connect() as db:
            if identity in ("sim-temp", "sim-magnet"):
                key = "target_kelvin" if identity == "sim-temp" else "target_tesla"
                db.execute(
                    "UPDATE devices SET value=? WHERE id=?", (command["parameters"][key], identity)
                )
                result = {"samples": [], "artifact": None}
            else:
                p = command["parameters"]
                points = p["points"]
                currents = [
                    p["start_ampere"] + i * (p["stop_ampere"] - p["start_ampere"]) / (points - 1)
                    for i in range(points)
                ]
                result = {
                    "samples": [],
                    "artifact": {
                        "current_A": currents,
                        "voltage_V": [
                            max(-p["compliance_volt"], min(p["compliance_volt"], x * 100))
                            for x in currents
                        ],
                        "status": "LOCAL_ONLY",
                    },
                }
            db.execute(
                "INSERT INTO actions(command_id,device,result) VALUES (?,?,?)",
                (command["command_id"], identity, json.dumps(result)),
            )
        if task["success_condition"]["kind"] == "stable_window":
            result["samples"] = self.window(task["success_condition"])
        return result

    def action_count(self, command_id):
        with self.connect() as db:
            return db.execute(
                "SELECT count(*) FROM actions WHERE command_id=?", (command_id,)
            ).fetchone()[0]
