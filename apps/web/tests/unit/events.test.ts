import { test } from "node:test";
import assert from "node:assert/strict";
import { SSEDecoder, eventDecision } from "../../src/lib/events";
test("SSE split boundaries, multiline content and heartbeat", () => {
  const decoder = new SSEDecoder();
  assert.deepEqual(
    decoder.push(
      ': heartbeat\r\n\r\nid: 7\r\nevent: task.changed\r\ndata: {"experiment_seq":',
    ),
    [],
  );
  const frames = decoder.push('7,\r\ndata: "message":"中文"}\r\n\r\n');
  assert.equal(frames.length, 1);
  assert.equal(frames[0].id, 7);
  assert.equal(JSON.parse(frames[0].data).message, "中文");
  assert.equal(eventDecision(frames[0], 6), "refresh");
});
test("dedup, gap and cursor mismatch never fabricate state", () => {
  const frame = { id: 5, event: "task", data: '{"experiment_seq":5}' };
  assert.equal(eventDecision(frame, 5), "skip");
  assert.equal(eventDecision(frame, 2), "resync");
  assert.throws(() => eventDecision({ ...frame, id: 6 }, 5));
  assert.equal(
    eventDecision({ event: "stream.error", data: "{}" }, 5),
    "resync",
  );
});
test("oversized or invalid cursors and incomplete frames are not applied", () => {
  assert.throws(() => new SSEDecoder().push("id: -1\ndata: {}\n\n"));
  assert.throws(() => new SSEDecoder().push("x".repeat(524289)));
  assert.deepEqual(new SSEDecoder().push("id: 1\ndata: {}\n"), []);
});
