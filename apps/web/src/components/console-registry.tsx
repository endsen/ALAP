"use client";
import Link from "next/link";
import { useState } from "react";
import { Client, id } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import {
  differences,
  type Field,
  type RecordValue,
  type RegistryRow,
} from "@/lib/console";
import { Empty, Status, Time } from "./common";
import {
  ActionButton,
  Editor,
  JsonView,
  Panel,
  Result,
} from "./console-common";
const agentFields: Field[] = [
  { key: "manifest.agent_id", label: "Agent 标识" },
  { key: "manifest.version", label: "配置版本", type: "number" },
  {
    key: "manifest.kind",
    label: "角色",
    choices: ["planner", "instrument", "analysis"],
  },
  { key: "manifest.model_ref", label: "模型版本引用" },
  {
    key: "manifest.system_prompt_ref",
    label: "指令策略",
    choices: ["alap-policy@1"],
  },
  {
    key: "manifest.allowed_tools",
    label: "工具授权（逗号分隔版本引用）",
    type: "list",
  },
  {
    key: "manifest.skill_refs",
    label: "Skills 绑定（逗号分隔版本引用）",
    type: "list",
  },
  {
    key: "manifest.scoped_experiments",
    label: "实验作用域（逗号分隔）",
    type: "list",
  },
  {
    key: "manifest.scoped_instruments",
    label: "设备作用域（逗号分隔）",
    type: "list",
  },
  {
    key: "manifest.context_policy",
    label: "上下文策略",
    choices: ["experiment_snapshot_only", "scoped_knowledge"],
  },
  { key: "manifest.autonomy_level", label: "自主级别", choices: ["L0", "L1"] },
  {
    key: "manifest.max_iterations",
    label: "最大迭代次数",
    type: "number",
    max: 100,
  },
  {
    key: "manifest.max_runtime_seconds",
    label: "运行时限（秒）",
    type: "number",
    max: 86400,
  },
  { key: "token_budget", label: "Token 预算", type: "number" },
  { key: "context_bytes", label: "上下文上限（字节）", type: "number" },
  { key: "max_tool_calls", label: "最大工具调用数", type: "number" },
];
const skillFields: Field[] = [
  { key: "skill_id", label: "Skill 标识" },
  { key: "version", label: "配置版本", type: "number" },
  { key: "kind", label: "技能类型", choices: ["instruction", "execution"] },
  { key: "content", label: "指令与操作知识", type: "area" },
  { key: "source", label: "来源" },
  { key: "owner", label: "维护者" },
  { key: "executor", label: "执行主体", choices: ["context", "engine"] },
  {
    key: "side_effect",
    label: "副作用",
    choices: ["none", "proposal", "physical_write"],
  },
  { key: "dependencies", label: "依赖版本", type: "list" },
  { key: "required_tools", label: "所需工具版本", type: "list" },
  { key: "required_scopes", label: "所需权限", type: "list" },
  { key: "resources", label: "设备范围", type: "list" },
  { key: "input_schema", label: "输入 Schema", type: "json" },
  { key: "output_schema", label: "输出 Schema", type: "json" },
  { key: "preconditions", label: "前置条件", type: "list" },
  { key: "success_criteria", label: "成功判据" },
];
const agentInitial: RecordValue = {
  manifest: {
    schema_version: "2.0",
    agent_id: "",
    version: 1,
    kind: "planner",
    model_ref: "",
    system_prompt_ref: "alap-policy@1",
    allowed_tools: [],
    skill_refs: [],
    scoped_experiments: [],
    scoped_instruments: [],
    context_policy: "experiment_snapshot_only",
    autonomy_level: "L1",
    max_iterations: 8,
    max_runtime_seconds: 120,
  },
  token_budget: 8192,
  context_bytes: 64000,
  max_tool_calls: 12,
};
const skillInitial: RecordValue = {
  schema_version: "1.0",
  skill_id: "",
  version: 1,
  kind: "instruction",
  content: "",
  source: "",
  owner: "",
  executor: "context",
  side_effect: "none",
  dependencies: [],
  required_tools: [],
  required_scopes: [],
  resources: [],
  input_schema: { type: "object" },
  output_schema: { type: "object" },
  preconditions: [],
  success_criteria: "",
};
export function Registry({
  client,
  kind,
  selected,
}: {
  client: Client;
  kind: "agents" | "skills";
  selected?: string;
}) {
  const [cursor, setCursor] = useState("");
  const [history, setHistory] = useState<string[]>([]);
  const [filter, setFilter] = useState("");
  const [state, setState] = useState("");
  const [draft, setDraft] = useState<RecordValue>();
  const [editorKey, setEditorKey] = useState(0);
  const [comparison, setComparison] = useState("");
  const page = useResource<{ items: RegistryRow[] }>(
    client,
    `/${kind}?limit=20&cursor=${id(cursor)}`,
  );
  const detail = useResource<RegistryRow>(
    client,
    selected ? `/${kind}/${id(selected)}` : null,
  );
  const compare = useResource<RegistryRow>(
    client,
    comparison ? `/${kind}/${id(comparison)}` : null,
  );
  const tools = useResource<{ items: RecordValue[] }>(
    client,
    kind === "agents" ? "/platform/tools" : null,
  );
  const models = useResource<{ items: { ref: string; enabled: boolean }[] }>(
    client,
    kind === "agents" ? "/models" : null,
  );
  const row = detail.value;
  const title = kind === "agents" ? "Agent" : "Skills";
  const initial = draft || (kind === "agents" ? agentInitial : skillInitial);
  function copy(row: RegistryRow) {
    const next = structuredClone(row.document);
    if (kind === "agents") {
      const m = next.manifest as RecordValue;
      m.version = Number(m.version) + 1;
      delete m.config_hash;
    } else next.version = Number(next.version) + 1;
    setDraft(next);
    setEditorKey((k) => k + 1);
  }
  return (
    <>
      <Panel title={`${title} 版本目录`}>
        <p className="muted">
          发布后固定配置与权限。禁用阻止新调用；已执行设备任务仍走受控停止流程。
        </p>
        <div className="console-actions">
          <label>
            当前页搜索
            <input value={filter} onChange={(e) => setFilter(e.target.value)} />
          </label>
          <label>
            状态筛选
            <select value={state} onChange={(e) => setState(e.target.value)}>
              <option value="">全部状态</option>
              {["DRAFT", "PUBLISHED", "DISABLED"].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <button onClick={page.refresh}>刷新目录</button>
        </div>
        <Result {...page} retry={page.refresh}>
          <div className="console-cards">
            {page.value?.items
              .filter(
                (r) =>
                  r.ref.toLowerCase().includes(filter.toLowerCase()) &&
                  (!state || r.state === state),
              )
              .map((r) => (
                <article key={r.ref}>
                  <Link href={`/${kind}/${id(r.ref)}`}>
                    <strong>{r.ref}</strong>
                  </Link>
                  <Status value={r.state} />
                  <small>
                    {kind === "agents"
                      ? String((r.document.manifest as RecordValue).kind)
                      : `${r.document.kind} / ${r.document.executor}`}
                  </small>
                  <code title={r.content_hash}>
                    {r.content_hash.slice(0, 16)}…
                  </code>
                </article>
              ))}
          </div>
          {page.value?.items.length === 0 && <Empty title="尚无版本" />}
          <div className="console-actions">
            <button
              disabled={!history.length}
              onClick={() => {
                setCursor(history.at(-1)!);
                setHistory((h) => h.slice(0, -1));
              }}
            >
              上一页
            </button>
            <button
              disabled={page.value?.items.length !== 20}
              onClick={() => {
                setHistory((h) => [...h, cursor]);
                setCursor(page.value!.items.at(-1)!.ref);
              }}
            >
              下一页
            </button>
          </div>
        </Result>
      </Panel>
      {selected && (
        <Panel title={`版本详情 · ${selected}`}>
          <Result {...detail} retry={detail.refresh}>
            {row && (
              <>
                <Status value={row.state} />
                <p>
                  发布者：{row.publisher || "尚未发布"} · 验证时间：
                  <Time value={row.validated_at} />
                </p>
                <p className="muted">内容 hash：{row.content_hash}</p>
                <div className="console-actions">
                  {row.state === "DRAFT" && (
                    <>
                      <ActionButton
                        client={client}
                        path={`/${kind}/${id(row.ref)}/validate`}
                        label="发布前校验"
                        confirm={false}
                        impact="仅校验配置，不调用模型或设备。"
                      />
                      <ActionButton
                        client={client}
                        path={`/${kind}/${id(row.ref)}/publish`}
                        label="发布版本"
                        impact={`发布 ${row.ref}。新运行可绑定该版本；已有运行不切换配置。`}
                        onDone={() => {
                          detail.refresh();
                          page.refresh();
                        }}
                      />
                    </>
                  )}
                  {row.state !== "DISABLED" && (
                    <ActionButton
                      client={client}
                      path={`/${kind}/${id(row.ref)}/disable`}
                      label="禁用版本"
                      impact={`禁用 ${row.ref} 将阻止新的调用，不会直接停止已发出的设备命令。`}
                      onDone={() => {
                        detail.refresh();
                        page.refresh();
                      }}
                    />
                  )}
                  <button onClick={() => copy(row)}>基于此版本修订</button>
                </div>
                <details open>
                  <summary>配置、授权与预算</summary>
                  <JsonView value={row.document} />
                </details>
                <label>
                  比较版本引用
                  <input
                    value={comparison}
                    onChange={(e) => setComparison(e.target.value)}
                    placeholder="例如 planner@1"
                  />
                </label>
                {comparison && (
                  <Result {...compare} retry={compare.refresh}>
                    {compare.value && (
                      <pre className="console-json">
                        {differences(compare.value.document, row.document).join(
                          "\n",
                        ) || "两个版本内容一致"}
                      </pre>
                    )}
                  </Result>
                )}
                {kind === "agents" && row.state === "PUBLISHED" && (
                  <AgentTrial client={client} reference={row.ref} />
                )}
                {kind === "agents" && (
                  <Link href="/traces">查看实验中的运行记录与轨迹 →</Link>
                )}
              </>
            )}
          </Result>
        </Panel>
      )}
      <Panel title={`创建 ${title} 草稿`}>
        {kind === "agents" && (
          <details>
            <summary>可绑定的模型和工具版本</summary>
            <p>
              模型：
              {models.value?.items
                .filter((r) => r.enabled)
                .map((r) => r.ref)
                .join("、") || "暂无已启用模型"}
            </p>
            <JsonView value={tools.value?.items || []} />
          </details>
        )}
        <Editor
          key={editorKey}
          client={client}
          path={`/${kind}`}
          title="版本化配置"
          initial={initial}
          fields={kind === "agents" ? agentFields : skillFields}
          label="保存草稿"
          onDone={page.refresh}
        />
        <p className="muted">
          指令策略固定为 alap-policy@1；操作知识可通过 instruction Skills
          维护。执行技能由引擎执行，导入不安装代码。
        </p>
      </Panel>
    </>
  );
}

function AgentTrial({
  client,
  reference,
}: {
  client: Client;
  reference: string;
}) {
  const [experiment, setExperiment] = useState("");
  const [goal, setGoal] = useState("");
  const [run, setRun] = useState<RecordValue>();
  const finished =
    run &&
    ["COMPLETED", "FAILED", "CANCELLED", "NEEDS_ATTENTION"].includes(
      String(run.status),
    );
  return (
    <Panel title="受控 Agent 测试">
      <p className="muted">
        在有权限的实验中创建运行，锁定此配置版本。推进可能调用真实模型并产生费用；结果只是提案，不会批准或执行设备命令。
      </p>
      <div className="console-fields">
        <label>
          测试实验 ID
          <input
            value={experiment}
            onChange={(e) => setExperiment(e.target.value)}
          />
        </label>
        <label>
          测试目标
          <input value={goal} onChange={(e) => setGoal(e.target.value)} />
        </label>
      </div>
      <ActionButton
        client={client}
        path="/agent-runs"
        label="创建测试运行"
        body={{ experiment_id: experiment, definition_ref: reference, goal }}
        disabled={!experiment || !goal || !!run}
        impact={`在 ${experiment} 创建绑定 ${reference} 的 Agent 运行。`}
        onDone={setRun}
      />
      {run && (
        <>
          <Status value={String(run.status)} />
          {!!run.cancel_requested && !finished && (
            <p role="status">
              已请求取消，等待后台确认；可在运行轨迹查看最新状态。
            </p>
          )}
          <JsonView value={run} />
          <div className="console-actions">
            <ActionButton
              client={client}
              path={`/agent-runs/${id(String(run.id))}/advance`}
              label="推进测试一步"
              disabled={!!finished || !!run.cancel_requested}
              impact="本步骤可能调用配置的模型及已授权只读/提案工具，受到此版本预算限制。"
              onDone={setRun}
            />
            <ActionButton
              client={client}
              path={`/agent-runs/${id(String(run.id))}/cancel`}
              label="取消 Agent 测试"
              disabled={!!finished || !!run.cancel_requested}
              onDone={setRun}
            />
            <Link href={`/traces/${id(experiment)}/${id(String(run.id))}`}>
              查看此次测试轨迹 →
            </Link>
          </div>
        </>
      )}
    </Panel>
  );
}
