import type { Plan, Proposal, PlanContext } from "./types";
export function candidate(proposal: Proposal, context: PlanContext): Plan {
  if (proposal.based_on_snapshot_version !== context.snapshot_version)
    throw new Error("提案基于旧快照。请重新规划，不能自动套用新状态。");
  const select = (versions: Record<string, string>) =>
    Object.fromEntries(
      proposal.requested_resources.map((r) => {
        if (!versions[r])
          throw new Error("缺少设备能力或策略版本，请联系管理员。");
        return [r, versions[r]];
      }),
    );
  return {
    schema_version: "2.0",
    plan_revision_id: crypto.randomUUID(),
    revision: context.next_revision,
    proposal,
    policy_versions: select(context.policy_versions),
    capability_versions: select(context.capability_versions),
  };
}
export function differences(before: Plan | undefined, after: Plan): string[] {
  if (!before) return ["首个计划版本，所有步骤均为新增。"];
  const changes: string[] = [];
  if (
    JSON.stringify(before.proposal.requested_resources) !==
    JSON.stringify(after.proposal.requested_resources)
  )
    changes.push("设备范围已变化");
  if (before.proposal.risk_level !== after.proposal.risk_level)
    changes.push("风险级别已变化");
  const old = new Map(before.proposal.tasks.map((t) => [t.id, t]));
  for (const task of after.proposal.tasks) {
    if (!old.has(task.id)) changes.push(`新增步骤：${task.id}`);
    else if (JSON.stringify(old.get(task.id)) !== JSON.stringify(task))
      changes.push(`步骤参数或依赖变化：${task.id}`);
    old.delete(task.id);
  }
  for (const key of old.keys()) changes.push(`移除步骤：${key}`);
  if (!changes.length)
    changes.push("设备、风险与步骤结构未变化；仍需按新版本重新审批。");
  return changes;
}
