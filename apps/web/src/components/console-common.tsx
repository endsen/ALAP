"use client";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Client } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import {
  at,
  formDocument,
  textValue,
  type Field,
  type RecordValue,
} from "@/lib/console";
import { Empty, Loading, Problem } from "./common";
export function JsonView({ value }: { value: unknown }) {
  return <pre className="console-json">{JSON.stringify(value, null, 2)}</pre>;
}
export function Panel({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="console-panel">
      <h2>{title}</h2>
      {children}
    </section>
  );
}
export function Result({
  value,
  error,
  loading,
  retry,
  children,
}: {
  value: unknown;
  error: unknown;
  loading: boolean;
  retry: () => void;
  children: ReactNode;
}) {
  return loading ? (
    <Loading />
  ) : error ? (
    <Problem error={error} retry={retry} />
  ) : value === undefined ? (
    <Empty title="暂无记录" />
  ) : (
    <>{children}</>
  );
}
export function ActionButton({
  client,
  path,
  label,
  body,
  revision,
  onDone,
  impact = "操作会改变服务器记录。请核对对象及影响范围。",
  confirm = true,
  disabled = false,
  method = "POST",
}: {
  client: Client;
  path: string;
  label: string;
  body?: unknown;
  revision?: number;
  onDone?: (result: RecordValue) => void;
  impact?: string;
  confirm?: boolean;
  disabled?: boolean;
  method?: string;
}) {
  const [open, setOpen] = useState(false);
  const [checked, setChecked] = useState(false);
  const [done, setDone] = useState(false);
  const action = useAction();
  async function run() {
    await action.act(async () => {
      const result = await client.mutate<RecordValue>(
        path,
        body,
        revision,
        method,
      );
      setOpen(false);
      setDone(true);
      onDone?.(result);
    });
  }
  return (
    <span className="console-action">
      <button
        disabled={disabled || action.busy}
        onClick={() => {
          setChecked(false);
          setDone(false);
          if (confirm) setOpen(true);
          else void run();
        }}
      >
        {label}
      </button>
      {done && <small role="status">已完成</small>}
      <Problem error={action.error} />
      {open && (
        <div className="modal-backdrop">
          <section
            role="dialog"
            aria-modal="true"
            aria-label={label}
            className="console-dialog"
            onKeyDown={(e) => {
              if (e.key === "Escape" && !action.busy) setOpen(false);
              if (e.key === "Tab") {
                const buttons = Array.from(
                  e.currentTarget.querySelectorAll<HTMLElement>(
                    "button:not(:disabled), input:not(:disabled)",
                  ),
                );
                const first = buttons[0],
                  last = buttons.at(-1);
                if (e.shiftKey && document.activeElement === first) {
                  e.preventDefault();
                  last?.focus();
                } else if (!e.shiftKey && document.activeElement === last) {
                  e.preventDefault();
                  first?.focus();
                }
              }
            }}
          >
            <h2>{label}</h2>
            <p>{impact}</p>
            <code>{path}</code>
            <label className="check-line">
              <input
                type="checkbox"
                checked={checked}
                onChange={(e) => setChecked(e.target.checked)}
              />
              我已核对对象和影响范围
            </label>
            <div className="console-actions">
              <button
                autoFocus
                onClick={() => setOpen(false)}
                disabled={action.busy}
              >
                返回
              </button>
              <button
                className="primary"
                disabled={!checked || action.busy}
                onClick={() => void run()}
              >
                确认{label}
              </button>
            </div>
            <Problem error={action.error} />
          </section>
        </div>
      )}
    </span>
  );
}
export function Editor({
  client,
  path,
  fields,
  initial = {},
  title,
  label = "保存新版本",
  onDone,
  revision,
  method = "POST",
  secret = false,
}: {
  client: Client;
  path: string;
  fields: Field[];
  initial?: RecordValue;
  title: string;
  label?: string;
  onDone?: () => void;
  revision?: number;
  method?: string;
  secret?: boolean;
}) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      fields.map((f) => [f.key, textValue(at(initial, f.key), f.type)]),
    ),
  );
  const [saved, setSaved] = useState(false);
  const action = useAction();
  return (
    <form
      className="console-form"
      onSubmit={(e) => {
        e.preventDefault();
        void action.act(async () => {
          const body = formDocument(fields, values, initial);
          await client.mutate(path, body, revision, method);
          if (secret) setValues({});
          setSaved(true);
          onDone?.();
        });
      }}
    >
      <h3>{title}</h3>
      <div className="console-fields">
        {fields.map((f) => (
          <label key={f.key}>
            {f.label}
            {f.optional && <small>（可选）</small>}
            {f.choices ? (
              <select
                value={values[f.key] || ""}
                onChange={(e) =>
                  setValues({ ...values, [f.key]: e.target.value })
                }
                required={!f.optional}
              >
                <option value="">请选择</option>
                {f.choices.map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            ) : ["area", "json"].includes(f.type || "") ? (
              <textarea
                rows={f.type === "json" ? 5 : 3}
                value={values[f.key] || ""}
                required={!f.optional}
                onChange={(e) =>
                  setValues({ ...values, [f.key]: e.target.value })
                }
              />
            ) : (
              <input
                type={
                  f.type === "number"
                    ? "number"
                    : f.type === "password"
                      ? "password"
                      : "text"
                }
                min={f.min ?? 1}
                max={f.max ?? 1000000}
                value={values[f.key] || ""}
                autoComplete="off"
                required={!f.optional && f.type !== "list"}
                onChange={(e) =>
                  setValues({ ...values, [f.key]: e.target.value })
                }
              />
            )}
          </label>
        ))}
      </div>
      <Problem error={action.error} />
      <button className="primary" disabled={action.busy}>
        {action.busy ? "正在提交…" : label}
      </button>
      {saved && <p role="status">已保存，后续操作以服务器记录为准。</p>}
    </form>
  );
}
export function useOnline() {
  const [online, setOnline] = useState(true);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);
  return online;
}
