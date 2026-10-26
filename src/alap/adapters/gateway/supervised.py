"""Opt-in continuous simulator using the independent monitor's authoritative outputs."""

import json
import math
import time
from datetime import UTC, datetime
from uuid import uuid4

from alap.adapters.gateway.edge import SimulationEdgeStore
from alap.adapters.gateway.simulator import Simulator
from alap.domain.rules import DomainError


class CommandEdgeStore(SimulationEdgeStore):
    def begin(self, command):
        rejected = False
        with self.transaction() as db:
            state = db.execute("SELECT * FROM edge_state WHERE id=1").fetchone()
            now = time.monotonic()
            rejected = self._expire(db, state, now) or state["mode"] == "TRIPPED"
            if not rejected:
                if db.execute("SELECT 1 FROM edge_command WHERE running=1").fetchone():
                    raise DomainError("EDGE_BUSY", "Previous command requires reconciliation")
                if datetime.now(UTC) >= datetime.fromisoformat(command["deadline_at"]):
                    raise DomainError("DEADLINE_EXPIRED", "Command lease/authorization expired")
                generation = str(uuid4())
                db.execute(
                    "INSERT OR REPLACE INTO edge_command VALUES(1,?,?,?,?,1)",
                    (
                        command["command_id"],
                        command["control_epoch"],
                        generation,
                        command["deadline_at"],
                    ),
                )
                db.execute(
                    "UPDATE edge_state SET mode='ARMED',generation=?,sequence=-1,deadline=? "
                    "WHERE id=1",
                    (generation, now + json.loads(state["policy"])["timeout_s"]),
                )
                self._event(
                    db,
                    "command_armed",
                    generation,
                    {
                        "command_id": command["command_id"],
                        "epoch": command["control_epoch"],
                        "deadline_at": command["deadline_at"],
                    },
                )
        if rejected:
            raise DomainError("EDGE_LATCHED", "Supervision loss requires explicit acknowledgement")
        return generation

    def status(self, command_id):
        with self.transaction() as db:
            binding = db.execute("SELECT * FROM edge_command WHERE id=1").fetchone()
            state = db.execute("SELECT mode,generation FROM edge_state WHERE id=1").fetchone()
            if not binding or binding["command_id"] != command_id or not binding["running"]:
                raise DomainError("EDGE_COMMAND_PENDING", "Command is not active")
            return {
                "command_id": command_id,
                "epoch": binding["epoch"],
                "generation": binding["generation"],
                "mode": state["mode"],
            }

    def pulse(self, value):
        issued, expiry = (datetime.fromisoformat(value[k]) for k in ("issued_at", "expires_at"))
        now = datetime.now(UTC)
        if not issued <= now < expiry or not 0 < (expiry - issued).total_seconds() <= 2:
            raise DomainError("EDGE_HEARTBEAT_INVALID", "Fresh bounded heartbeat required")
        self.heartbeat(
            value["generation"],
            value["sequence"],
            command_id=value["command_id"],
            epoch=value["epoch"],
        )
        return {"accepted": True}

    def finish(self, command_id, generation):
        with self.transaction() as db:
            binding = db.execute("SELECT * FROM edge_command WHERE id=1").fetchone()
            if (
                not binding
                or binding["command_id"] != command_id
                or binding["generation"] != generation
            ):
                raise DomainError("EDGE_COMMAND_MISMATCH", "Original command binding required")
            state = db.execute("SELECT * FROM edge_state WHERE id=1").fetchone()
            self._expire(db, state, time.monotonic())
            db.execute("UPDATE edge_outputs SET value=0 WHERE device='sim-smu'")
            state = db.execute("SELECT * FROM edge_state WHERE id=1").fetchone()
            db.execute("UPDATE edge_command SET running=0 WHERE id=1")
            if state["mode"] != "TRIPPED":
                db.execute("UPDATE edge_state SET mode='WAITING',deadline=NULL WHERE id=1")
            return dict(state)


