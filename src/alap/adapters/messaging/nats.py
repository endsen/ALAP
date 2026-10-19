"""JetStream publisher. Streams and server credentials are explicitly provisioned."""

import json

import nats


class JetStreamPublisher:
    def __init__(self, connection, stream, subject):
        self.connection = connection
        self.js = connection.jetstream()
        self.stream, self.subject = stream, subject

    @classmethod
    async def connect(cls, url, *, stream, subject):
        connection = await nats.connect(url, connect_timeout=3, max_reconnect_attempts=2)
        return cls(connection, stream, subject)

    async def publish(self, event):
        return await self.js.publish(
            self.subject,
            json.dumps(event, sort_keys=True, separators=(",", ":")).encode(),
            headers={"Nats-Msg-Id": event["event_id"]},
            stream=self.stream,
            timeout=3,
        )

    async def consume_once(self, service, actor, consumer_id, subscription, *, timeout=1):
        messages = await subscription.fetch(1, timeout=timeout)
        message = messages[0]
        # If DB commit fails, no ACK: durable consumer will redeliver.
        applied = service.consume(actor, consumer_id, json.loads(message.data))
        await message.ack_sync(timeout=3)
        return applied

    async def close(self):
        await self.connection.drain()
