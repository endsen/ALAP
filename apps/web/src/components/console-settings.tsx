"use client";
import { useState } from "react";
import { Client, id } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { RecordValue } from "@/lib/console";
import { Empty, Time } from "./common";
import { ActionButton, JsonView, Panel, Result } from "./console-common";
import { Credentials } from "./console-models";
export function Audit({ client }: { client: Client }) {
  const [after, setAfter] = useState(0);
  const [previous, setPrevious] = useState<number[]>([]);
  const [filter, setFilter] = useState("");
  const data = useResource<{
    items: {
      id: number;
      actor_id: string;
      operation: string;
      target: string;
      created_at: string;
    }[];
  }>(client, `/audit?limit=20&after=${after}`);
  return (
    <Panel title="平台审计">
      <p className="muted">
        显示已持久化的管理操作。实验状态转换证据仍在对应实验记录中。
      </p>
      <label>
        当前页筛选操作、身份或对象
        <input value={filter} onChange={(e) => setFilter(e.target.value)} />
      </label>
      <Result {...data} retry={data.refresh}>
        <div className="console-table">
          <table>
            <thead>
              <tr>
                <th>序号 / 时间</th>
                <th>主体</th>
                <th>操作 / 对象</th>
              </tr>
            </thead>
            <tbody>
              {data.value?.items
                .filter((r) =>
                  `${r.actor_id} ${r.operation} ${r.target}`.includes(filter),
                )
                .map((r) => (
                  <tr key={r.id}>
                    <td>
                      {r.id}
                      <small>
                        <Time value={r.created_at} />
                      </small>
                    </td>
                    <td>{r.actor_id}</td>
                    <td>
                      {r.operation}
                      <small>{r.target}</small>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
        {!data.value?.items.length && <Empty title="暂无审计记录" />}
        <div className="console-actions">
          <button
            disabled={!previous.length}
            onClick={() => {
              setAfter(previous.at(-1)!);
              setPrevious((p) => p.slice(0, -1));
            }}
          >
            上一页
          </button>
          <button
            disabled={data.value?.items.length !== 20}
            onClick={() => {
              setPrevious((p) => [...p, after]);
              setAfter(data.value!.items.at(-1)!.id);
            }}
          >
            下一页
          </button>
          <button onClick={data.refresh}>刷新审计</button>
        </div>
      </Result>
    </Panel>
  );
}
type Principal = {
  id: string;
  kind: string;
  role: string;
  disabled_at: string | null;
};
export function Settings({
  client,
  current,
}: {
  client: Client;
  current: string;
}) {
  const [cursor, setCursor] = useState("");
  const [selected, setSelected] = useState<Principal>();
  const [role, setRole] = useState("observer");
  const data = useResource<{ items: Principal[]; next_cursor: string | null }>(
    client,
    `/principals?limit=20&cursor=${id(cursor)}`,
  );
  const settings = useResource<RecordValue>(client, "/settings");
  return (
    <>
      <Panel title="用户与角色">
        <p className="muted">
          平台角色不授予实验设备权限。令牌签发仍通过受信任管理员入口；这里可撤销会话、禁用身份和调整已注册用户角色。
        </p>
        <Result {...data} retry={data.refresh}>
          {data.value?.items.map((p) => (
            <article className="console-row" key={p.id}>
              <h3>{p.id}</h3>
              <p>
                {p.kind} · {p.role} · {p.disabled_at ? "已禁用" : "有效身份"}
              </p>
              <div className="console-actions">
                {p.kind === "user" && p.id !== current && !p.disabled_at && (
                  <button
                    onClick={() => {
                      setSelected(p);
                      setRole(p.role);
                    }}
                  >
                    调整角色
                  </button>
                )}
                <ActionButton
                  client={client}
                  path={`/principals/${id(p.id)}/revoke-tokens`}
                  label="撤销全部会话"
                  impact={`撤销 ${p.id} 的所有访问令牌。该用户将需要重新取得令牌。`}
                  onDone={data.refresh}
                />
                {p.id !== current && !p.disabled_at && (
                  <ActionButton
                    client={client}
                    path={`/principals/${id(p.id)}/disable`}
                    label="禁用身份"
                    impact={`禁用 ${p.id}，将阻断该主体后续访问。不会伪造设备停止确认。`}
                    onDone={data.refresh}
                  />
                )}
              </div>
            </article>
          ))}
          <div className="console-actions">
            <button disabled={!cursor} onClick={() => setCursor("")}>
              首页
            </button>
            <button
              disabled={!data.value?.next_cursor}
              onClick={() => setCursor(data.value!.next_cursor!)}
            >
              下一页用户
            </button>
            <button
              onClick={() => {
                setSelected(undefined);
                data.refresh();
              }}
            >
              刷新身份
            </button>
          </div>
        </Result>
        {selected && (
          <section className="console-row">
            <h3>调整 {selected.id} 的角色</h3>
            <label>
              新平台角色
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                {["observer", "researcher", "admin"].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
            <ActionButton
              client={client}
              path={`/principals/${id(selected.id)}/role`}
              body={{ role, expected_role: selected.role }}
              label="应用角色"
              impact={`将 ${selected.id} 从 ${selected.role} 改为 ${role}。admin 可管理平台配置及凭据，实验成员权限仍单独核验。`}
              onDone={() => {
                setSelected(undefined);
                data.refresh();
              }}
            />
          </section>
        )}
      </Panel>
      <Credentials client={client} />
      <Panel title="系统配置与保留策略">
        <p className="muted">
          以下为实际运行策略。本版本不自动清理历史，不提供尚未接入清理器的保留天数设置。
        </p>
        <Result {...settings} retry={settings.refresh}>
          <dl className="console-facts">
            <div>
              <dt>身份认证</dt>
              <dd>本地访问令牌，最长 24 小时</dd>
            </div>
            <div>
              <dt>历史保留</dt>
              <dd>不自动删除</dd>
            </div>
            <div>
              <dt>凭据存储</dt>
              <dd>服务器加密保存</dd>
            </div>
            <div>
              <dt>配置版本</dt>
              <dd>发布后不可变，修订产生新版本</dd>
            </div>
            <div>
              <dt>Gateway 接入</dt>
              <dd>
                {settings.value?.live_gateway
                  ? "已装配适配器（不代表在线）"
                  : "未装配"}
              </dd>
            </div>
          </dl>
          <details>
            <summary>核对运行配置</summary>
            <JsonView value={settings.value} />
          </details>
        </Result>
      </Panel>
    </>
  );
}
