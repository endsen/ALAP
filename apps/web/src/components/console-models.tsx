"use client";
import { useState } from "react";
import { Client, id } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { ConfigRow, Field, RecordValue } from "@/lib/console";
import { Empty, Status } from "./common";
import {
  ActionButton,
  Editor,
  JsonView,
  Panel,
  Result,
} from "./console-common";
const connectionFields: Field[] = [
  { key: "id", label: "连接标识" },
  { key: "version", label: "连接版本", type: "number" },
  { key: "vendor", label: "供应商", choices: ["openai", "deepseek"] },
  { key: "base_url", label: "官方 API 地址" },
  { key: "secret_ref", label: "凭据引用" },
];
const modelFields: Field[] = [
  { key: "id", label: "模型配置标识" },
  { key: "version", label: "模型配置版本", type: "number" },
  { key: "connection_id", label: "连接标识" },
  { key: "connection_version", label: "绑定连接版本", type: "number" },
  { key: "model", label: "供应商模型名称" },
  {
    key: "context_tokens",
    label: "上下文 Token 上限",
    type: "number",
    max: 10000000,
  },
  { key: "output_tokens", label: "输出 Token 上限", type: "number" },
  { key: "timeout_seconds", label: "请求时限（秒）", type: "number", max: 300 },
  { key: "max_attempts", label: "最大尝试次数", type: "number", max: 3 },
  ...["streaming", "tools", "structured", "vision", "usage"].map((key) => ({
    key: `capabilities.${key}`,
    label: `能力声明 · ${key}`,
    choices: ["declared", "unsupported", "unknown"],
  })),
];
export function Models({ client }: { client: Client }) {
  const connections = useResource<{ items: ConfigRow[] }>(
    client,
    "/connections",
  );
  const models = useResource<{ items: ConfigRow[] }>(client, "/models");
  const [tab, setTab] = useState("models");
  const [draft, setDraft] = useState<RecordValue>();
  const [key, setKey] = useState(0);
  const [probe, setProbe] = useState<RecordValue>();
  const [filter, setFilter] = useState("");
  const data = tab === "models" ? models : connections;
  const initial: RecordValue =
    draft ||
    (tab === "models"
      ? {
          id: "",
          version: 1,
          connection_id: "",
          connection_version: 1,
          model: "",
          context_tokens: 8192,
          output_tokens: 1024,
          timeout_seconds: 30,
          max_attempts: 1,
          capabilities: {
            streaming: "unknown",
            tools: "unknown",
            structured: "unknown",
            vision: "unsupported",
            usage: "unknown",
          },
        }
      : {
          id: "",
          version: 1,
          vendor: "openai",
          base_url: "https://api.openai.com/v1",
          secret_ref: "",
        });
  return (
    <>
      <Panel title="模型与供应商连接">
        <p className="muted">
          能力声明与实测分开展示。测试只发送固定的 OK
          请求，可能产生供应商费用；不发送实验内容或工具。默认模型由每个 Agent
          的版本绑定决定。
        </p>
        <div className="console-actions">
          {["models", "connections"].map((t) => (
            <button
              aria-pressed={tab === t}
              key={t}
              onClick={() => {
                setTab(t);
                setDraft(undefined);
                setKey((k) => k + 1);
              }}
            >
              {t === "models" ? "模型配置" : "供应商连接"}
            </button>
          ))}
          <label>
            当前列表搜索
            <input value={filter} onChange={(e) => setFilter(e.target.value)} />
          </label>
          <button onClick={data.refresh}>刷新</button>
        </div>
        <Result {...data} retry={data.refresh}>
          {data.value?.items
            .filter((r) => r.ref.includes(filter))
            .map((r) => (
              <article className="console-row" key={r.ref}>
                <h3>{r.ref}</h3>
                <Status value={r.enabled ? "ENABLED" : "DISABLED"} />
                <dl className="console-facts">
                  {tab === "models" ? (
                    <>
                      <div>
                        <dt>模型</dt>
                        <dd>{String(r.document.model)}</dd>
                      </div>
                      <div>
                        <dt>绑定连接</dt>
                        <dd>
                          {String(r.document.connection_id)}@
                          {String(r.document.connection_version)}
                        </dd>
                      </div>
                      <div>
                        <dt>上下文 / 输出上限</dt>
                        <dd>
                          {String(r.document.context_tokens)} /{" "}
                          {String(r.document.output_tokens)} Token
                        </dd>
                      </div>
                      <div>
                        <dt>请求时限 / 尝试上限</dt>
                        <dd>
                          {String(r.document.timeout_seconds)} 秒 /{" "}
                          {String(r.document.max_attempts)} 次
                        </dd>
                      </div>
                    </>
                  ) : (
                    <>
                      <div>
                        <dt>供应商</dt>
                        <dd>{String(r.document.vendor)}</dd>
                      </div>
                      <div>
                        <dt>API 地址</dt>
                        <dd>{String(r.document.base_url)}</dd>
                      </div>
                    </>
                  )}
                </dl>
                {tab === "models" && (
                  <div className="capability-list">
                    {Object.entries(r.document.capabilities as RecordValue).map(
                      ([name, value]) => (
                        <span key={name}>
                          {(
                            {
                              streaming: "流式",
                              tools: "工具",
                              structured: "结构化",
                              vision: "视觉",
                              usage: "用量",
                            } as Record<string, string>
                          )[name] || name}{" "}
                          ·{" "}
                          {(
                            {
                              declared: "已声明",
                              tested: "已实测",
                              unknown: "未知",
                              unsupported: "不支持",
                            } as Record<string, string>
                          )[String(value)] || String(value)}
                        </span>
                      ),
                    )}
                  </div>
                )}
                <details>
                  <summary>完整版本配置</summary>
                  <JsonView value={r.document} />
                </details>
                <div className="console-actions">
                  <button
                    onClick={() => {
                      const fields =
                        tab === "models" ? modelFields : connectionFields;
                      const keys = new Set(
                        fields.map((f) => f.key.split(".")[0]),
                      );
                      const copy = structuredClone(
                        Object.fromEntries(
                          Object.entries(r.document).filter(([k]) =>
                            keys.has(k),
                          ),
                        ),
                      );
                      copy.version = Number(copy.version) + 1;
                      setDraft(copy);
                      setKey((k) => k + 1);
                    }}
                  >
                    创建修订版本
                  </button>
                  {r.enabled && (
                    <ActionButton
                      client={client}
                      path={`/${tab}/${id(r.ref)}/disable`}
                      label="禁用配置"
                      revision={r.revision}
                      impact={`禁用 ${r.ref} 会阻止依赖此配置的新调用。已发布的 Agent 不会自动切换模型。`}
                      onDone={data.refresh}
                    />
                  )}{" "}
                  {tab === "models" && r.enabled && (
                    <ActionButton
                      client={client}
                      path={`/models/${id(r.ref)}/test`}
                      label="测试模型连接"
                      impact="将向此配置的供应商发送一个最多 32 输出 Token 的合成文本请求，可能收费。仅验证文本流，不代表工具或视觉能力通过。"
                      onDone={setProbe}
                    />
                  )}
                </div>
              </article>
            ))}
          {data.value?.items.length === 0 && <Empty title="尚未配置" />}
        </Result>
        {probe && (
          <Panel title="最近一次模型测试">
            <JsonView value={probe} />
          </Panel>
        )}
      </Panel>
      <Panel title={tab === "models" ? "新增模型版本" : "新增连接版本"}>
        <Editor
          key={`${tab}-${key}`}
          client={client}
          path={`/${tab}`}
          fields={tab === "models" ? modelFields : connectionFields}
          initial={initial}
          title="不可变配置"
          onDone={data.refresh}
        />
      </Panel>
    </>
  );
}
export function Credentials({ client }: { client: Client }) {
  const data = useResource<{
    items: { ref: string; revision: number; configured: boolean }[];
  }>(client, "/credentials");
  const [selected, setSelected] = useState("");
  const row = data.value?.items.find((r) => r.ref === selected);
  return (
    <Panel title="供应商凭据">
      <p className="muted">
        密钥仅提交给服务器加密保存，提交成功后清空输入，不回显明文。
      </p>
      <Result {...data} retry={data.refresh}>
        {data.value?.items.map((r) => (
          <div className="console-row" key={r.ref}>
            <strong>{r.ref}</strong> ·{" "}
            {r.configured ? "******** · 已配置" : "已禁用"} · 版本 {r.revision}
            <div className="console-actions">
              <button onClick={() => setSelected(r.ref)}>轮换凭据</button>
              {r.configured && (
                <ActionButton
                  client={client}
                  path={`/credentials/${id(r.ref)}/disable`}
                  label="禁用凭据"
                  revision={r.revision}
                  onDone={data.refresh}
                />
              )}
            </div>
          </div>
        ))}
      </Result>
      <label>
        凭据引用
        <input
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          autoComplete="off"
        />
      </label>
      {selected && (
        <Editor
          key={`${selected}-${row?.revision}`}
          client={client}
          path={`/credentials/${id(selected)}`}
          fields={[{ key: "value", label: "新密钥", type: "password" }]}
          title={row ? "轮换现有凭据" : "创建凭据"}
          label="加密保存凭据"
          revision={row?.revision ?? -1}
          method="PUT"
          secret
          onDone={data.refresh}
        />
      )}
    </Panel>
  );
}
