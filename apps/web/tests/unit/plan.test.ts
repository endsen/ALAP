import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { candidate, differences } from "../../src/lib/plan";
import type { Plan } from "../../src/lib/types";
const plan = JSON.parse(
  fs.readFileSync(
    path.resolve("../../contracts/examples/plan_revision.json"),
    "utf8",
  ),
) as Plan;
const context = {
  snapshot_version: 1,
  next_revision: 2,
  policy_versions: plan.policy_versions,
  capability_versions: plan.capability_versions,
};
test("candidate binds exact snapshot, policy and capability versions", () => {
  const value = candidate(plan.proposal, context);
  assert.equal(value.revision, 2);
  assert.deepEqual(value.policy_versions, plan.policy_versions);
  assert.throws(() =>
    candidate(plan.proposal, { ...context, snapshot_version: 2 }),
  );
  assert.throws(() =>
    candidate(plan.proposal, { ...context, policy_versions: {} }),
  );
});
test("diff identifies resources, risks and changed task constraints", () => {
  const changed = structuredClone(plan);
  changed.proposal.tasks[0].timeout_s += 1;
  assert.ok(
    differences(plan, changed).some((s) =>
      s.includes(changed.proposal.tasks[0].id),
    ),
  );
  assert.ok(differences(undefined, plan)[0].includes("首个"));
});
