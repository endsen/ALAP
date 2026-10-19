"""D05a acquisition publication. Never collect data or perform storage I/O under DB locks."""

import json
import math
from datetime import datetime

from alap.application.experiments import digest, new_id, require
from alap.application.ports import ArtifactStore
from alap.domain.lifecycle import Authority, Kind
from alap.domain.rules import DomainError


class DatasetService:
    def __init__(self, execution, store: ArtifactStore):
        self.execution, self.store = execution, store
        self.base = execution.base
        self.transaction = self.base.transaction

    def _source(self, repo, ctx, command, receipt):
        signed = receipt["raw_receipt"]
        value = self.execution.auth.open(signed)
        instrument = repo.get("instruments", command["instrument_id"])
        require(
            receipt["command_id"] == command["id"]
            and value["command_id"] == command["id"]
            and value["payload_hash"] == command["payload_hash"]
            and value["epoch"] == str(command["epoch"])
            and value["gateway_id"] == instrument["gateway_id"]
            and value["state"] == "VERIFYING",
            "DATA_SOURCE_MISMATCH",
            "An authenticated recorded acquisition receipt is required",
        )
        task = next(t for t in ctx["tasks"] if t["id"] == command["task_id"])
        require(
            task["definition"]["skill_ref"] == "iv_measurement@1"
            and task["definition"]["success_condition"]["kind"] == "dataset_committed",
            "UNSUPPORTED_DATASET",
            "Only the versioned IV acquisition adapter is implemented",
        )
        result = value["result"]
        artifact = result["artifact"]
        parameters = task["definition"]["parameters"]
        require(
            artifact.get("status") == "LOCAL_ONLY", "DATA_SOURCE_MISMATCH", "Local result required"
        )
        count = parameters["points"]
        currents, voltages = artifact.get("current_A"), artifact.get("voltage_V")
        require(
            isinstance(currents, list)
            and isinstance(voltages, list)
            and len(currents) == len(voltages) == count,
            "INVALID_ACQUISITION",
            "IV point count differs from the approved skill",
        )
        require(
            all(type(v) in (int, float) and math.isfinite(v) for v in currents + voltages),
            "INVALID_ACQUISITION",
            "Finite numeric samples required",
        )
        expected = [
            parameters["start_ampere"]
            + i * (parameters["stop_ampere"] - parameters["start_ampere"]) / (count - 1)
            for i in range(count)
        ]
        require(
            all(
                math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-15)
                for a, b in zip(currents, expected, strict=True)
            )
            and all(abs(v) <= parameters["compliance_volt"] for v in voltages),
            "INVALID_ACQUISITION",
            "IV sequence or compliance violates the approved parameters",
        )
        interval = result.get("acquisition_interval", {})
        try:
            begin = datetime.fromisoformat(interval["start_utc"])
            end = datetime.fromisoformat(interval["end_utc"])
            issued = datetime.fromisoformat(
                json.loads(bytes(command["payload_bytes"]))["issued_at"]
            )
            valid = (
                begin.utcoffset() is not None
                and end.utcoffset() is not None
                and issued <= begin <= end <= repo.now()
            )
        except ValueError, KeyError, TypeError:
            valid = False
        require(valid, "INVALID_ACQUISITION", "Original acquisition times must bind the command")
        return artifact, interval, task

    def _context(self, repo, actor, dataset_id):
        self.execution._engine(repo, actor)
        initial = repo.get("datasets", dataset_id)
        ctx = self.execution._locked(repo, actor, initial["run_id"], authorize=False, active=False)
        row = repo.get("datasets", dataset_id, lock=True)
        command = next(c for c in ctx["commands"] if c["id"] == row["command_id"])
        receipt = repo.get("gateway_receipts", row["receipt_id"])
        artifact, interval, task = self._source(repo, ctx, command, receipt)
        metadata = {
            "dataset_id": row["id"],
            "command_id": command["id"],
            "payload_hash": command["payload_hash"],
            "acquisition_interval": interval,
        }
        return ctx, row, artifact, metadata, task

    def _change(self, repo, ctx, row, event, actor, facts, updates=None):
        decision = self.base._decision(
            repo,
            ctx["experiment"],
            row,
            Kind.DATASET,
            event,
            actor,
            Authority.DATA_SERVICE,
            repo.now(),
            facts,
        )
        values = {
            "state": decision.current.state,
            "state_version": decision.current.version,
            **(updates or {}),
        }
        repo.update("datasets", row["id"], values)
        self.base._event(
            repo,
            ctx["experiment"],
            kind="dataset",
            identity=row["id"],
            event="committed" if event == "commit" else event,
            actor=actor,
            old_version=row["state_version"],
            new_version=decision.current.version,
            from_state=row["state"],
            to_state=decision.current.state,
            evidence_ids=decision.evidence_ids,
            effects=decision.effects,
            now=decision.decided_at,
        )
        row.update(values)

    def stage(self, actor, command_id, receipt_id):
        with self.transaction() as repo:
            self.execution._engine(repo, actor)
            initial = repo.get("command_ledger", command_id)
            ctx = self.execution._locked(
                repo, actor, initial["run_id"], authorize=False, active=False
            )
            command = next(c for c in ctx["commands"] if c["id"] == command_id)
            receipt = repo.get("gateway_receipts", receipt_id)
            artifact, interval, _ = self._source(repo, ctx, command, receipt)
            existing = repo.find("datasets", {"command_id": command_id})
            if existing:
                old = repo.get("gateway_receipts", existing[0]["receipt_id"])
                old_result = self.execution.auth.open(old["raw_receipt"])["result"]
                require(
                    old_result["artifact"] == artifact
                    and old_result["acquisition_interval"] == interval,
                    "DATA_SOURCE_MISMATCH",
                    "Repeated acquisition result differs",
                )
                return existing[0]["id"]
            require(
                command["state"] == "VERIFYING", "DATA_NOT_READY", "Resolve command outcome first"
            )
            # Use a persisted dispatch snapshot, never the planning revision as device evidence.
            dispatch = next(
                e
                for e in repo.events(command["experiment_id"])
                if e["aggregate_id"] == command_id and e["event_type"] == "command.dispatch.v1"
            )
            evidence = repo.find(
                "evidence_records",
                {
                    "subject_kind": "command",
                    "subject_id": command_id,
                    "subject_version": 0,
                    "fact": "preconditions_fresh",
                },
            )
            require(
                len(evidence) == 1, "DEVICE_SNAPSHOT_MISSING", "Original dispatch evidence required"
            )
            version = dispatch["experiment_seq"]
            repo.insert(
                "device_snapshots",
                {
                    "id": new_id(),
                    "experiment_id": command["experiment_id"],
                    "version": version,
                    "command_id": command_id,
                    "source": {
                        "dispatch_event": dispatch["event_id"],
                        "evidence_id": evidence[0]["id"],
                        "preconditions": evidence[0]["source"],
                        "receipt_id": receipt_id,
                    },
                },
            )
            identity = new_id()
            row = {
                "id": identity,
                "experiment_id": command["experiment_id"],
                "run_id": command["run_id"],
                "task_id": command["task_id"],
                "command_id": command_id,
                "receipt_id": receipt_id,
                "state": "STAGING",
                "state_version": 0,
                "binding_hash": digest(
                    {"command": command["payload_hash"], "artifact": artifact, "interval": interval}
                ),
                "storage_key": self.store.key(identity),
                "device_snapshot_version": version,
                "acquired_from": datetime.fromisoformat(interval["start_utc"]),
                "acquired_to": datetime.fromisoformat(interval["end_utc"]),
            }
            repo.insert("datasets", row)
            self.execution._creation(repo, ctx, "dataset", row, actor)
            return identity

    def commit(self, actor, dataset_id):
        with self.transaction() as repo:
            ctx, row, artifact, metadata, task = self._context(repo, actor, dataset_id)
            require(
                row["state"] != "CORRUPT",
                "DATASET_CORRUPT",
                "Damaged acquisition cannot be republished",
            )
            before = dict(row)
        checksum = (
            self.store.verify(row["storage_key"], artifact, metadata)
            if before["state"] == "COMMITTED"
            else self.store.put(row["storage_key"], artifact, metadata)
        )
        if before["state"] == "COMMITTED":
            require(
                checksum == before["checksum"], "ARTIFACT_INVALID", "Published checksum changed"
            )
        with self.transaction() as repo:
            ctx, row, _, _, task = self._context(repo, actor, dataset_id)
            require(
                row["state"] != "CORRUPT",
                "DATASET_CORRUPT",
                "Damaged acquisition cannot be republished",
            )
            if row["state"] == "COMMITTED":
                require(
                    checksum == row["checksum"], "ARTIFACT_INVALID", "Published checksum changed"
                )
                return row["manifest_json"]
            if row["state"] == "STAGING":
                self._change(
                    repo,
                    ctx,
                    row,
                    "upload_complete",
                    actor,
                    {"upload_complete": {"key": row["storage_key"], "sha256": checksum}},
                )
        # A separate transaction leaves an explicit recoverable VALIDATING record on failure.
        with self.transaction() as repo:
            ctx, row, _, _, task = self._context(repo, actor, dataset_id)
            require(
                row["state"] != "CORRUPT",
                "DATASET_CORRUPT",
                "Damaged acquisition cannot be republished",
            )
            if row["state"] == "COMMITTED":
                require(row["checksum"] == checksum, "ARTIFACT_INVALID", "Checksum conflict")
                return row["manifest_json"]
            resources = task["definition"]["required_resources"]
            plan = ctx["plan"]["plan_json"]
            manifest = {
                "dataset_id": dataset_id,
                "experiment_id": row["experiment_id"],
                "run_id": row["run_id"],
                "task_id": row["task_id"],
                "instrument_ids": resources,
                "acquisition_interval": metadata["acquisition_interval"],
                "data_format": "hdf5",
                "storage_uri": "alap-artifact:" + row["storage_key"],
                "checksum_sha256": checksum,
                "unit_map": {"current_A": "A", "voltage_V": "V"},
                "status": "COMMITTED",
                "schema_version": "2.0",
                "policy_versions": {r: plan["policy_versions"][r] for r in resources},
                "capability_versions": {r: plan["capability_versions"][r] for r in resources},
                "device_snapshot_version": row["device_snapshot_version"],
            }
            self.base.catalog.validate_dataset(manifest, public=True)
            repo.insert(
                "provenance_edges",
                {
                    "dataset_id": dataset_id,
                    "experiment_id": row["experiment_id"],
                    "run_id": row["run_id"],
                    "task_id": row["task_id"],
                    "command_id": row["command_id"],
                    "receipt_id": row["receipt_id"],
                    "plan_revision_id": ctx["plan"]["id"],
                    "algorithm_version": "iv-hdf5-v1",
                    "parameters_hash": digest(task["definition"]["parameters"]),
                },
            )
            proof = {"key": row["storage_key"], "sha256": checksum, "receipt": row["receipt_id"]}
            self._change(
                repo,
                ctx,
                row,
                "commit",
                actor,
                {
                    f: proof
                    for f in (
                        "artifact_durable",
                        "checksum_verified",
                        "manifest_valid",
                        "metadata_prepared",
                    )
                },
                {"manifest_json": manifest, "checksum": checksum},
            )
            return manifest

    def read(self, actor, dataset_id):
        # No raw path returned; recheck membership and state after file I/O as well.
        with self.transaction.snapshot() as repo:
            row = repo.get("datasets", dataset_id)
            self.base._access(repo, actor, repo.get("experiments", row["experiment_id"]), "read")
            require(
                row["state"] == "COMMITTED",
                "DATASET_NOT_COMMITTED",
                "Only valid committed data is readable",
            )
            member = repo.membership(row["experiment_id"], actor)
            require(
                set(row["manifest_json"]["instrument_ids"])
                <= set(member["scope"].get("resources", [])),
                "FORBIDDEN",
                "Dataset instruments exceed membership scope",
            )
        content = self.store.read(row["storage_key"], row["checksum"])
        with self.transaction.snapshot() as repo:
            current = repo.get("datasets", dataset_id)
            self.base._access(repo, actor, repo.get("experiments", row["experiment_id"]), "read")
            require(
                current["state"] == "COMMITTED"
                and current["state_version"] == row["state_version"],
                "DATASET_NOT_COMMITTED",
                "Dataset changed during read",
            )
            member = repo.membership(row["experiment_id"], actor)
            require(
                set(current["manifest_json"]["instrument_ids"])
                <= set(member["scope"].get("resources", [])),
                "FORBIDDEN",
                "Dataset scope changed during read",
            )
        return row["manifest_json"], content

    def verify_integrity(self, actor, dataset_id):
        with self.transaction() as repo:
            ctx, row, artifact, metadata, _ = self._context(repo, actor, dataset_id)
            require(row["state"] == "COMMITTED", "DATASET_NOT_COMMITTED", "Published data required")
        try:
            checksum = self.store.verify(row["storage_key"], artifact, metadata)
            valid = checksum == row["checksum"]
        except DomainError as exc:
            if exc.code != "ARTIFACT_INVALID":
                raise
            valid = False
        if valid:
            return True
        with self.transaction() as repo:
            ctx, current, _, _, _ = self._context(repo, actor, dataset_id)
            if current["state"] == "COMMITTED":
                self._change(
                    repo,
                    ctx,
                    current,
                    "corruption_found",
                    actor,
                    {
                        "corruption_verified": {
                            "key": row["storage_key"],
                            "expected_sha256": row["checksum"],
                        }
                    },
                )
        return False

    def finalize(self, actor, dataset_id):
        """Recoverable post-commit notification; never performs an acquisition."""
        require(
            self.verify_integrity(actor, dataset_id), "DATASET_CORRUPT", "Integrity check failed"
        )
        with self.transaction() as repo:
            ctx, row, artifact, metadata, _ = self._context(repo, actor, dataset_id)
            require(
                row["state"] == "COMMITTED", "DATASET_NOT_COMMITTED", "Publish before completion"
            )
            command = next(c for c in ctx["commands"] if c["id"] == row["command_id"])
            instrument = repo.get("instruments", command["instrument_id"])
            request = {
                "operation": "confirm_dataset",
                "gateway_id": instrument["gateway_id"],
                "command_id": command["id"],
                "payload_hash": command["payload_hash"],
                "epoch": str(command["epoch"]),
                "dataset_id": dataset_id,
                "checksum_sha256": row["checksum"],
                "artifact_hash": digest(artifact),
            }
        receipt = self.execution.gateways[instrument["gateway_id"]].confirm_dataset(
            self.execution.auth.seal(request)
        )
        self.execution.ingest(
            actor,
            command["id"],
            receipt,
            reconcile=any(
                t["id"] == row["task_id"] and t["state"] == "NEEDS_RECONCILIATION"
                for t in ctx["tasks"]
            ),
        )
