"use client";
import { APIError, explain } from "@/lib/api";
import type { Series } from "@/lib/types";
export function Status({ value }: { value: string }) {
  const tone = ["SUCCEEDED", "COMMITTED", "APPROVED", "COMPLETED"].includes(
    value,
  )
    ? "good"
    : [
          "UNKNOWN",
          "NEEDS_ATTENTION",
          "NEEDS_RECONCILIATION",
          "CORRUPT",
          "FAILED",
          "STALE",
          "EXPIRED",
        ].includes(value)
      ? "warn"
      : ["RUNNING", "PENDING", "READY", "PLANNED", "VERIFYING"].includes(value)
        ? "active"
        : "neutral";
  const labels: Record<string, string> = {
    UNKNOWN: "状态未知",
    DRAFT: "草案",
    PLANNED: "计划已验证",
    PROPOSED: "候选提案",
    READY: "待调度",
    RUNNING: "运行中",
    COMPLETED: "已完成",
    SUCCEEDED: "已验证成功",
    COMMITTED: "数据已提交",
    PENDING: "待审批",
    APPROVED: "已批准",
    REJECTED: "已拒绝",
    REVOKED: "已撤销",
    EXPIRED: "已过期",
    PAUSED: "已暂停",
    CANCELLED: "已取消",
    CANCEL_REQUESTED: "取消待确认",
    PAUSE_REQUESTED: "暂停待确认",
    FAILED: "失败",
    CORRUPT: "数据损坏",
    NEEDS_ATTENTION: "需要人工核对",
    NEEDS_RECONCILIATION: "需要对账",
    VERIFYING: "正在验证",
    BLOCKED: "已阻断",
    SUPERSEDED: "已被新版本替代",
  };
  return (
    <span className={`status ${tone}`} title={value}>
      <i />
      {labels[value] || value}
    </span>
  );
}
export function Problem({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  if (!error) return null;
  return (
    <div className="problem" role="alert">
      <strong>
        {error instanceof Error && !(error instanceof APIError)
          ? error.message
          : explain(error)}
      </strong>
      {error instanceof APIError && error.requestId && (
        <small>请求编号 {error.requestId}</small>
      )}
      {retry && (
        <button className="subtle" onClick={retry}>
          重新获取状态
        </button>
      )}
    </div>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <span className="empty-mark">◇</span>
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading" role="status">
      <span />
      正在读取权威状态…
    </div>
  );
}
export function Time({ value }: { value: string | null | undefined }) {
  return (
    <time dateTime={value || undefined}>
      {value
        ? new Date(value).toLocaleString("zh-CN", { hour12: false })
        : "暂无读回时间"}
    </time>
  );
}
export function Plot({ series }: { series: Series }) {
  const xs = series.points.map((p) => p[0]),
    ys = series.points.map((p) => p[1]);
  const minX = Math.min(...xs),
    maxX = Math.max(...xs),
    minY = Math.min(...ys),
    maxY = Math.max(...ys);
  const scale = (x: number, min: number, max: number, span: number) =>
    ((x - min) / (max - min || 1)) * span;
  const path = series.points
    .map(
      (p, i) =>
        `${i ? "L" : "M"}${70 + scale(p[0], minX, maxX, 610)},${300 - scale(p[1], minY, maxY, 250)}`,
    )
    .join(" ");
  return (
    <figure className="plot">
      <svg
        viewBox="0 0 740 360"
        role="img"
        aria-label="电流电压曲线，横轴电流 A，纵轴电压 V"
      >
        {[0, 1, 2, 3, 4].map((i) => (
          <g key={i}>
            <line
              x1="70"
              y1={50 + i * 62.5}
              x2="680"
              y2={50 + i * 62.5}
              stroke="#e1e6e9"
            />
            <text x="60" y={54 + i * 62.5} textAnchor="end">
              {(maxY - ((maxY - minY) * i) / 4).toExponential(1)}
            </text>
          </g>
        ))}
        <path d={path} fill="none" stroke="#177b77" strokeWidth="2.5" />
        <line x1="70" y1="300" x2="680" y2="300" stroke="#8b9ba6" />
        <text x="70" y="322">
          {minX.toExponential(2)}
        </text>
        <text x="680" y="322" textAnchor="end">
          {maxX.toExponential(2)}
        </text>
        <text x="370" y="350" textAnchor="middle">
          电流 / A
        </text>
        <text x="16" y="175" transform="rotate(-90 16 175)" textAnchor="middle">
          电压 / V
        </text>
      </svg>
      <figcaption>
        采样点 {series.total_points.toLocaleString()} ·{" "}
        {series.downsampled
          ? "等距抽样预览，原始下载保留全部数据"
          : "展示全部采样点"}{" "}
        · 曲线不代替科学结论
      </figcaption>
    </figure>
  );
}
