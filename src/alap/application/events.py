"""Durable experiment stream; broker delivery never authorizes hardware actions."""

from datetime import UTC

from alap.application.experiments import digest, new_id, require
from alap.application.ports import EventPublisher


def envelope(row):
    return {
        k: row[k]
        for k in (
            "event_id",
            "experiment_id",
            "experiment_seq",
            "aggregate_id",
            "aggregate_seq",
            "event_type",
            "schema_version",
            "producer",
            "trace_id",
            "payload",
        )
    } | {"occurred_at": row["occurred_at"].astimezone(UTC).isoformat()}


class EventService:
    def __init__(self, foundation):
        self.base, self.transaction = foundation, foundation.transaction

    def _service(self, repo, actor):
        principal = self.base._principal(repo, actor)
        require(
            principal["kind"] == "service" and principal["issuer"] == "alap-events",
            "FORBIDDEN",
            "Explicit event worker identity required",
        )

    async def publish_once(
        self, actor, publisher: EventPublisher, *, limit=100, stopping=lambda: False
    ):
        require(type(limit) is int and 1 <= limit <= 100, "INVALID_LIMIT", "Batch size 1..100")
        token = new_id()
        with self.transaction() as repo:
            self._service(repo, actor)
            batch = repo.claim_events(token, limit)
        published = 0
        for row in batch:
            if stopping():
                break
            with self.transaction() as repo:
                self._service(repo, actor)
            value = envelope(row)
            self.base.catalog.validate("event", value)
            await publisher.publish(value)  # Await durable broker ACK with no DB locks held.
            with self.transaction() as repo:
                self._service(repo, actor)
                published += int(repo.mark_published(row["event_id"], token))
        return published

    def consume(self, actor, consumer_id, value):
        require(
            isinstance(consumer_id, str) and 0 < len(consumer_id) <= 100,
            "INVALID_CONSUMER",
            "Stable consumer identity required",
        )
        self.base.catalog.validate("event", value)
        with self.transaction() as repo:
            self._service(repo, actor)
            original = repo.event(value["event_id"])
            require(
                digest(envelope(original)) == digest(value),
                "EVENT_CONFLICT",
                "Message must match the immutable authoritative event",
            )
            return repo.apply_event(consumer_id, original, digest(value))

    def after(self, actor, experiment_id, cursor, *, limit=100):
        require(
            type(cursor) is int and cursor >= 0, "INVALID_CURSOR", "Nonnegative cursor required"
        )
        require(type(limit) is int and 1 <= limit <= 1000, "INVALID_LIMIT", "Page size 1..1000")
        with self.transaction.snapshot() as repo:
            experiment = repo.get("experiments", experiment_id)
            self.base._access(repo, actor, experiment, "read")
            # Authorize the same snapshot as the returned event page: a concurrent
            # new plan must not introduce events beyond the reader's resource scope.
            member = repo.membership(experiment_id, actor)
            resources = set(member["scope"].get("resources", []))
            require(
                all(
                    set(plan["plan_json"]["proposal"]["requested_resources"]) <= resources
                    for plan in repo.plans(experiment_id)
                ),
                "FORBIDDEN",
                "Experiment events exceed current resource scope",
            )
            require(
                cursor <= experiment["event_cursor"],
                "RESYNC_REQUIRED",
                "Cursor is ahead of authority",
            )
            events = repo.events_after(experiment_id, cursor, limit)
            expected = cursor
            for event in events:
                expected += 1
                require(
                    event["experiment_seq"] == expected, "RESYNC_REQUIRED", "Persistent stream gap"
                )
            require(
                events or cursor == experiment["event_cursor"],
                "RESYNC_REQUIRED",
                "History unavailable",
            )
            return {
                "events": [envelope(e) for e in events],
                "next_cursor": expected,
                "head_cursor": experiment["event_cursor"],
            }
