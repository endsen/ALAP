import { test } from "node:test";
import assert from "node:assert/strict";
import { Client, APIError } from "../../src/lib/api";
test("ambiguous delivery retains idempotency key and blocks changed payload", async (t) => {
  const keys: string[] = [];
  let calls = 0;
  t.mock.method(
    globalThis,
    "fetch",
    async (_url: unknown, init: RequestInit) => {
      keys.push((init.headers as Record<string, string>)["Idempotency-Key"]);
      if (calls++ === 0) throw new TypeError("offline");
      return new Response(JSON.stringify({ id: "one" }), { status: 201 });
    },
  );
  const client = new Client("test", () => {});
  await assert.rejects(client.mutate("/experiments", { title: "same" }));
  await assert.rejects(
    client.mutate("/experiments", { title: "changed" }),
    (e) => e instanceof APIError && e.code === "EXECUTION_UNKNOWN",
  );
  await client.mutate("/experiments", { title: "same" });
  assert.equal(keys.length, 2);
  assert.equal(keys[0], keys[1]);
  await client.mutate("/experiments", { title: "same" });
  assert.notEqual(keys[1], keys[2]);
});
test("401 expires session and no input contents become error messages", async (t) => {
  let expired = false;
  t.mock.method(
    globalThis,
    "fetch",
    async () =>
      new Response(
        JSON.stringify({
          error: {
            code: "UNAUTHENTICATED",
            message: "raw-secret",
            request_id: "req",
          },
        }),
        { status: 401 },
      ),
  );
  const client = new Client("test", () => {
    expired = true;
  });
  await assert.rejects(
    client.read("/me"),
    (e) =>
      e instanceof APIError &&
      e.message === "UNAUTHENTICATED" &&
      e.requestId === "req",
  );
  assert.ok(expired);
});
