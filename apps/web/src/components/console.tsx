"use client";
import { useEffect, useState } from "react";
import { APIError, Client } from "@/lib/api";
import { consoleNav } from "@/lib/console";
import type { Identity } from "@/lib/types";
import { Empty } from "./common";
import { useOnline } from "./console-common";
import { Registry } from "./console-registry";
import { Models } from "./console-models";
import { MCP } from "./console-mcp";
import { Knowledge } from "./console-knowledge";
import { Observe } from "./console-observe";
import { Audit, Settings } from "./console-settings";
export function ConsolePage({
  client,
  identity,
  parts,
}: {
  client: Client;
  identity: Identity;
  parts: string[];
}) {
  const online = useOnline();
  const [denied, setDenied] = useState(false);
  const [unverified, setUnverified] = useState(false);
  useEffect(() => {
    const hide = () => setDenied(true);
    const check = () => {
      client
        .read<Identity>("/me")
        .then((me) => {
          setUnverified(false);
          if (me.role !== identity.role) hide();
        })
        .catch((error) => {
          if (error instanceof APIError && [401, 403].includes(error.status))
            hide();
          else setUnverified(true);
        });
    };
    window.addEventListener("alap:access-denied", hide);
    window.addEventListener("focus", check);
    const timer = setInterval(check, 15000);
    return () => {
      clearInterval(timer);
      window.removeEventListener("alap:access-denied", hide);
      window.removeEventListener("focus", check);
    };
  }, [client, identity.role]);
  if (denied)
    return (
      <Empty title="权限或会话已变化，已清除当前页面">
        <button onClick={() => client.invalidate()}>重新登录核验权限</button>
      </Empty>
    );
  const route = consoleNav.find((n) => n[0] === parts[0]);
  if (!route) return <Empty title="页面不存在" />;
  if (route[3] && identity.role !== "admin")
    return (
      <Empty title="需要平台管理员权限">
        服务端会再次核验权限，请联系管理员。
      </Empty>
    );
  return (
    <div className="console-page">
      <header className="console-heading">
        <div>
          <p className="eyebrow">ALAP / PLATFORM</p>
          <h1>{route[2]}</h1>
        </div>
        <span className="console-scope">
          {route[3] ? "平台管理范围" : "当前用户授权范围"}
        </span>
      </header>
      {(!online || unverified) && (
        <p role="alert" className="problem">
          暂时无法核验连接或身份，已禁用写入。恢复连接并重新核验后再操作。
        </p>
      )}
      <fieldset disabled={!online || unverified} className="console-body">
        {parts[0] === "agents" || parts[0] === "skills" ? (
          <Registry client={client} kind={parts[0]} selected={parts[1]} />
        ) : parts[0] === "models" ? (
          <Models client={client} />
        ) : parts[0] === "mcp" ? (
          <MCP client={client} />
        ) : parts[0] === "knowledge" ? (
          <Knowledge client={client} />
        ) : parts[0] === "audit" ? (
          <Audit client={client} />
        ) : parts[0] === "settings" ? (
          <Settings client={client} current={identity.id} />
        ) : (
          <Observe
            client={client}
            mode={parts[0] as "dashboard" | "usage" | "traces"}
            initialExperiment={parts[1]}
            initialRun={parts[2]}
          />
        )}
      </fieldset>
    </div>
  );
}
