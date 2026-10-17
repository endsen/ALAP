"""Semantic rules for already schema-validated experiment records."""

import hashlib
import heapq
import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any


class DomainError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def require_json_value(value: Any) -> None:
    """Reject non-JSON objects and Python's otherwise accepted NaN/Infinity."""
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            require_json_value(item)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            require_json_value(item)
        return
    raise DomainError("INVALID_JSON_VALUE", "Only finite JSON values and string keys are allowed")


def validate_plan_resources_and_dag(plan: dict, *, snapshot_version: int) -> tuple[str, ...]:
    if plan["based_on_snapshot_version"] != snapshot_version:
        raise DomainError("PLAN_STALE", "The planning snapshot no longer matches")
    tasks = plan["tasks"]
    ids = [task["id"] for task in tasks]
    if len(ids) != len(set(ids)):
        raise DomainError("DUPLICATE_TASK", "Task IDs must be unique")
    by_id = {task["id"]: task for task in tasks}
    resources = set()
    for task in tasks:
        task_resources = set(task["required_resources"])
        resources.update(task_resources)
        if task["resource_id"] not in task_resources:
            raise DomainError("UNDECLARED_RESOURCE", "Task must reserve its primary resource")
        conditions = task["preconditions"] + [task["success_condition"]]
        for condition in conditions:
            if condition["kind"] == "stable_window":
                if condition["resource_id"] not in task_resources:
                    raise DomainError(
                        "UNDECLARED_RESOURCE", "Condition references unreserved device"
                    )
        success = task["success_condition"]
        if success["kind"] == "stable_window":
            if success["resource_id"] != task["resource_id"]:
                raise DomainError("INVALID_SUCCESS_CONDITION", "Readback must match primary device")
            if success["min_duration_s"] > task["timeout_s"]:
                raise DomainError("INVALID_SUCCESS_CONDITION", "Stable window exceeds task timeout")
        if task["id"] in task["depends_on"]:
            raise DomainError("CYCLIC_PLAN", "A task cannot depend on itself")
        if set(task["depends_on"]) - by_id.keys():
            raise DomainError("MISSING_DEPENDENCY", "Task references an unknown dependency")
    if resources != set(plan["requested_resources"]):
        raise DomainError("RESOURCE_MISMATCH", "Plan resources must exactly cover task resources")
    indegrees = {task["id"]: len(task["depends_on"]) for task in tasks}
    children: dict[str, list[str]] = {task_id: [] for task_id in ids}
    for task in tasks:
        for parent in task["depends_on"]:
            children[parent].append(task["id"])
    ready = [task_id for task_id, degree in indegrees.items() if degree == 0]
    heapq.heapify(ready)
    ordered = []
    while ready:
        task_id = heapq.heappop(ready)
        ordered.append(task_id)
        for child in children[task_id]:
            indegrees[child] -= 1
            if indegrees[child] == 0:
                heapq.heappush(ready, child)
    if len(ordered) != len(tasks):
        raise DomainError("CYCLIC_PLAN", "Task dependencies contain a cycle")
    return tuple(ordered)


def validate_version_maps(record: dict, resources: set[str]) -> None:
    for field in ("policy_versions", "capability_versions"):
        if set(record[field]) != resources:
            raise DomainError("PROVENANCE_MISMATCH", f"{field} must cover exactly the resources")


def validate_interval(start: str, end: str, *, strictly_increasing: bool = False) -> None:
    # RFC 3339 permits lowercase t/z, whereas fromisoformat rejects a lowercase z.
    start_at, end_at = datetime.fromisoformat(start.upper()), datetime.fromisoformat(end.upper())
    if end_at < start_at or (strictly_increasing and end_at == start_at):
        raise DomainError("INVALID_TIME_INTERVAL", "End must follow start")


@dataclass(frozen=True)
class PlanSnapshot:
    """Immutable validated bytes; not an approval or permission to dispatch."""

    canonical_bytes: bytes

    @property
    def plan_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()


def freeze_revision(revision: dict) -> PlanSnapshot:
    require_json_value(revision)
    return PlanSnapshot(
        json.dumps(
            revision, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    )
