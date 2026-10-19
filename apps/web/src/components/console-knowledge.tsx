"use client";
import { useState } from "react";
import { Client, id } from "@/lib/api";
import { useResource, useAction } from "@/lib/hooks";
import type { Field } from "@/lib/console";
import { Empty, Problem } from "./common";
import { ActionButton, Editor, Panel, Result } from "./console-common";
import { ExperimentChoice } from "./console-observe";
type SourceRow = {
  reference: { id: string; hash: string };
  source_id: string;
  version: number;
  source_uri: string;
  content: string;
  kind: string;
  trust: string;
};
const fields: Field[] = [
  { key: "source_id", label: "知识来源标识" },
  { key: "version", label: "来源版本", type: "number" },
  { key: "kind", label: "来源类型", choices: ["document", "memory"] },
  { key: "source_uri", label: "来源地址或说明" },
  { key: "resources", label: "设备范围（逗号分隔）", type: "list" },
  { key: "agent_ref", label: "限定 Agent 版本", optional: true },
  { key: "content", label: "文档或记忆内容", type: "area" },
];
export function Knowledge({ client }: { client: Client }) {
  const [experiment, setExperiment] = useState("");
  return (
    <>
      <ExperimentChoice
        client={client}
        selected={experiment}
        onChange={setExperiment}
      />
      {experiment ? (
        <Sources key={experiment} client={client} experiment={experiment} />
      ) : (
        <Empty title="选择实验后管理知识来源" />
      )}
    </>
  );
}
function Sources({
  client,
  experiment,
}: {
  client: Client;
  experiment: string;
}) {
  const [agent, setAgent] = useState("");
  const [limit, setLimit] = useState(20);
  const [recipient, setRecipient] = useState("");
  const [query, setQuery] = useState("");
  const [resources, setResources] = useState("");
  const [found, setFound] = useState<SourceRow[]>();
  const search = useAction();
  const data = useResource<{ items: SourceRow[] }>(
    client,
    `/experiments/${id(experiment)}/knowledge?limit=${limit}${agent ? `&agent_ref=${id(agent)}` : ""}`,
  );
  return (
    <>
      <Panel title="知识与记忆来源">
        <p className="muted">
          来源内容是检索证据，不构成操作授权。当前使用文本检索，无后台向量索引；共享与停用仅允许来源所有者操作。
        </p>
        <div className="console-actions">
          <label>
            Agent 作用域
            <input
              value={agent}
              onChange={(e) => {
                setAgent(e.target.value);
                setFound(undefined);
              }}
            />
          </label>
          <button
            onClick={() => {
              data.refresh();
              setFound(undefined);
            }}
          >
            刷新来源
          </button>
        </div>
        <form
          className="console-form"
          onSubmit={(e) => {
            e.preventDefault();
            void search.act(async () => {
              setFound(undefined);
              const result = await client.mutate<{ items: SourceRow[] }>(
                "/knowledge/search",
                {
                  experiment_id: experiment,
                  query,
                  resources: resources
                    .split(/[,，]/)
                    .map((x) => x.trim())
                    .filter(Boolean),
                  ...(agent ? { agent_ref: agent } : {}),
                },
              );
              setFound(result.items);
            });
          }}
        >
          <h3>检索证据</h3>
          <div className="console-fields">
            <label>
              检索文本
              <input
                required
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <label>
              检索设备范围
              <input
                value={resources}
                onChange={(e) => setResources(e.target.value)}
              />
            </label>
          </div>
          <button disabled={search.busy}>检索</button>
          <Problem error={search.error} />
        </form>
        <label>
          共享或撤销的使用者身份
          <input
            value={recipient}
            onChange={(e) => setRecipient(e.target.value)}
          />
        </label>
        <Result {...data} retry={data.refresh}>
          {(found || data.value?.items)?.map((s) => (
            <article className="console-row" key={s.reference.id}>
              <h3>
                {s.source_id}@{s.version}
              </h3>
              <p>
                {s.kind} · {s.source_uri}
              </p>
              <small>内容 hash：{s.reference.hash}</small>
              <blockquote className="knowledge-content">{s.content}</blockquote>
              <div className="console-actions">
                <ActionButton
                  disabled={!recipient}
                  client={client}
                  path={`/knowledge/${id(s.reference.id)}/share`}
                  body={{ actor_id: recipient, revoked: false }}
                  label="共享来源"
                  impact={`将此版本内容共享给 ${recipient}，对方仍需具备当前实验与设备权限。`}
                />
                <ActionButton
                  disabled={!recipient}
                  client={client}
                  path={`/knowledge/${id(s.reference.id)}/share`}
                  body={{ actor_id: recipient, revoked: true }}
                  label="撤销来源访问"
                />
                <ActionButton
                  client={client}
                  path={`/knowledge/${id(s.reference.id)}/disable`}
                  label="停用来源"
                  onDone={() => {
                    data.refresh();
                    setFound(undefined);
                  }}
                />
              </div>
            </article>
          ))}
          {(found || data.value?.items)?.length === 0 && (
            <Empty title="没有可见来源" />
          )}
          <button
            disabled={limit >= 100 || data.value?.items.length !== limit}
            onClick={() => setLimit((n) => Math.min(n + 20, 100))}
          >
            显示更多（最多 100 条）
          </button>
        </Result>
      </Panel>
      <Panel title="导入新来源版本">
        <Editor
          client={client}
          path={`/experiments/${id(experiment)}/knowledge`}
          fields={fields}
          initial={{ version: 1, kind: "document", resources: [] }}
          title="文档或记忆"
          label="导入来源"
          onDone={() => {
            data.refresh();
            setFound(undefined);
          }}
        />
      </Panel>
    </>
  );
}
