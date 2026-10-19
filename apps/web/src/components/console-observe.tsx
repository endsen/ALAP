"use client";
import Link from "next/link";
import { useState } from "react";
import { Client, id } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { AgentRun, Experiment, Snapshot } from "@/lib/types";
import type { RecordValue } from "@/lib/console";
import { Empty, Status, Time } from "./common";
import { JsonView, Panel, Result } from "./console-common";
export function ExperimentChoice({
  client,
  selected,
  onChange,
}: {
  client: Client;
  selected: string;
  onChange: (id: string) => void;
}) {
  const [cursor, setCursor] = useState("");
  const data = useResource<{ items: Experiment[]; next_cursor: string | null }>(
    client,
    `/experiments?limit=20&cursor=${id(cursor)}`,
  );
  return (
    <Panel title="实验范围">
      <Result {...data} retry={data.refresh}>
        <div className="console-actions">
          <label>
            选择实验
            <select value={selected} onChange={(e) => onChange(e.target.value)}>
              <option value="">请选择有权限的实验</option>
              {data.value?.items.map((e) => (
                <option value={e.id} key={e.id}>
                  {e.title || e.id}
                </option>
              ))}
            </select>
          </label>
          <button disabled={!cursor} onClick={() => setCursor("")}>
            首页
          </button>
          <button
            disabled={!data.value?.next_cursor}
            onClick={() => setCursor(data.value!.next_cursor!)}
          >
            下一页实验
          </button>
        </div>
      </Result>
    </Panel>
  );
}
type Group = {
  agent_run_ids: string[];
  vendor: string | null;
  model_ref: string;
  agent_ref: string;
  utc_day: string;
  model_completions: number;
  recorded_attempts: number;
  unknown_usage: number;
  reported_tokens: Record<string, number> | null;
  estimated_cost: null;
};
type Usage = {
  groups: Group[];
  agent_runs: number;
  logical_requests: number;
  unresolved_requests: number;
  reported_tokens: Record<string, number | null>;
  unknown_usage_completions: number;
  estimated_cost: null;
};
type Dashboard = {
  experiment: Experiment;
  event_cursor: number;
  runs_by_state: Record<string, number>;
  approvals_by_state: Record<string, number>;
  datasets_by_state: Record<string, number>;
  instruments: { id: string; status: string }[];
  usage: Usage;
};
export function Observe({
  client,
  mode,
  initialExperiment = "",
  initialRun = "",
}: {
  client: Client;
  mode: "dashboard" | "usage" | "traces";
  initialExperiment?: string;
  initialRun?: string;
}) {
  const [experiment, setExperiment] = useState(initialExperiment);
  return (
    <>
      <ExperimentChoice
        client={client}
        selected={experiment}
        onChange={setExperiment}
      />
      {experiment ? (
        <div key={experiment}>
          {mode === "traces" ? (
            <Traces
              client={client}
              experiment={experiment}
              initialRun={initialRun}
            />
          ) : (
            <Metrics
              client={client}
              experiment={experiment}
              dashboard={mode === "dashboard"}
            />
          )}
        </div>
      ) : (
        <Empty title="选择实验后读取授权记录" />
      )}
    </>
  );
}
function Metrics({
  client,
  experiment,
  dashboard,
}: {
  client: Client;
  experiment: string;
  dashboard: boolean;
}) {
  const data = useResource<Dashboard | Usage>(
    client,
    `/experiments/${id(experiment)}/${dashboard ? "dashboard" : "usage"}`,
  );
  const [model, setModel] = useState("");
  const [agent, setAgent] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const d = dashboard ? (data.value as Dashboard) : undefined;
  const usage = d?.usage || (data.value as Usage | undefined);
  const groups =
    usage?.groups?.filter(
      (g) =>
        (!model || g.model_ref === model) &&
        (!agent || g.agent_ref === agent) &&
        (!from || g.utc_day >= from) &&
        (!to || g.utc_day <= to),
    ) || [];
  const groupTokens = groups.reduce(
    (n, g) => n + (g.reported_tokens?.total_tokens || 0),
    0,
  );
  const known = groups.some((g) => g.reported_tokens !== null);
  return (
    <Panel title={dashboard ? "实验仪表板" : "模型调用用量"}>
      <div className="console-actions">
        <button onClick={data.refresh}>刷新记录</button>
        <Link href={`/workspace/${id(experiment)}`}>查看实验记录 →</Link>
        <Link href={`/traces/${id(experiment)}`}>查看调用轨迹 →</Link>
      </div>
      <p className="muted">
        统计范围：当前用户在此实验中的 Agent 调用。时间按 UTC
        日分组，未知用量和费用不计为零；设备计数不代表在线状态。
      </p>
      <Result {...data} retry={data.refresh}>
        {d && (
          <>
            <div className="metric-grid">
              {[
                ["执行状态", d.runs_by_state],
                ["审批状态", d.approvals_by_state],
                ["数据状态", d.datasets_by_state],
              ].map(([title, states]) => (
                <article key={String(title)}>
                  <h3>{String(title)}</h3>
                  {Object.entries(states as Record<string, number>).map(
                    ([s, n]) => (
                      <p key={s}>
                        <Status value={s} /> <b>{n}</b>
                      </p>
                    ),
                  )}
                  <Link href={`/workspace/${id(experiment)}`}>核对明细 →</Link>
                </article>
              ))}
            </div>
            <p>
              设备范围 {d.instruments.length} 台 · 事件游标 {d.event_cursor}
            </p>
          </>
        )}
        <div className="metric-grid">
          <article>
            <small>逻辑请求</small>
            <strong>{usage?.logical_requests ?? "未知"}</strong>
          </article>
          <article>
            <small>未决请求</small>
            <strong>{usage?.unresolved_requests ?? "未知"}</strong>
          </article>
          <article>
            <small>费用估算</small>
            <strong>未知</strong>
          </article>
        </div>
        <div className="console-actions">
          <label>
            模型筛选
            <select value={model} onChange={(e) => setModel(e.target.value)}>
              <option value="">全部模型</option>
              {[...new Set(usage?.groups.map((g) => g.model_ref))].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <label>
            Agent 筛选
            <select value={agent} onChange={(e) => setAgent(e.target.value)}>
              <option value="">全部 Agent</option>
              {[...new Set(usage?.groups.map((g) => g.agent_ref))].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <label>
            起始日期（UTC）
            <input
              type="date"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
          </label>
          <label>
            结束日期（UTC）
            <input
              type="date"
              value={to}
              min={from}
              onChange={(e) => setTo(e.target.value)}
            />
          </label>
        </div>
        <p>
          筛选后已报告 Token：
          <strong>{known ? groupTokens.toLocaleString() : "未知"}</strong> ·
          未返回用量的完成调用：
          {groups.reduce((n, g) => n + g.unknown_usage, 0)}
        </p>
        <div className="console-table">
          <table>
            <thead>
              <tr>
                <th>日期 / 供应商</th>
                <th>模型 / Agent</th>
                <th>完成 / 已记录尝试</th>
                <th>已报告 Token</th>
                <th>未知用量</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g, i) => (
                <tr key={i}>
                  <td>
                    {g.utc_day}
                    <small>{g.vendor || "未知"}</small>
                  </td>
                  <td>
                    {g.model_ref}
                    <small>{g.agent_ref}</small>
                    {g.agent_run_ids.map((run) => (
                      <small key={run}>
                        <Link href={`/traces/${id(experiment)}/${id(run)}`}>
                          核对 Run {run.slice(0, 8)} →
                        </Link>
                      </small>
                    ))}
                  </td>
                  <td>
                    {g.model_completions} / {g.recorded_attempts}
                  </td>
                  <td>{g.reported_tokens?.total_tokens ?? "未知"}</td>
                  <td>{g.unknown_usage}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!groups.length && <Empty title="此筛选范围没有完成调用记录" />}
        <details>
          <summary>核对本次统计原始记录</summary>
          <JsonView value={usage} />
        </details>
      </Result>
    </Panel>
  );
}
function Traces({
  client,
  experiment,
  initialRun = "",
}: {
  client: Client;
  experiment: string;
  initialRun?: string;
}) {
  const [cursor, setCursor] = useState("");
  const [run, setRun] = useState(initialRun);
  const [tab, setTab] = useState("llm");
  const runs = useResource<{ items: AgentRun[] }>(
    client,
    `/experiments/${id(experiment)}/agent-runs?limit=20&cursor=${id(cursor)}`,
  );
  const trace = useResource<{
    items: { seq: number; event: RecordValue; occurred_at: string }[];
  }>(client, run ? `/agent-runs/${id(run)}/trace` : null);
  const snapshot = useResource<Snapshot>(
    client,
    tab === "gateway" ? `/experiments/${id(experiment)}/snapshot` : null,
  );
  return (
    <Panel title="实验关联轨迹">
      <p className="muted">
        LLM 与工具记录限当前用户可见的 Agent
        Run。设备标签显示命令台账，不提供原始敏感通信报文。
      </p>
      <div className="console-actions">
        {[
          ["llm", "LLM"],
          ["tools", "工具 / MCP"],
          ["gateway", "仪器命令"],
        ].map(([v, label]) => (
          <button key={v} aria-pressed={tab === v} onClick={() => setTab(v)}>
            {label}
          </button>
        ))}
      </div>
      {tab === "gateway" ? (
        <Result {...snapshot} retry={snapshot.refresh}>
          {snapshot.value?.commands.map((c) => (
            <article className="console-row" key={c.id}>
              <strong>{c.id}</strong>
              <Status value={c.state} />
              <p>
                Run {c.run_id} · Task {c.task_id} · 版本 {c.state_version}
              </p>
              <Link href={`/workspace/${id(experiment)}`}>查看实验依据</Link>
            </article>
          ))}
          {!snapshot.value?.commands.length && <Empty title="暂无命令台账" />}
        </Result>
      ) : (
        <>
          <Result {...runs} retry={runs.refresh}>
            <label>
              Agent Run
              <select value={run} onChange={(e) => setRun(e.target.value)}>
                <option value="">选择运行记录</option>
                {runs.value?.items.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.definition_ref} · {r.status} · {r.id}
                  </option>
                ))}
              </select>
            </label>
            <div className="console-actions">
              <button onClick={() => setCursor("")} disabled={!cursor}>
                首页
              </button>
              <button
                disabled={runs.value?.items.length !== 20}
                onClick={() => {
                  setCursor(runs.value!.items.at(-1)!.id);
                  setRun("");
                }}
              >
                下一页运行
              </button>
            </div>
          </Result>
          {run && (
            <Result {...trace} retry={trace.refresh}>
              {trace.value?.items
                .filter((t) =>
                  tab === "llm"
                    ? String(t.event.type).startsWith("model_")
                    : !String(t.event.type).startsWith("model_"),
                )
                .map((t) => (
                  <article className="console-row" key={t.seq}>
                    <strong>
                      #{t.seq} · {String(t.event.type)}
                    </strong>
                    <Time value={t.occurred_at} />
                    <JsonView value={t.event} />
                  </article>
                ))}
              {!trace.value?.items.length && <Empty title="尚无轨迹" />}
            </Result>
          )}
        </>
      )}
    </Panel>
  );
}
