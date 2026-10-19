import { Suspense } from "react";
import { WorkspaceApp } from "@/components/workspace";
import type { Metadata } from "next";
import "./style.css";
export const metadata: Metadata = {
  title: "ALAP · 实验工作区",
  description: "面向实验室的专用 Agent 工作区",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <Suspense fallback={<p>正在打开工作区…</p>}>
          <WorkspaceApp />
        </Suspense>
        {children}
      </body>
    </html>
  );
}
