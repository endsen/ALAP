import type { components } from "@/generated/api";
export type AgentConfig = components["schemas"]["AgentConfig"];
export type Skill = components["schemas"]["SkillManifest"];
export type Source = components["schemas"]["KnowledgeSource"];
export type Json =
  | null
  | boolean
  | number
  | string
  | Json[]
  | { [key: string]: Json };
export type RecordValue = { [key: string]: Json };
export type RegistryRow = {
  ref: string;
  state: string;
  document: RecordValue;
  content_hash: string;
  publisher: string | null;
  validated_at?: string | null;
};
export type ConfigRow = {
  ref: string;
  document: RecordValue;
  enabled: boolean;
  revision: number;
};
export type Field = {
  key: string;
  label: string;
  type?: "number" | "text" | "area" | "list" | "json" | "password";
  choices?: string[];
  optional?: boolean;
  min?: number;
  max?: number;
};
export function at(object: RecordValue, path: string): Json | undefined {
  return path
    .split(".")
    .reduce<
      Json | undefined
    >((v, k) => (v && typeof v === "object" && !Array.isArray(v) ? v[k] : undefined), object);
}
export function textValue(value: Json | undefined, type?: string) {
  if (value === undefined || value === null) return "";
  return type === "list" && Array.isArray(value)
    ? value.join(", ")
    : typeof value === "object"
      ? JSON.stringify(value, null, 2)
      : String(value);
}
export function formDocument(
  fields: Field[],
  values: Record<string, string>,
  initial: RecordValue = {},
): RecordValue {
  const out = structuredClone(initial);
  for (const f of fields) {
    const raw = values[f.key] || "";
    const keys = f.key.split(".");
    let target = out;
    for (const k of keys.slice(0, -1)) {
      if (!target[k] || typeof target[k] !== "object") target[k] = {};
      target = target[k] as RecordValue;
    }
    const key = keys.at(-1)!;
    if (f.optional && !raw.trim()) {
      delete target[key];
      continue;
    }
    if (f.type === "number") {
      const n = Number(raw);
      if (
        !raw.trim() ||
        !Number.isFinite(n) ||
        !Number.isInteger(n) ||
        n < (f.min ?? 1) ||
        n > (f.max ?? 1000000)
      )
        throw new Error(`${f.label}超出允许范围。`);
      target[key] = n;
    } else if (f.type === "json") {
      try {
        target[key] = JSON.parse(raw);
      } catch {
        throw new Error(`${f.label}需要有效 JSON。`);
      }
    } else if (f.type === "list")
      target[key] = [
        ...new Set(
          raw
            .split(/[,，\n]/)
            .map((x) => x.trim())
            .filter(Boolean),
        ),
      ];
    else target[key] = raw.trim();
  }
  return out;
}
export function differences(left: Json, right: Json, prefix = ""): string[] {
  if (JSON.stringify(left) === JSON.stringify(right)) return [];
  if (
    left &&
    right &&
    typeof left === "object" &&
    typeof right === "object" &&
    !Array.isArray(left) &&
    !Array.isArray(right)
  )
    return [...new Set([...Object.keys(left), ...Object.keys(right)])].flatMap(
      (k) =>
        differences(
          left[k] ?? null,
          right[k] ?? null,
          prefix ? `${prefix}.${k}` : k,
        ),
    );
  return [`${prefix}: ${JSON.stringify(left)} → ${JSON.stringify(right)}`];
}
export const consoleNav = [
  ["dashboard", "◈", "仪表板", false],
  ["agents", "◇", "Agent", true],
  ["models", "◉", "模型", true],
  ["skills", "▧", "Skills", true],
  ["mcp", "⇄", "MCP", true],
  ["knowledge", "▤", "知识", false],
  ["usage", "◴", "用量", false],
  ["traces", "⌘", "轨迹", false],
  ["audit", "≡", "审计", true],
  ["settings", "⚙", "设置", true],
] as const;
