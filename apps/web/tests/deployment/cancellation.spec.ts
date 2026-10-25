import { test, expect } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
const state = JSON.parse(
  readFileSync(process.env.ALAP_COMPOSE_BROWSER_STATE!, "utf8"),
);
test("deployed cancellation remains pending until resident worker confirms", async ({
  page,
}) => {
  await page.goto(`/workspace/${state.experiment}`);
  await page.getByLabel("平台访问令牌").fill(state.owner);
  await page.getByRole("button", { name: "进入工作区" }).click();
  await page.getByRole("button", { name: /D12D3:cancel_hold/ }).click();
  const conversation = page.locator(".conversation");
  await expect(conversation.locator('[title="RUNNING"]')).toBeVisible();
  await conversation.getByRole("button", { name: "停止 Agent" }).click();
  await expect(
    conversation.getByText("已请求取消，等待后台确认", { exact: true }),
  ).toBeVisible();
  await expect(conversation.locator('[title="RUNNING"]')).toBeVisible();
  await expect(
    conversation.getByRole("button", { name: "停止 Agent" }),
  ).toBeDisabled();
  await expect(
    conversation.getByRole("button", { name: "继续处理目标" }),
  ).toBeDisabled();
  const response = await page.request.get(`/api/v1/agent-runs/${state.run}`, {
    headers: { Authorization: `Bearer ${state.owner}` },
  });
  expect(response.status()).toBe(200);
  const pending = await response.json();
  expect(pending.status).toBe("RUNNING");
  expect(pending.cancel_requested).toBe(true);
  writeFileSync(state.pending, JSON.stringify(pending), { mode: 0o600 });
  writeFileSync(state.release, "release");
  await expect(conversation.locator('[title="CANCELLED"]')).toBeVisible();
  await expect(
    conversation.getByText("已请求取消，等待后台确认", { exact: true }),
  ).toHaveCount(0);
  await expect(
    conversation.getByRole("button", { name: "停止 Agent" }),
  ).toHaveCount(0);
  expect(
    await page.evaluate(() => [localStorage.length, sessionStorage.length]),
  ).toEqual([0, 0]);
});
