"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { APIError, Client, id } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import type {
  Experiment,
  Identity,
  Instrument,
  Manifest,
  Series,
} from "@/lib/types";
import { Empty, Loading, Plot, Problem, Status, Time } from "./common";
import { ExperimentWorkspace } from "./experiment";
import { ConsolePage } from "./console";
import { consoleNav } from "@/lib/console";

const nav = [
  ["/experiments", "◫", "实验"],
  ["/approvals", "✓", "计划审批"],
  ["/instruments", "⌁", "设备"],
  ["/data", "↗", "数据"],
] as const;
export function WorkspaceApp() {
  const [session, setSession] = useState<{
    client: Client;
    identity: Identity;
  }>();
  const pathname = usePathname();
  if (!session)
    return <Login entered={setSession} expired={() => setSession(undefined)} />;
  const parts = pathname.split("/").filter(Boolean).map(decodeURIComponent);
  const workspace =
    (parts[0] === "workspace" || parts[0] === "experiments") &&
    parts.length > 1;
  const title = workspace
    ? "实验工作区"
    : nav.find((n) => n[0] === "/" + parts[0])?.[2] ||
      consoleNav.find((n) => n[0] === parts[0])?.[2] ||
      "实验";
  return (
    <div className="app-shell">
      <a className="skip" href="#main">
        跳转到内容
      </a>
      <aside className="sidebar">
        <Link className="brand" href="/experiments">
          <span className="brand-icon">A</span>
          <span>
            ALAP<small>LABORATORY AGENT</small>
          </span>
        </Link>
        <div className="nav-caption">实验工作台</div>
        <nav>
          {nav.map(([path, icon, label]) => (
            <Link
              key={path}
              className={
                pathname.startsWith(path) ||
                (path === "/experiments" && workspace)
                  ? "selected"
                  : ""
              }
              href={path}
            >
              <span aria-hidden>{icon}</span>
              {label}
              {label === "实验" && <b>↗</b>}
            </Link>
          ))}
        </nav>
        <details className="console-nav" open>
          <summary>平台与观测</summary>
          <nav>
            {consoleNav
              .filter((n) => !n[3] || session.identity.role === "admin")
              .map(([route, icon, label]) => (
                <Link
                  key={route}
                  href={`/${route}`}
                  className={parts[0] === route ? "selected" : ""}
                >
                  <span aria-hidden>{icon}</span>
                  {label}
                </Link>
              ))}
          </nav>
        </details>
        <div className="sidebar-bottom">
          <span className="dot" />
          受控实验 · 人工审批<p>Agent 提议，授权后执行</p>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <span>
            工作台 <i>/</i> <b>{title}</b>
          </span>
          <div className="identity">
            <span className="avatar">
              {session.identity.id.slice(0, 1).toUpperCase()}
            </span>
            <span>
              {session.identity.id}
              <small>{session.identity.role}</small>
            </span>
            <button className="subtle" onClick={() => setSession(undefined)}>
              退出
            </button>
          </div>
        </header>
        <main id="main" key={pathname}>
          {consoleNav.some((n) => n[0] === parts[0]) ? (
            <ConsolePage
              client={session.client}
              identity={session.identity}
              parts={parts}
            />
          ) : workspace ? (
            <ExperimentWorkspace
              client={session.client}
              experiment={parts[1]}
              initialTab={parts[2] === "studio" ? "plan" : "chat"}
            />
          ) : parts[0] === "instruments" ? (
            <Instruments client={session.client} instrument={parts[1]} />
          ) : parts[0] === "data" && parts[1] ? (
            <Dataset client={session.client} dataset={parts[1]} />
          ) : (
            <Experiments
              client={session.client}
              identity={session.identity}
              mode={
                parts[0] === "approvals"
                  ? "approvals"
                  : parts[0] === "data"
                    ? "data"
                    : "experiments"
              }
            />
          )}
        </main>
        <footer>
          ALAP / 专用实验 Agent 平台 <span>数据与状态以服务器记录为准</span>
        </footer>
      </div>
    </div>
  );
}
function Login({
  entered,
  expired,
}: {
  entered: (s: { client: Client; identity: Identity }) => void;
  expired: () => void;
}) {
  const [token, setToken] = useState("");
  const action = useAction();
  return (
    <div className="login-page">
      <div className="login-story">
        <div className="brand">
          <span className="brand-icon">A</span>ALAP
        </div>
        <p className="eyebrow">AUTONOMOUS LABORATORY AGENT PLATFORM</p>
        <h1>
          实验，从一个
          <br />
          问题开始。
        </h1>
        <p>
          让专用 Agent 协助规划，
          <br />
          让每一步执行都有依据。
        </p>
        <div className="orb">
          <span>PLAN</span>
          <b>◇</b>
          <span>VERIFY</span>
        </div>
        <small>规划 · 审核 · 执行 · 复盘</small>
      </div>
      <section className="login-panel">
        <span className="eyebrow">WORKSPACE ACCESS</span>
        <h2>进入实验工作区</h2>
        <p className="muted">使用管理员签发的平台访问令牌登录。</p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void action.act(async () => {
              const client = new Client(token.trim(), expired);
              const identity = await client.read<Identity>("/me");
              setToken("");
              entered({ client, identity });
            });
          }}
        >
          <label>
            平台访问令牌
            <input
              type="password"
              autoComplete="off"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              required
              placeholder="粘贴平台令牌"
            />
          </label>
          <Problem error={action.error} />
          <button className="primary" disabled={action.busy || !token.trim()}>
            {action.busy ? "正在验证…" : "进入工作区 →"}
          </button>
        </form>
        <small>
          这是平台登录令牌，不是 LLM API 密钥。
          <br />
          仅保留在当前页面会话，刷新后需重新登录。
        </small>
      </section>
    </div>
  );
}
function Experiments({
  client,
  identity,
  mode,
}: {
  client: Client;
  identity: Identity;
  mode: "experiments" | "approvals" | "data";
}) {
  const router = useRouter();
  const [cursor, setCursor] = useState("");
  const [filter, setFilter] = useState("");
  const [creating, setCreating] = useState(false);
  const result = useResource<{
    items: Experiment[];
    next_cursor: string | null;
  }>(client, "/experiments?limit=20" + (cursor ? "&cursor=" + id(cursor) : ""));
  const samples = useResource<{
    items: { id: string; metadata: Record<string, unknown> }[];
  }>(client, "/samples");
  const action = useAction();
  const title =
    mode === "approvals" ? "计划审批" : mode === "data" ? "实验数据" : "实验";
  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">EXPERIMENT WORKSPACE</p>
          <h1>{title}</h1>
          <p className="muted">
            {mode === "experiments"
              ? "从目标到可追溯结果，管理每一次实验。"
              : "选择实验，查看当前授权范围内的记录。"}
          </p>
        </div>
        {mode === "experiments" &&
          ["admin", "researcher"].includes(identity.role) && (
            <button className="primary" onClick={() => setCreating(!creating)}>
              ＋ 新建实验
            </button>
          )}
      </div>
      {creating && (
        <section className="panel">
          <h2>新建实验</h2>
          <form
            className="form-grid"
            onSubmit={(e) => {
              e.preventDefault();
              const form = new FormData(e.currentTarget);
              void action.act(async () => {
                const exp = await client.mutate<Experiment>("/experiments", {
                  title: form.get("title"),
                  objective: form.get("objective"),
                  sample_id: form.get("sample"),
                });
                router.push("/workspace/" + id(exp.id));
              });
            }}
          >
            <label>
              实验名称
              <input
                name="title"
                required
                maxLength={200}
                placeholder="例如：零场 IV 响应测量"
              />
            </label>
            <label>
              样品
              <select name="sample" required defaultValue="">
                <option value="" disabled>
                  选择已有样品
                </option>
                {samples.value?.items.map((s) => (
                  <option key={s.id} value={s.id}>
                    {String(s.metadata.title || s.id)}
                  </option>
                ))}
              </select>
            </label>
            <label className="wide">
              研究目标
              <textarea
                name="objective"
                required
                maxLength={4000}
                placeholder="描述希望测量的现象与约束"
              />
            </label>
            <button
              className="primary"
              disabled={action.busy || !samples.value?.items.length}
            >
              创建实验
            </button>
            <button
              type="button"
              className="subtle"
              onClick={() => setCreating(false)}
            >
              收起
            </button>
          </form>
          {samples.value?.items.length === 0 && (
            <p>尚无样品。请先创建一个样品记录。</p>
          )}
          <SampleForm client={client} refresh={samples.refresh} />
          <Problem error={action.error} />
        </section>
      )}
      <div className="overview-strip">
        <span className="line-symbol">◈</span>
        <div>
          <strong>先规划，再审核，最后执行</strong>
          <p>候选提案不会直接操作设备。设备未知或请求结果不明时，请先核对。</p>
        </div>
        <span className="outline-label">人工审批边界</span>
      </div>
      <section className="panel">
        <div className="section-heading">
          <h2>{mode === "experiments" ? "我的实验" : "选择实验"}</h2>
          <input
            aria-label="筛选实验"
            className="search"
            placeholder="搜索当前页名称或编号…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
        <Problem error={result.error} retry={result.refresh} />
        {result.loading ? (
          <Loading />
        ) : !result.value?.items.length ? (
          <Empty title="还没有可访问的实验">
            创建实验后，由管理员配置设备范围，即可开始规划。
          </Empty>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>实验名称 / 编号</th>
                  <th>状态</th>
                  <th>样品</th>
                  <th>创建时间</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {result.value.items
                  .filter((e) =>
                    (e.title + " " + e.id)
                      .toLowerCase()
                      .includes(filter.toLowerCase()),
                  )
                  .map((e) => (
                    <tr key={e.id}>
                      <td>
                        <Link
                          className="row-link"
                          href={`/workspace/${id(e.id)}${mode === "approvals" ? "?tab=plan" : mode === "data" ? "?tab=data" : ""}`}
                        >
                          {e.title || "未命名实验"}
                        </Link>
                        <small className="mono">{e.id}</small>
                      </td>
                      <td>
                        <Status value={e.state} />
                      </td>
                      <td>{e.sample_id}</td>
                      <td>
                        <Time value={e.created_at} />
                      </td>
                      <td>
                        <Link
                          className="arrow-link"
                          aria-label={`打开 ${e.title || e.id}`}
                          href={`/experiments/${id(e.id)}/studio`}
                        >
                          {mode === "approvals" ? "审核计划" : "查看计划"} ↗
                        </Link>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="pagination">
          <span>仅显示当前身份可访问的实验</span>
          {cursor && (
            <button className="subtle" onClick={() => setCursor("")}>
              返回首页
            </button>
          )}
          {result.value?.next_cursor && (
            <button
              className="subtle"
              onClick={() => setCursor(result.value!.next_cursor!)}
            >
              下一页 →
            </button>
          )}
        </div>
      </section>
    </div>
  );
}
function SampleForm({
  client,
  refresh,
}: {
  client: Client;
  refresh: () => void;
}) {
  const action = useAction();
  return (
    <details>
      <summary>添加样品记录</summary>
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault();
          const form = e.currentTarget;
          const data = new FormData(form);
          void action.act(async () => {
            await client.mutate("/samples", {
              id: crypto.randomUUID(),
              metadata: { title: data.get("title") },
            });
            form.reset();
            refresh();
          });
        }}
      >
        <label>
          样品名称
          <input name="title" required maxLength={100} />
        </label>
        <button disabled={action.busy}>保存样品</button>
      </form>
      <Problem error={action.error} />
    </details>
  );
}
function Instruments({
  client,
  instrument,
}: {
  client: Client;
  instrument?: string;
}) {
  const result = useResource<Instrument | Instrument[]>(
    client,
    instrument ? "/instruments/" + id(instrument) : "/instruments",
  );
  const items = result.value
    ? Array.isArray(result.value)
      ? result.value
      : [result.value]
    : [];
  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">INSTRUMENTS</p>
          <h1>{instrument ? "设备详情" : "设备"}</h1>
          <p className="muted">仅展示已授权设备；未知状态不代表可执行。</p>
        </div>
        <button onClick={result.refresh}>刷新状态</button>
      </div>
      <Problem error={result.error} retry={result.refresh} />
      {result.loading ? (
        <Loading />
      ) : !items.length ? (
        <Empty title="没有已授权的设备" />
      ) : (
        <div className="device-grid">
          {items.map((i) => (
            <section className="panel device" key={i.instrument_id}>
              <span className="device-icon">⌁</span>
              <Status value={i.status} />
              <h2>
                <Link href={"/instruments/" + id(i.instrument_id)}>
                  {i.instrument_id}
                </Link>
              </h2>
              <dl>
                <dt>网关</dt>
                <dd>{i.gateway_id}</dd>
                <dt>能力版本</dt>
                <dd>{i.capability_version || "未提供"}</dd>
                <dt>最新读回</dt>
                <dd>
                  <Time value={i.observed_at} />
                </dd>
                <dt>目标值</dt>
                <dd>见已审核计划</dd>
                <dt>实际值 / 鲜度</dt>
                <dd>
                  {i.observed_at ? "以设备读回为准" : "尚无可验证的新鲜读回"}
                </dd>
              </dl>
              <div className="notice">
                此页面只读。控制动作须经过实验计划与审批。
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
function Dataset({ client, dataset }: { client: Client; dataset: string }) {
  const [generation, setGeneration] = useState(0);
  return (
    <DatasetView
      key={`${dataset}:${generation}`}
      client={client}
      dataset={dataset}
      retry={() => setGeneration((value) => value + 1)}
    />
  );
}
function DatasetView({
  client,
  dataset,
  retry,
}: {
  client: Client;
  dataset: string;
  retry: () => void;
}) {
  const manifest = useResource<Manifest>(client, `/datasets/${id(dataset)}`);
  const series = useResource<Series>(
    client,
    manifest.value ? `/datasets/${id(dataset)}/series` : null,
  );
  const action = useAction();
  const denied = [manifest.error, series.error, action.error].find(
    (error) => error instanceof APIError && [401, 403].includes(error.status),
  );
  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">DATASET / VERIFIED ACQUISITION</p>
          <h1>数据查看</h1>
          <p className="mono muted">{dataset}</p>
        </div>
        <button
          className="primary"
          disabled={!!denied || !manifest.value || action.busy}
          onClick={() =>
            void action.act(() =>
              client.download(
                `/datasets/${id(dataset)}/download`,
                dataset + ".h5",
              ),
            )
          }
        >
          下载原始 HDF5 ↓
        </button>
      </div>
      <Problem error={denied || manifest.error} retry={retry} />
      {!denied && <Problem error={action.error} />}
      {denied ? null : manifest.loading ? (
        <Loading />
      ) : (
        manifest.value && (
          <>
            <section className="panel">
              <div className="section-heading">
                <h2>IV 测量曲线</h2>
                <Status value={manifest.value.status} />
              </div>
              <Problem error={series.error} retry={series.refresh} />
              {series.loading ? (
                <Loading />
              ) : (
                series.value && <Plot series={series.value} />
              )}
            </section>
            <section className="panel">
              <h2>来源与采集记录</h2>
              <dl>
                <dt>所属实验</dt>
                <dd>
                  <Link href={"/workspace/" + id(manifest.value.experiment_id)}>
                    {manifest.value.experiment_id}
                  </Link>
                </dd>
                <dt>采集时间窗</dt>
                <dd>
                  <Time value={manifest.value.acquisition_interval.start_utc} />{" "}
                  — <Time value={manifest.value.acquisition_interval.end_utc} />
                </dd>
                <dt>设备</dt>
                <dd>{manifest.value.instrument_ids.join(" · ")}</dd>
                <dt>Run / Task</dt>
                <dd>
                  {manifest.value.run_id} / {manifest.value.task_id}
                </dd>
                <dt>SHA-256</dt>
                <dd className="mono hash">{manifest.value.checksum_sha256}</dd>
              </dl>
            </section>
          </>
        )
      )}
    </div>
  );
}
