"use client";
import { useEffect, useRef, useState } from "react";
import { Client, id } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import { differences } from "@/lib/plan";
import type { Plan, Snapshot } from "@/lib/types";
import { Empty, Problem, Status, Time } from "./common";
export type Confirmation = {
  title: string;
  path: string;
  body?: unknown;
  revision: number;
  details: string[];
};
export function Confirm({
  client,
  value,
  close,
  done,
}: {
  client: Client;
  value: Confirmation;
  close: () => void;
  done: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const action = useAction();
  const [checked, setChecked] = useState(false);
  useEffect(() => {
    const element = dialog.current;
    const previous = document.activeElement;
    element?.showModal();
    return () => {
      element?.close();
      requestAnimationFrame(() => {
        const target =
          previous instanceof HTMLElement &&
          previous.isConnected &&
          !previous.matches(":disabled")
            ? previous
            : document.querySelector<HTMLElement>(
                '[role="tab"][aria-selected="true"]',
              );
        target?.focus({ preventScroll: true });
      });
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className="confirmation"
      onCancel={(e) => {
        e.preventDefault();
        if (!action.busy) close();
      }}
    >
      <div className="section-heading">
        <h2>{value.title}</h2>
        <button aria-label="关闭确认" disabled={action.busy} onClick={close}>
          ×
        </button>
      </div>
      <p className="muted">请核对本次操作绑定的版本与影响范围。</p>
      <ul>
        {value.details.map((d, i) => (
          <li key={i}>{d}</li>
        ))}
      </ul>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => setChecked(e.target.checked)}
        />
        我已核对以上内容，确认本次操作。
      </label>
      <Problem error={action.error} />
      <div className="button-row">
        <button disabled={action.busy} onClick={close}>
          返回检查
        </button>
        <button
          className="primary"
          disabled={!checked || action.busy}
          onClick={() =>
            void action.act(async () => {
              await client.mutate(value.path, value.body, value.revision);
              done();
            })
          }
        >
          {action.busy ? "正在提交…" : "确认" + value.title}
        </button>
      </div>
    </dialog>
  );
}
export function PlanPanel({
  client,
  experiment,
  snapshot: s,
  online,
  draft,
  clearDraft,
  refresh,
}: {
  client: Client;
  experiment: string;
  snapshot: Snapshot;
  online: boolean;
  draft?: Plan;
  clearDraft: () => void;
  refresh: () => void;
}) {
  const [index, setIndex] = useState(0);
  const [confirmation, setConfirmation] = useState<Confirmation>();
  const [saved, setSaved] = useState(false);
  const plan = draft || s.plans[index];
  const action = useAction();
  const summary = plan
    ? s.plan_summaries.find((p) => p.id === plan.plan_revision_id)
    : undefined;
  const approvals = plan
    ? s.approvals.filter((a) => a.plan_revision_id === plan.plan_revision_id)
    : [];
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const currentPlan =
    !!plan &&
    (draft
      ? plan.proposal.based_on_snapshot_version === s.experiment.revision
      : plan.plan_revision_id === s.plans[0]?.plan_revision_id);
  const writable = s.permissions.write && online;
  const details = plan
    ? [
        `计划版本：v${plan.revision} · ${plan.plan_revision_id}`,
        `设备：${plan.proposal.requested_resources.join("、")}`,
        `风险：${plan.proposal.risk_level}`,
        `计划 hash：${summary?.plan_hash || "提交校验后生成"}`,
      ]
    : [];
  return (
    <div className="plan-layout">
      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">PLAN STUDIO</p>
            <h2>{draft ? "审核计划草案" : "计划版本"}</h2>
          </div>
          {!draft && s.plans.length > 0 && (
            <select
              aria-label="选择计划版本"
              value={index}
              onChange={(e) => setIndex(Number(e.target.value))}
            >
              {s.plans.map((p, i) => (
                <option key={p.plan_revision_id} value={i}>
                  v{p.revision} · {i === 0 ? "最新版本" : "历史版本"}
                </option>
              ))}
            </select>
          )}
        </div>
        <Problem error={action.error} />
        {saved && !approvals.length && (
          <div className="notice">
            计划已提交校验。设备尚未执行，请继续请求审批。
          </div>
        )}
        {!plan ? (
          <Empty title="还没有计划">
            在 Agent 工作区提交目标，将结构化提案转为计划草案。
          </Empty>
        ) : (
          <>
            <div className="plan-summary">
              <span>
                VERSION <b>{plan.revision.toString().padStart(2, "0")}</b>
              </span>
              <div>
                <h3>{plan.proposal.reason}</h3>
                <p>
                  {plan.proposal.requested_resources.join(" · ")}{" "}
                  <span className="outline-label">
                    {plan.proposal.risk_level}
                  </span>
                </p>
              </div>
            </div>
            {!currentPlan && (
              <div className="problem">
                这是历史版本或基于旧快照的草案。请刷新并重新规划，不能沿用旧状态审批。
              </div>
            )}
            <div className="dag" aria-label="任务依赖图">
              {plan.proposal.tasks.map((t, i) => (
                <div className="dag-node" key={t.id}>
                  <span>{String(i + 1).padStart(2, "0")}</span>
                  <div>
                    <b>{t.id}</b>
                    <small>
                      {t.depends_on.length
                        ? "依赖 " + t.depends_on.join("、")
                        : "起始步骤"}{" "}
                      → {t.resource_id}
                    </small>
                  </div>
                </div>
              ))}
            </div>
            <h3>步骤参数与约束</h3>
            {plan.proposal.tasks.map((t) => (
              <details className="task-detail" key={t.id}>
                <summary>
                  <b>{t.id}</b>
                  <span>
                    {t.kind} · {t.skill_ref}
                  </span>
                </summary>
                <dl>
                  <dt>设备</dt>
                  <dd>{t.required_resources.join(" · ")}</dd>
                  <dt>超时</dt>
                  <dd>{t.timeout_s} 秒</dd>
                  <dt>参数</dt>
                  <dd>
                    <pre>{JSON.stringify(t.parameters, null, 2)}</pre>
                  </dd>
                  <dt>前置条件</dt>
                  <dd>
                    <pre>{JSON.stringify(t.preconditions, null, 2)}</pre>
                  </dd>
                  <dt>成功依据</dt>
                  <dd>
                    <pre>{JSON.stringify(t.success_condition, null, 2)}</pre>
                  </dd>
                </dl>
              </details>
            ))}
            <details className="diff" open>
              <summary>与{draft ? "当前最新" : "上一个"}版本的差异</summary>
              <ul>
                {differences(draft ? s.plans[0] : s.plans[index + 1], plan).map(
                  (d, i) => (
                    <li key={i}>{d}</li>
                  ),
                )}
              </ul>
            </details>
            {draft && (
              <div className="notice">
                此提案将作为你提交的计划版本。后端将验证依赖、设备范围、参数和快照版本。
              </div>
            )}
            <div className="button-row">
              {draft ? (
                <>
                  <button
                    className="primary"
                    disabled={!writable || action.busy || !currentPlan}
                    onClick={() =>
                      void action.act(async () => {
                        await client.mutate(
                          `/experiments/${id(experiment)}/proposals`,
                          draft,
                          s.experiment.revision,
                        );
                        clearDraft();
                        setSaved(true);
                        setIndex(0);
                        refresh();
                      })
                    }
                  >
                    提交计划校验
                  </button>
                  <button disabled={action.busy} onClick={clearDraft}>
                    放弃草案
                  </button>
                </>
              ) : (
                <button
                  className="primary"
                  disabled={!writable || !currentPlan || !summary}
                  onClick={() =>
                    setConfirmation({
                      title: "请求审批",
                      path: `/experiments/${id(experiment)}/approval-requests`,
                      body: {
                        plan_revision_id: plan.plan_revision_id,
                        plan_hash: summary!.plan_hash,
                        expires_at: new Date(
                          Date.now() + 30 * 60 * 1000,
                        ).toISOString(),
                      },
                      revision: s.experiment.revision,
                      details: [...details, "审批有效期：自本次请求起 30 分钟"],
                    })
                  }
                >
                  请求审批
                </button>
              )}
            </div>
            {summary && (
              <p className="hash mono">SHA-256 {summary.plan_hash}</p>
            )}
          </>
        )}
      </section>
      <aside className="panel approval-panel">
        <p className="eyebrow">APPROVAL GATE</p>
        <h2>审批与执行</h2>
        <p className="muted">审批只对指定版本、设备和参数有效。</p>
        {!approvals.length ? (
          <Empty title="暂无审批记录" />
        ) : (
          approvals.map((a) => {
            const expired = new Date(a.expires_at).getTime() <= now;
            const stale =
              !currentPlan || !summary || a.plan_hash !== summary.plan_hash;
            return (
              <article className="approval-card" key={a.id}>
                <Status
                  value={
                    expired && ["PENDING", "APPROVED"].includes(a.state)
                      ? "EXPIRED"
                      : a.state
                  }
                />
                <small className="mono">{a.id}</small>
                <p>
                  有效期至
                  <br />
                  <Time value={a.expires_at} />
                </p>
                <p className="hash mono">{a.plan_hash}</p>
                <div className="button-row">
                  {a.state === "PENDING" && s.permissions.approve && (
                    <>
                      <button
                        className="primary"
                        disabled={!online || expired || stale}
                        onClick={() =>
                          setConfirmation({
                            title: "批准计划",
                            path: `/experiments/${id(experiment)}/approvals`,
                            body: {
                              approval_id: a.id,
                              decision: "approve",
                              state_version: a.state_version,
                            },
                            revision: s.experiment.revision,
                            details: [
                              ...details,
                              `有效期至 ${new Date(a.expires_at).toLocaleString()}`,
                            ],
                          })
                        }
                      >
                        批准
                      </button>
                      <button
                        disabled={!online}
                        onClick={() =>
                          setConfirmation({
                            title: "拒绝计划",
                            path: `/experiments/${id(experiment)}/approvals`,
                            body: {
                              approval_id: a.id,
                              decision: "reject",
                              state_version: a.state_version,
                            },
                            revision: s.experiment.revision,
                            details,
                          })
                        }
                      >
                        拒绝
                      </button>
                    </>
                  )}
                  {a.state === "APPROVED" && (
                    <>
                      {writable && (
                        <button
                          className="primary"
                          disabled={
                            expired ||
                            stale ||
                            s.runs.some(
                              (r) =>
                                r.plan_revision_id === a.plan_revision_id &&
                                !["SUCCEEDED", "FAILED", "CANCELLED"].includes(
                                  r.state,
                                ),
                            )
                          }
                          onClick={() =>
                            setConfirmation({
                              title: "启动 Run",
                              path: `/experiments/${id(experiment)}/runs`,
                              body: { approval_id: a.id },
                              revision: s.experiment.revision,
                              details: [
                                ...details,
                                "创建待调度 Run；仍需调度器与 Gateway 独立核验。",
                              ],
                            })
                          }
                        >
                          创建执行 Run
                        </button>
                      )}
                      {s.permissions.approve && (
                        <button
                          disabled={!online}
                          onClick={() =>
                            setConfirmation({
                              title: "撤销审批",
                              path: `/experiments/${id(experiment)}/approvals`,
                              body: {
                                approval_id: a.id,
                                decision: "revoke",
                                state_version: a.state_version,
                              },
                              revision: s.experiment.revision,
                              details,
                            })
                          }
                        >
                          撤销
                        </button>
                      )}
                    </>
                  )}
                </div>
              </article>
            );
          })
        )}
        {!s.permissions.approve && (
          <p className="notice">当前身份没有人工审批权限。</p>
        )}
        {s.runs.map((r) => (
          <div className="run-card" key={r.id}>
            <small className="mono">{r.id}</small>
            <Status value={r.state} />
          </div>
        ))}
      </aside>
      {confirmation && (
        <Confirm
          client={client}
          value={confirmation}
          close={() => setConfirmation(undefined)}
          done={() => {
            setConfirmation(undefined);
            refresh();
          }}
        />
      )}
    </div>
  );
}
