import test from "node:test";
import assert from "node:assert/strict";
import { differences, formDocument } from "../../src/lib/console";
test("version forms preserve nested identity, deduplicate scope and remove omitted optional secrets", () => {
  const result = formDocument(
    [
      { key: "manifest.version", label: "版本", type: "number" },
      { key: "manifest.tools", label: "工具", type: "list" },
      { key: "secret_ref", label: "引用", optional: true },
    ],
    { "manifest.version": "2", "manifest.tools": "a@1, a@1，b@2" },
    { manifest: { schema_version: "2.0" }, secret_ref: "previous" },
  );
  assert.deepEqual(result, {
    manifest: { schema_version: "2.0", version: 2, tools: ["a@1", "b@2"] },
  });
});
test("invalid numeric budgets and malformed schemas cannot be silently coerced", () => {
  for (const value of ["", "NaN", "1.5", "-1", "101"])
    assert.throws(() =>
      formDocument([{ key: "n", label: "预算", type: "number", max: 100 }], {
        n: value,
      }),
    );
  assert.throws(() =>
    formDocument([{ key: "schema", label: "Schema", type: "json" }], {
      schema: "{",
    }),
  );
});
test("version diff includes scope removal, changed budget and nested permission", () => {
  const delta = differences(
    { scope: ["a"], manifest: { budget: 1, tool: "a@1" } },
    { scope: [], manifest: { budget: 2, tool: "a@2" } },
  );
  assert.equal(delta.length, 3);
  assert.ok(delta.some((d) => d.startsWith("manifest.tool:")));
});
