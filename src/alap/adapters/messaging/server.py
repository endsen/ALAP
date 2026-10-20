"""Publish PostgreSQL outbox notifications to a pre-provisioned JetStream stream."""

import argparse
import asyncio
import json
import math
import signal
import sys
import time
from pathlib import Path

import nats.errors
import psycopg

from alap.adapters.messaging.nats import JetStreamPublisher
from alap.adapters.postgres.repository import PostgresUnitOfWork
from alap.adapters.postgres.settings import database_url
from alap.application.events import EventService
from alap.application.experiments import ExperimentService, require
from alap.contracts import ContractCatalog


def build_service(dsn):
    return EventService(
        ExperimentService(
            PostgresUnitOfWork(dsn),
            ContractCatalog(Path(__file__).resolve().parents[4] / "contracts"),
            skills={},
            policy_versions={},
            capability_versions={},
        )
    )


async def serve(service, settings, stop):
    poll_s = settings.get("poll_s", 0.5)
    limit = settings.get("batch_size", 1)
    if not math.isfinite(poll_s) or not 0.05 <= poll_s <= 60:
        raise ValueError("Polling interval must be 0.05..60 seconds")
    require(type(limit) is int and 1 <= limit <= 100, "INVALID_LIMIT", "Batch size 1..100")
    publisher, last, heartbeat, failures = None, None, 0, 0

    async def sanitized_error(_error):
        # The NATS default error logger can include connection details.
        return None

    try:
        while not stop.is_set():
            delay = poll_s
            try:
                with service.transaction() as repo:
                    service._service(repo, settings["events_actor"])
                if publisher is None:
                    publisher = await JetStreamPublisher.connect(
                        settings["nats_url"],
                        stream=settings["stream"],
                        subject=settings["subject"],
                        error_cb=sanitized_error,
                    )
                count = await service.publish_once(
                    settings["events_actor"], publisher, limit=limit, stopping=stop.is_set
                )
                report = {"event": "outbox_tick", "published": count}
                failures = 0
            except nats.errors.Error, OSError, psycopg.OperationalError:
                # Claims expire in PostgreSQL. Never mark published without a durable ACK.
                if publisher is not None:
                    await publisher.connection.close()
                    publisher = None
                failures = min(failures + 1, 6)
                delay = min(30, poll_s * 2**failures)
                report = {"event": "outbox_retry", "code": "DELIVERY_UNAVAILABLE"}
            encoded = json.dumps(report, sort_keys=True)
            if encoded != last or time.monotonic() - heartbeat >= 30:
                print(encoded, flush=True)
                last, heartbeat = encoded, time.monotonic()
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except TimeoutError:
                pass
    finally:
        if publisher is not None:
            await publisher.connection.close()


async def run(settings):
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        await serve(build_service(database_url()), settings, stop)
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        asyncio.run(run(json.loads(args.config.read_text())))
        print(json.dumps({"event": "outbox_stopped"}), flush=True)
        return 0
    except Exception as exc:
        print(
            json.dumps({"event": "outbox_failed", "code": getattr(exc, "code", "OUTBOX_ERROR")}),
            file=sys.stderr,
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
