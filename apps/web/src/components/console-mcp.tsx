"use client";
import { useState } from "react";
import { Client, id } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { Field, RecordValue } from "@/lib/console";
import { Empty, Status } from "./common";
import {
  ActionButton,
  Editor,
  JsonView,
  Panel,
  Result,
} from "./console-common";
const fields: Field[] = [
  { key: "id", label: "MCP 连接标识" },
  { key: "version", label: "版本", type: "number" },
  { key: "url", label: "Streamable HTTP 地址" },
  { key: "address", label: "固定服务器 IP" },
  { key: "secret_ref", label: "认证凭据引用", optional: true },
  { key: "timeout", label: "请求时限（秒）", type: "number", max: 60 },
  {
    key: "response_limit",
    label: "响应上限（字节）",
    type: "number",
    min: 1024,
    max: 1048576,
  },
];
export function MCP({ client }: { client: Client }) {
  const data = useResource<{
    connections: { ref: string; enabled: boolean; config: RecordValue }[];
    tools: {
      id: string;
      name: string;
      connection_ref: string;
      current: boolean;
      spec_hash: string;
    }[];
  }>(client, "/mcp");
  const [result, setResult] = useState<RecordValue>();
  const [tool, setTool] = useState("");
  const [actor, setActor] = useState("");
  const [experiment, setExperiment] = useState("");
  const [resources, setResources] = useState("");
  const [filter, setFilter] = useState("");
  const grant = {
    actor_id: actor,
    experiment_id: experiment,
    resources: resources
      .split(/[,，]/)
      .map((x) => x.trim())
      .filter(Boolean),
  };
  return (
    <>
      <Panel title="MCP 连接与工具授权">
        <p className="muted">
          发现工具不授予权限。只读性质需管理员核实，未知或物理写工具不得授权给
          Agent。
        </p>
        <div className="console-actions">
          <label>
            当前列表搜索
            <input value={filter} onChange={(e) => setFilter(e.target.value)} />
          </label>
          <button onClick={data.refresh}>刷新</button>
        </div>
        <Result {...data} retry={data.refresh}>
          {data.value?.connections
            .filter((c) => c.ref.includes(filter))
            .map((c) => (
              <article className="console-row" key={c.ref}>
                <h3>{c.ref}</h3>
                <Status value={c.enabled ? "ENABLED" : "DISABLED"} />
                <JsonView value={c.config} />
                <div className="console-actions">
                  <ActionButton
                    client={client}
                    disabled={!c.enabled}
                    path={`/mcp/${id(c.ref)}/discover`}
                    label="连接测试与工具发现"
                    impact="连接配置的 MCP 服务并读取工具目录，不调用业务工具。目录变更后必须重新核实授权。"
                    onDone={(r) => {
                      setResult(r);
                      data.refresh();
                    }}
                  />
                  {c.enabled && (
                    <ActionButton
                      client={client}
                      path={`/mcp/${id(c.ref)}/disable`}
                      label="禁用 MCP"
                      onDone={data.refresh}
                    />
                  )}
                </div>
              </article>
            ))}
          {data.value?.connections.length === 0 && (
            <Empty title="尚无 MCP 连接" />
          )}
          <h3>已发现工具</h3>
          <div className="console-cards">
            {data.value?.tools
              .filter((t) => `${t.name} ${t.connection_ref}`.includes(filter))
              .map((t) => (
                <article key={t.id}>
                  <strong>{t.name}</strong>
                  <small>{t.connection_ref}</small>
                  <Status value={t.current ? "CURRENT" : "STALE"} />
                  <code>{t.spec_hash}</code>
                  <button onClick={() => setTool(t.id)}>核实授权范围</button>
                </article>
              ))}
          </div>
        </Result>
        {result && (
          <details open>
            <summary>发现结果与 Schema</summary>
            <JsonView value={result} />
          </details>
        )}
        {tool && (
          <Panel title="逐工具人工授权">
            <p>工具 ID：{tool}</p>
            <div className="console-fields">
              <label>
                使用者身份
                <input
                  value={actor}
                  onChange={(e) => setActor(e.target.value)}
                />
              </label>
              <label>
                所属实验
                <input
                  value={experiment}
                  onChange={(e) => setExperiment(e.target.value)}
                />
              </label>
              <label>
                资源范围（逗号分隔）
                <input
                  value={resources}
                  onChange={(e) => setResources(e.target.value)}
                />
              </label>
            </div>
            <div className="console-actions">
              <ActionButton
                disabled={!actor || !experiment}
                client={client}
                path={`/mcp/tools/${id(tool)}/grant`}
                body={grant}
                label="批准只读工具"
                impact="确认已核实远端实现无物理写副作用。授权绑定此 Schema、使用者、实验与资源；Agent 仍须绑定返回的工具版本。"
                onDone={setResult}
              />
              <ActionButton
                disabled={!actor || !experiment}
                client={client}
                path={`/mcp/tools/${id(tool)}/revoke`}
                body={grant}
                label="撤销工具授权"
                onDone={setResult}
              />
            </div>
          </Panel>
        )}
      </Panel>
      <Panel title="新增 MCP 连接版本">
        <Editor
          client={client}
          path="/mcp"
          fields={fields}
          initial={{
            version: 1,
            timeout: 10,
            response_limit: 1048576,
            allow_loopback: false,
          }}
          title="固定地址连接"
          onDone={data.refresh}
        />
      </Panel>
    </>
  );
}
