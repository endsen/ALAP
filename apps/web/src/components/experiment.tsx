"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Client, id } from "@/lib/api";
import { useAction, useExperiment, useResource } from "@/lib/hooks";
import { candidate } from "@/lib/plan";
import type {
  Agent,
  AgentRun,
  Plan,
  PlanContext,
  Proposal,
  Snapshot,
} from "@/lib/types";
import { Empty, Loading, Problem, Status } from "./common";
import { PlanPanel, Confirm, type Confirmation } from "./plans";

export function ExperimentWorkspace({
  client,
  experiment,
  initialTab,
}: {
  client: Client;
  experiment: string;
  initialTab: "chat" | "plan";
}) {
  const params = useSearchParams();
  const [tab, setTab] = useState(params.get("tab") || initialTab);
  const live = useExperiment(client, experiment);
  const s = live.snapshot;
  const sessions = useResource<{ items: AgentRun[] }>(
    client,
    `/experiments/${id(experiment)}/agent-runs?limit=100`,
  );
  const agents = useResource<{ items: Agent[] }>(
    client,
    `/experiments/${id(experiment)}/available-agents`,
  );
  const [selected, setSelected] = useState<string>();
  const [draft, setDraft] = useState<Plan>();
  const [confirmation, setConfirmation] = useState<Confirmation>();
  const action = useAction();
  const writable = !!s?.permissions.write && live.connection === "live";
  async function useProposal(proposal: Proposal) {
    await action.act(async () => {
      const context = await client.read<PlanContext>(
        `/experiments/${id(experiment)}/plan-context`,
      );
      setDraft(candidate(proposal, context));
      setTab("plan");
    });
  }
  return (
    <div className="workspace-page">
      <div className="workspace-heading">
        <div>
          <Link className="back" href="/experiments">
            ← 全部实验
          </Link>
          <h1>
            {s?.experiment.title || "实验工作区"}{" "}
            {s && <Status value={s.experiment.state} />}
          </h1>
          <p className="mono muted">{experiment}</p>
        </div>
        <div className={`connection ${live.connection}`} role="status">
          <i />
          {live.connection === "live"
            ? "实时同步"
            : live.connection === "connecting"
              ? "正在同步"
              : live.connection === "denied"
                ? "访问已中止"
                : "连接中断 · 状态可能过期"}
          <button className="subtle" onClick={live.refresh}>
            刷新
          </button>
        </div>
      </div>
      <Problem error={live.error} retry={live.refresh} />
      <Problem error={action.error} />
      {live.resynced && (
        <div className="notice">事件序列已重新同步，当前显示服务器快照。</div>
      )}
      {!s ? (
        live.error ? null : (
          <Loading />
        )
      ) : (
        <>
          <div className="tabs" role="tablist" aria-label="实验视图">
            {[
              ["chat", "Agent 工作区"],
              ["plan", "计划与审批"],
              ["data", "实验数据"],
              ["timeline", "运行记录"],
            ].map(([key, label]) => (
              <button
                role="tab"
                aria-selected={tab === key}
                className={tab === key ? "active" : ""}
                onClick={() => setTab(key)}
                key={key}
              >
                {label}
                {key === "data" && <small>{s.datasets.length}</small>}
              </button>
            ))}
          </div>
          {tab === "chat" ? (
            <div className="workspace-grid">
              <aside className="session-list">
                <div className="section-heading">
                  <h2>会话</h2>
                  <button
                    aria-label="新建会话"
                    className="subtle"
                    onClick={() => setSelected(undefined)}
                  >
                    ＋
                  </button>
                </div>
                <button
                  className={!selected ? "session current" : "session"}
                  onClick={() => setSelected(undefined)}
                >
                  <b>新的实验目标</b>
                  <small>从问题开始规划</small>
                </button>
                <Problem error={sessions.error} retry={sessions.refresh} />
                {sessions.value?.items.map((r) => (
                  <button
                    key={r.id}
                    className={
                      "session " + (selected === r.id ? "current" : "")
                    }
                    onClick={() => setSelected(r.id)}
                  >
                    <b>{r.goal}</b>
                    <small>{r.definition_ref}</small>
                    <Status value={r.status} />
                  </button>
                ))}
              </aside>
              <section className="conversation">
                <Conversation
                  key={selected || "new"}
                  client={client}
                  experiment={experiment}
                  selected={selected}
                  agents={agents.value?.items || []}
                  writable={writable}
                  choose={(identity) => {
                    setSelected(identity);
                    sessions.refresh();
                  }}
                  refresh={sessions.refresh}
                  adopt={useProposal}
                />
                <Problem error={agents.error} retry={agents.refresh} />
              </section>
              <aside className="monitor">
                <p className="eyebrow">EXPERIMENT MONITOR</p>
                <h2>实验状态</h2>
                <div className="monitor-objective">
                  <small>当前目标</small>
                  <p>{s.experiment.objective || "尚未填写目标"}</p>
                </div>
                <h3>
                  设备范围 <span>{s.permissions.resources.length}</span>
                </h3>
                {s.permissions.resources.map((r) => (
                  <div className="monitor-device" key={r}>
                    <span>⌁ {r}</span>
                    <Status value="UNKNOWN" />
                    <small>新鲜读回尚不可用</small>
                  </div>
                ))}
                {!s.permissions.resources.length && (
                  <p className="muted">尚未分配设备范围。请联系管理员配置。</p>
                )}
                <h3>执行 Run</h3>
                {!s.runs.length ? (
                  <p className="muted">尚未创建执行 Run</p>
                ) : (
                  s.runs.map((run) => (
                    <div className="run-card" key={run.id}>
                      <small className="mono">{run.id}</small>
                      <Status value={run.state} />
                      {writable && (
                        <div className="button-row">
                          {["READY", "RUNNING", "WAITING_RESOURCE"].includes(
                            run.state,
                          ) && (
                            <button
                              onClick={() =>
                                setConfirmation(controlConfirm(run, "pause"))
                              }
                            >
                              暂停
                            </button>
                          )}
                          {run.state === "PAUSED" && (
                            <button
                              onClick={() =>
                                setConfirmation(controlConfirm(run, "resume"))
                              }
                            >
                              恢复
                            </button>
                          )}
                          {!["SUCCEEDED", "FAILED", "CANCELLED"].includes(
                            run.state,
                          ) && (
                            <button
                              className="danger"
                              onClick={() =>
                                setConfirmation(controlConfirm(run, "cancel"))
                              }
                            >
                              取消
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  ))
                )}
                <p className="quiet-note">
                  暂停和取消先表达请求；只有服务器确认后才显示完成。
                </p>
              </aside>
            </div>
          ) : tab === "plan" ? (
            <PlanPanel
              client={client}
              experiment={experiment}
              snapshot={s}
              online={live.connection === "live"}
              draft={draft}
              clearDraft={() => setDraft(undefined)}
              refresh={live.refresh}
            />
          ) : tab === "data" ? (
            <section className="panel">
              {!s.datasets.length ? (
                <Empty title="还没有实验数据">
                  数据完成校验和提交后，会出现在这里。
                </Empty>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>数据集</th>
                      <th>状态</th>
                      <th>版本</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {s.datasets.map((d) => (
                      <tr key={d.id}>
                        <td className="mono">{d.id}</td>
                        <td>
                          <Status value={d.state} />
                        </td>
                        <td>{d.state_version}</td>
                        <td>
                          {d.state === "COMMITTED" ? (
                            <Link
                              className="arrow-link"
                              href={"/data/" + id(d.id)}
                            >
                              查看曲线 ↗
                            </Link>
                          ) : (
                            <span className="muted">尚不可读取</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          ) : (
            <Timeline snapshot={s} />
          )}
          {confirmation && (
            <Confirm
              client={client}
              value={confirmation}
              close={() => setConfirmation(undefined)}
              done={() => {
                setConfirmation(undefined);
                live.refresh();
              }}
            />
          )}
        </>
      )}
    </div>
  );
}
function controlConfirm(
  run: Snapshot["runs"][number],
  action: string,
): Confirmation {
  const labels: Record<string, string> = {
    pause: "暂停实验",
    resume: "恢复实验",
    cancel: "取消实验",
  };
  return {
    title: labels[action],
    path: `/runs/${id(run.id)}/actions`,
    body: { action },
    revision: run.state_version,
    details: [
      `Run：${run.id}`,
      `当前状态：${run.state} · 版本 ${run.state_version}`,
      action === "resume"
        ? "恢复前由后端重新检查审批、租约与设备读回。"
        : "这会请求停止调度或取消；不代表设备已立即停止。",
    ],
  };
}
function Conversation({
  client,
  experiment,
  selected,
  agents,
  writable,
  choose,
  refresh,
  adopt,
}: {
  client: Client;
  experiment: string;
  selected?: string;
  agents: Agent[];
  writable: boolean;
  choose: (id: string) => void;
  refresh: () => void;
  adopt: (p: Proposal) => Promise<void>;
}) {
  const [goal, setGoal] = useState("");
  const [agent, setAgent] = useState("");
  const run = useResource<AgentRun>(
    client,
    selected ? "/agent-runs/" + id(selected) : null,
  );
  const proposals = useResource<{
    items: { id: string; state: string; proposal: Proposal }[];
  }>(client, selected ? `/agent-runs/${id(selected)}/proposals` : null);
  const trace = useResource<{
    items: { seq: number; event: Record<string, unknown> }[];
  }>(client, selected ? `/agent-runs/${id(selected)}/trace` : null);
  const action = useAction();
  const alive = useRef(true);
  const [progress, setProgress] = useState<AgentRun>();
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  // The resident worker advances runs independently of this browser. Poll only
  // while a readable run is active; terminal results refresh proposal/trace data.
  useEffect(() => {
    if (!selected || run.loading || run.error || action.busy) return;
    if (
      run.value &&
      ["COMPLETED", "FAILED", "CANCELLED"].includes(run.value.status)
    ) {
      proposals.refresh();
      trace.refresh();
      return;
    }
    const timer = setTimeout(run.refresh, 2000);
    return () => clearTimeout(timer);
  }, [
    selected,
    run.loading,
    run.error,
    run.value,
    run.refresh,
    action.busy,
    proposals.refresh,
    trace.refresh,
  ]);
  async function advance() {
    if (!selected) return;
    await action.act(async () => {
      for (let i = 0; i < 32 && alive.current; i++) {
        const value = await client.mutate<AgentRun>(
          `/agent-runs/${id(selected)}/advance`,
        );
        if (!alive.current) return;
        setProgress(value);
        if (["COMPLETED", "FAILED", "CANCELLED"].includes(value.status)) break;
      }
      if (alive.current) {
        run.refresh();
        proposals.refresh();
        trace.refresh();
        refresh();
      }
    });
  }
  const current = progress || run.value;
  return (
    <>
      <div className="conversation-heading">
        <span className="agent-glyph">✧</span>
        <div>
          <h2>专用实验 Agent</h2>
          <small>
            {current?.definition_ref || "目标 → 结构化提案 → 人工审核"}
          </small>
        </div>
        {current && <Status value={current.status} />}
      </div>
      <div className="conversation-body">
        <Problem error={action.error} />
        <Problem error={run.error} retry={run.refresh} />
        {!selected ? (
          <div className="welcome">
            <span>✧</span>
            <h2>今天，想验证什么？</h2>
            <p>
              描述实验目标、设备范围与约束。
              <br />
              Agent 会协助规划，所有设备动作仍须审核。
            </p>
            <div className="suggestion">
              例如：在稳定温度和零磁场下采集 IV 曲线，
              <br />
              检查响应是否对称，并说明分析限制。
            </div>
          </div>
        ) : run.loading && !current ? (
          <Loading />
        ) : (
          current && (
            <>
              <article className="user-message">
                <small>实验目标</small>
                <p>{current.goal}</p>
              </article>
              <article className="agent-message">
                <small>✧ Agent</small>
                {current.result ? (
                  <p>
                    {typeof current.result === "string"
                      ? current.result
                      : `已生成 ${current.result.proposal_ids.length} 个结构化提案，请核对后转为计划。`}
                  </p>
                ) : (
                  <p>
                    {action.busy
                      ? "正在处理目标与工具结果…"
                      : current.status === "FAILED"
                        ? "本次处理失败，未产生可用的最终答复。"
                        : "会话已建立，继续处理可生成结果。"}
                  </p>
                )}
              </article>
              {proposals.value?.items.map((p) => (
                <div className="proposal-card" key={p.id}>
                  <div className="section-heading">
                    <strong>结构化计划提案</strong>
                    <Status value={p.state} />
                  </div>
                  <p>{p.proposal.reason}</p>
                  <small>
                    {p.proposal.tasks.length} 个步骤 ·{" "}
                    {p.proposal.requested_resources.join(" / ")}
                  </small>
                  <button
                    className="primary"
                    disabled={!writable || action.busy}
                    onClick={() => void adopt(p.proposal)}
                  >
                    转为计划草案 →
                  </button>
                </div>
              ))}
              <Problem error={proposals.error} retry={proposals.refresh} />
              <details className="trace">
                <summary>
                  查看处理轨迹（{trace.value?.items.length || 0}）
                </summary>
                <Problem error={trace.error} retry={trace.refresh} />
                {trace.value?.items.map((t) => (
                  <div key={t.seq}>
                    <span>{t.seq.toString().padStart(2, "0")}</span>
                    <strong>{String(t.event.type)}</strong>
                    <pre>{JSON.stringify(t.event, null, 2)}</pre>
                  </div>
                ))}
              </details>
            </>
          )
        )}
      </div>
      <div className="composer">
        {!writable && (
          <p className="muted">当前为只读状态，或正在等待重新同步。</p>
        )}
        {!selected ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void action.act(async () => {
                const value = await client.mutate<AgentRun>("/agent-runs", {
                  experiment_id: experiment,
                  definition_ref: agent || agents[0]?.ref,
                  goal,
                });
                choose(value.id);
              });
            }}
          >
            <label>
              实验目标
              <textarea
                placeholder="描述实验目标与约束…"
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                required
                maxLength={16000}
                disabled={!writable}
              />
            </label>
            <div className="composer-actions">
              <select
                aria-label="选择 Agent"
                value={agent || agents[0]?.ref || ""}
                onChange={(e) => setAgent(e.target.value)}
                disabled={!writable || !agents.length}
              >
                {!agents.length && (
                  <option value="">没有已发布且适用的 Agent</option>
                )}
                {agents.map((a) => (
                  <option key={a.ref} value={a.ref}>
                    {a.ref} · {a.kind}
                  </option>
                ))}
              </select>
              <button
                className="primary"
                disabled={
                  !writable || action.busy || !agents.length || !goal.trim()
                }
              >
                提交目标 ↑
              </button>
            </div>
          </form>
        ) : (
          <div className="button-row">
            <button
              className="primary"
              disabled={
                !writable ||
                action.busy ||
                !current ||
                ["COMPLETED", "FAILED", "CANCELLED"].includes(current.status)
              }
              onClick={() => void advance()}
            >
              {action.busy ? "正在处理…" : "继续处理目标 →"}
            </button>
            {current &&
              !["COMPLETED", "FAILED", "CANCELLED"].includes(
                current.status,
              ) && (
                <button
                  disabled={!writable || action.busy}
                  onClick={() =>
                    void action.act(async () => {
                      await client.mutate(`/agent-runs/${id(selected)}/cancel`);
                      run.refresh();
                      refresh();
                    })
                  }
                >
                  停止 Agent
                </button>
              )}
          </div>
        )}
        <small>对话和工具结果是建议；审批与设备执行独立核验。</small>
      </div>
    </>
  );
}
function Timeline({ snapshot: s }: { snapshot: Snapshot }) {
  return (
    <section className="panel">
      <h2>运行与验证记录</h2>
      <p className="muted">
        展示服务器当前记录；命令已发送、设备确认与验证成功是不同状态。
      </p>
      {!s.tasks.length ? (
        <Empty title="尚无执行任务" />
      ) : (
        <table>
          <thead>
            <tr>
              <th>任务</th>
              <th>运行</th>
              <th>任务状态</th>
              <th>命令状态</th>
            </tr>
          </thead>
          <tbody>
            {s.tasks.map((t) => (
              <tr key={t.id}>
                <td className="mono">{t.id}</td>
                <td className="mono">{t.run_id}</td>
                <td>
                  <Status value={t.state} />
                </td>
                <td>
                  {s.commands
                    .filter((c) => c.task_id === t.id)
                    .map((c) => (
                      <Status key={c.id} value={c.state} />
                    ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
