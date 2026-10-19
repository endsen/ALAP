"""Actual PostgreSQL/JetStream durability, duplicate consumption and ordered replay."""

import asyncio
import json
import os
from copy import deepcopy
from uuid import uuid4

import psycopg
import pytest
from nats.js.api import ConsumerConfig, StorageType

from alap.adapters.messaging.nats import JetStreamPublisher
from alap.application.events import EventService, envelope
from alap.domain.rules import DomainError

from .conftest import rows
from .test_persistence import EXP, approved, start

pytestmark = pytest.mark.postgres


@pytest.fixture
def events(scenario):
    base, _, _, dsn = scenario
    start(base, approved(scenario))
    with psycopg.connect(dsn) as db:
        db.execute("INSERT INTO principals VALUES('events','alap-events','events','service',NULL)")
    return EventService(base), dsn


async def transport():
    url = os.environ.get("ALAP_TEST_NATS_URL")
    if not url:
        pytest.fail("Real JetStream required: set ALAP_TEST_NATS_URL")
    stream = "ALAP_TEST_" + uuid4().hex
    subject = stream + ".events"
    publisher = await JetStreamPublisher.connect(url, stream=stream, subject=subject)
    await publisher.js.add_stream(name=stream, subjects=[subject], storage=StorageType.FILE)
    return publisher


def test_jetstream_ack_loss_redelivery_and_inbox_atomicity(events):
    service, dsn = events

    async def run():
        pub = await transport()
        try:

            class LostAck:
                async def publish(self, value):
                    await pub.publish(value)
                    raise ConnectionError("ACK lost")

            with pytest.raises(ConnectionError):
                await service.publish_once("events", LostAck(), limit=1)
            assert (
                rows(dsn, "SELECT count(*) AS n FROM outbox_events WHERE published_at IS NOT NULL")[
                    0
                ]["n"]
                == 0
            )
            with psycopg.connect(dsn) as db:
                db.execute(
                    "UPDATE event_delivery_claims "
                    "SET expires_at=clock_timestamp()-interval '1 second'"
                )
            total = rows(dsn, "SELECT count(*) AS n FROM outbox_events")[0]["n"]
            assert await service.publish_once("events", pub) == total
            assert (await pub.js.stream_info(pub.stream)).state.messages == total
            sub = await pub.js.pull_subscribe(
                pub.subject,
                durable="worker",
                stream=pub.stream,
                config=ConsumerConfig(durable_name="worker", ack_wait=30, max_ack_pending=1),
            )
            message = (await sub.fetch(1, timeout=2))[0]
            event = json.loads(message.data)
            # Transaction failure cannot leave an inbox entry without its projection effect.
            with psycopg.connect(dsn) as db:
                db.execute("""CREATE FUNCTION fail_projection() RETURNS trigger
                  LANGUAGE plpgsql AS $$
                  BEGIN RAISE EXCEPTION 'projection interrupted'; END $$;
                  CREATE TRIGGER injected_failure BEFORE INSERT ON event_projections
                  FOR EACH ROW EXECUTE FUNCTION fail_projection();""")
            with pytest.raises(psycopg.errors.RaiseException):
                service.consume("events", "worker", event)
            assert rows(dsn, "SELECT * FROM consumer_inbox") == []
            with psycopg.connect(dsn) as db:
                db.execute("DROP TRIGGER injected_failure ON event_projections")
            assert service.consume("events", "worker", event)
            # DB commit succeeds but client dies before broker ACK: NAK forces the same redelivery.
            await message.nak()
            await pub.connection.flush()
            retry = (await sub.fetch(1, timeout=2))[0]
            assert json.loads(retry.data)["event_id"] == event["event_id"]
            assert not service.consume("events", "worker", json.loads(retry.data))
            await retry.ack_sync()
            assert rows(dsn, "SELECT count(*) AS n FROM consumer_inbox")[0]["n"] == 1
            if total > 1:
                assert await pub.consume_once(service, "events", "worker", sub, timeout=2)
        finally:
            await pub.js.delete_stream(pub.stream)
            await pub.close()

    asyncio.run(run())


def test_out_of_order_does_not_regress_projection_and_conflicts_rejected(events):
    service, dsn = events
    source = rows(
        dsn, "SELECT * FROM outbox_events WHERE aggregate_type='approval' ORDER BY aggregate_seq"
    )
    assert len(source) >= 2
    for row in reversed(source):
        assert service.consume("events", "projection", envelope(row))
    projection = rows(dsn, "SELECT * FROM event_projections WHERE aggregate_type='approval'")[0]
    assert projection["aggregate_seq"] == source[-1]["aggregate_seq"]
    forged = deepcopy(envelope(source[-1]))
    forged["payload"]["state"] = "FORGED"
    with pytest.raises(DomainError, match="EVENT_CONFLICT"):
        service.consume("events", "projection", forged)


def test_claim_tokens_cannot_mark_reclaimed_event_published(events):
    service, dsn = events
    with service.transaction() as repo:
        first = repo.claim_events("old", 1)[0]
    with service.transaction() as repo:
        assert all(r["event_id"] != first["event_id"] for r in repo.claim_events("other", 100))
    with psycopg.connect(dsn) as db:
        db.execute(
            "UPDATE event_delivery_claims SET expires_at=clock_timestamp()-interval '1 second'"
        )
    with service.transaction() as repo:
        repo.claim_events("new", 100)
        assert not repo.mark_published(first["event_id"], "old")
        assert repo.mark_published(first["event_id"], "new")


def test_snapshot_cursor_replay_and_permissions(events):
    service, dsn = events
    page = service.after("owner", EXP, 0, limit=2)
    assert [e["experiment_seq"] for e in page["events"]] == [1, 2]
    all_events = page["events"][:]
    while page["next_cursor"] < page["head_cursor"]:
        page = service.after("owner", EXP, page["next_cursor"], limit=2)
        all_events.extend(page["events"])
    assert len(all_events) == rows(dsn, "SELECT event_cursor FROM experiments")[0]["event_cursor"]
    assert service.after("owner", EXP, page["next_cursor"])["events"] == []
    with pytest.raises(DomainError, match="RESYNC_REQUIRED"):
        service.after("owner", EXP, page["head_cursor"] + 1)
    with psycopg.connect(dsn) as db:
        db.execute(
            "UPDATE experiment_memberships SET revoked_at=clock_timestamp() WHERE actor_id='owner'"
        )
    with pytest.raises(DomainError, match="FORBIDDEN"):
        service.after("owner", EXP, page["next_cursor"])


def test_publisher_broker_failure_keeps_pending_and_io_outside_transaction(events):
    service, dsn = events

    class BrokerDown:
        async def publish(self, value):
            with psycopg.connect(dsn) as db:
                db.execute("SET LOCAL lock_timeout='200ms'")
                db.execute(
                    "SELECT * FROM outbox_events WHERE event_id=%s FOR UPDATE", (value["event_id"],)
                )
            raise ConnectionError("broker unavailable")

    with pytest.raises(ConnectionError):
        asyncio.run(service.publish_once("events", BrokerDown(), limit=1))
    assert (
        rows(dsn, "SELECT count(*) AS n FROM outbox_events WHERE published_at IS NOT NULL")[0]["n"]
        == 0
    )
    with pytest.raises(DomainError, match="FORBIDDEN"):
        asyncio.run(service.publish_once("owner", BrokerDown()))
