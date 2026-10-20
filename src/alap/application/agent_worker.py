"""Bounded, fair advancement of existing Agent runs in explicitly enabled experiments."""

from alap.application.experiments import require
from alap.domain.rules import DomainError


class AgentWorker:
    def __init__(self, runtime, actor, experiments, *, limit=20, refresh=lambda: None, cancel=None):
        require(
            isinstance(experiments, list)
            and 0 < len(experiments) <= 1000
            and all(isinstance(e, str) and e for e in experiments),
            "INVALID_SCOPE",
            "Explicit experiment allowlist required",
        )
        require(type(limit) is int and 1 <= limit <= 100, "INVALID_LIMIT", "Batch size 1..100")
        self.runtime, self.actor, self.experiments = runtime, actor, experiments
        self.limit, self.refresh, self.cancel = limit, refresh, cancel
        self.after = ""

    def tick(self):
        store = self.runtime.store
        candidates = store.worker_candidates(
            self.actor, self.experiments, after=self.after, limit=self.limit
        )
        self.refresh()
        report = []
        for row in candidates:
            if self.cancel is not None and self.cancel.is_set():
                break
            store.authorize_worker(self.actor)
            self.after = row["id"]
            try:
                # Original submitter's membership, scope and pinned versions are checked again.
                run = self.runtime.step(row["actor_id"], row["id"], self.cancel)
                report.append({"run_id": row["id"], "status": run["checkpoint"]["status"]})
            except DomainError as exc:
                report.append({"run_id": row["id"], "code": exc.code})
        if len(candidates) < self.limit:
            self.after = ""
        return {"event": "agent_tick", "runs": report}
