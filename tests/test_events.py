"""Transport canonicalization must not depend on the database session time zone."""

from datetime import UTC, datetime, timedelta, timezone

from alap.application.events import envelope


def test_event_time_normalized_across_sessions():
    now = datetime(2026, 10, 18, tzinfo=UTC)
    row = dict(
        event_id="event",
        experiment_id="experiment",
        experiment_seq=1,
        aggregate_id="run",
        aggregate_seq=0,
        event_type="run.created.v1",
        schema_version="2.0",
        producer="test",
        trace_id="trace",
        payload={},
        occurred_at=now,
    )
    local = {**row, "occurred_at": now.astimezone(timezone(timedelta(hours=8)))}
    assert envelope(row) == envelope(local)
    assert envelope(row)["occurred_at"].endswith("+00:00")
