import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";

const state = JSON.parse(
  readFileSync(process.env.ALAP_COMPOSE_BROWSER_STATE!, "utf8"),
);
async function login(
  page: Page,
  actor = "owner",
  path = `/workspace/${state.experiment}?tab=plan`,
) {
  await page.goto(path);
  await page.getByLabel("平台访问令牌").fill(state[actor]);
  await page.getByRole("button", { name: "进入工作区" }).click();
}
async function live(page: Page) {
  await expect(
    page.getByRole("status").filter({ hasText: "实时同步" }),
  ).toBeVisible();
}
async function confirm(page: Page, name: string) {
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("button", { name: "确认" + name, exact: true }),
  ).toBeDisabled();
  await dialog.getByRole("checkbox").check();
  await dialog
    .getByRole("button", { name: "确认" + name, exact: true })
    .click();
  await expect(dialog).not.toBeVisible();
}

test("deployed approval → Engine/Gateway → committed HDF5", async ({
  page,
}) => {
  await login(page);
  await live(page);
  await expect(page.getByRole("button", { name: "创建执行 Run" })).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "请求审批", exact: true }).click();
  await confirm(page, "请求审批");
  await page.getByRole("button", { name: "批准", exact: true }).click();
  await confirm(page, "批准计划");
  await page.getByRole("button", { name: "创建执行 Run" }).click();
  await confirm(page, "启动 Run");
  await page.getByRole("tab", { name: "实验数据" }).click();
  await page.getByRole("link", { name: "查看曲线" }).click({ timeout: 90000 });
  await expect(
    page.getByRole("heading", { name: "IV 测量曲线" }),
  ).toBeVisible();
  await expect(page.locator("svg")).toBeVisible();
  const pending = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载原始 HDF5" }).click();
  const download = await pending;
  const bytes = readFileSync((await download.path())!);
  expect(bytes.subarray(0, 8).toString("hex")).toBe("894844460d0a1a0a");
  await expect(
    page.getByText(createHash("sha256").update(bytes).digest("hex"), {
      exact: true,
    }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => [localStorage.length, sessionStorage.length]),
  ).toEqual([0, 0]);
});

test("deployed observer has no approval/write UI and reload loses token", async ({
  page,
}) => {
  await login(page, "observer");
  await live(page);
  await expect(
    page.getByRole("button", { name: "批准", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "请求审批", exact: true }),
  ).toBeDisabled();
  const denied = await page.evaluate(
    async ({ token, experiment }) => {
      const headers = { Authorization: `Bearer ${token}` };
      const snapshot = await (
        await fetch(`/api/v1/experiments/${experiment}/snapshot`, { headers })
      ).json();
      const approval = snapshot.approvals[0];
      const response = await fetch(
        `/api/v1/experiments/${experiment}/approval-requests`,
        {
          method: "POST",
          headers: {
            ...headers,
            "Content-Type": "application/json",
            "Idempotency-Key": crypto.randomUUID(),
            "If-Match": `"${snapshot.experiment.revision}"`,
          },
          body: JSON.stringify({
            plan_revision_id: approval.plan_revision_id,
            plan_hash: approval.plan_hash,
            expires_at: new Date(Date.now() + 60000).toISOString(),
          }),
        },
      );
      return response.status;
    },
    { token: state.observer, experiment: state.experiment },
  );
  expect(denied).toBe(403);
  await page.reload();
  await expect(page.getByLabel("平台访问令牌")).toBeVisible();
});

test("deployed SSE disconnect disables writes; reconnect restores authority", async ({
  page,
}) => {
  await login(page);
  await live(page);
  await page.route("**/events", (route) => route.abort());
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(page.getByText("连接中断 · 状态可能过期")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "请求审批", exact: true }),
  ).toBeDisabled();
  await page.unroute("**/events");
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await live(page);
  await expect(
    page.getByRole("button", { name: "请求审批", exact: true }),
  ).toBeEnabled();
});