class SupervisedSimulator(Simulator):
    def __init__(self, path, clock, edge_path, sample_interval_s):
        if (
            type(sample_interval_s) not in (int, float)
            or not math.isfinite(sample_interval_s)
            or not 0.01 <= sample_interval_s <= 1
        ):
            raise ValueError("Simulation sampling interval must be 0.01..1 seconds")
        super().__init__(path, clock)
        self.edge = CommandEdgeStore(edge_path)
        self.interval = sample_interval_s
        # Preserve action identity before touching output; incomplete actions are not nonexecution.
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS supervised_actions("
                "command_id TEXT PRIMARY KEY,generation TEXT,device TEXT)"
            )

    def observe(self, condition):
        result = super().observe(condition)
        result["value"] = self.edge.snapshot()["outputs"][condition["resource_id"]]
        return result

    def _interrupted(self, incident, points):
        return {
            "kind": "edge_interrupted",
            "artifact": None,
            "samples": [],
            "safe_stop_confirmed": True,
            "device_quiescent": True,
            "edge_incident": incident,
            "partial_points": points,
        }

    def durable_result(self, command_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT result FROM actions WHERE command_id=?", (command_id,)
            ).fetchone()
            binding = db.execute(
                "SELECT * FROM supervised_actions WHERE command_id=?", (command_id,)
            ).fetchone()
        if not row:
            try:
                pending = self.edge.status(command_id)
                self.edge.finish(command_id, pending["generation"])
            except DomainError as exc:
                if exc.code != "EDGE_COMMAND_PENDING":
                    raise
            return None
        if row["result"] is not None:
            return json.loads(row["result"])
        state = self.edge.snapshot()
        if (
            not binding
            or binding["device"] != "sim-smu"
            or state["mode"] != "TRIPPED"
            or state["outputs"]["sim-smu"] != 0
        ):
            raise DomainError(
                "RECONCILIATION_PENDING", "Incomplete physical action needs loss/stop evidence"
            )
        self.edge.finish(command_id, binding["generation"])
        result = self._interrupted(state["incident"], None)
        with self.connect() as db:
            db.execute(
                "UPDATE actions SET result=? WHERE command_id=?", (json.dumps(result), command_id)
            )
        return result

    def execute(self, command, task):
        identity = command["instrument_id"]
        expected = {
            "set_temperature": "sim-temp",
            "set_field": "sim-magnet",
            "iv_measurement": "sim-smu",
        }
        if expected.get(command["skill_id"]) != identity:
            raise DomainError("DEVICE_SKILL_MISMATCH", "Skill not supported by simulated device")
        generation = self.edge.begin(command)
        start = self.clock.now().isoformat()
        with self.connect() as db:
            db.execute(
                "INSERT INTO supervised_actions VALUES (?,?,?)",
                (command["command_id"], generation, identity),
            )
            db.execute(
                "INSERT INTO actions(command_id,device,result) VALUES (?,?,NULL)",
                (command["command_id"], identity),
            )
        currents = []
        result = {"samples": [], "artifact": None}
        try:
            p = command["parameters"]
            if identity == "sim-smu":
                for i in range(p["points"]):
                    value = p["start_ampere"] + i * (p["stop_ampere"] - p["start_ampere"]) / (
                        p["points"] - 1
                    )
                    self.edge.write_output(generation, identity, value)
                    time.sleep(self.interval)
                    currents.append(value)
                result["artifact"] = {
                    "current_A": currents,
                    "voltage_V": [
                        max(-p["compliance_volt"], min(p["compliance_volt"], x * 100))
                        for x in currents
                    ],
                    "status": "LOCAL_ONLY",
                }
            else:
                key = "target_kelvin" if identity == "sim-temp" else "target_tesla"
                self.edge.write_output(generation, identity, p[key])
                result["samples"] = self.window(task["success_condition"])
        except DomainError as exc:
            if exc.code != "EDGE_NOT_ARMED":
                raise
            if identity != "sim-smu":
                raise  # Do not claim generic magnet/temperature quiescence.
        state = self.edge.finish(command["command_id"], generation)
        if state["mode"] == "TRIPPED":
            if identity != "sim-smu":
                raise DomainError("RECONCILIATION_PENDING", "Device-specific recovery required")
            result = self._interrupted(state["incident"], len(currents))
        else:
            result["acquisition_interval"] = {
                "start_utc": start,
                "end_utc": self.clock.now().isoformat(),
            }
        with self.connect() as db:
            db.execute(
                "UPDATE actions SET result=? WHERE command_id=?",
                (json.dumps(result), command["command_id"]),
            )
        return result
