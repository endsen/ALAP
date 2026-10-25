import { test, expect } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
const state = JSON.parse(
  readFileSync(process.env.ALAP_COMPOSE_BROWSER_STATE!, "utf8"),
);
test("deployed source revocation shows waiting then failed without private content", async ({
  page,
}) => {
  await page.goto(`/workspace/${state.experiment}`);
  await page.getByLabel("平台访问令牌").fill(state.owner);
  await page.getByRole("button", { name: "进入工作区" }).click();
  await page.getByRole("button", { name: /内容不可访问/ }).click();
  const conversation = page.locator(".conversation");
  await expect(
    conversation.getByText(/知识来源权限已撤销，等待后台结束处理/),
  ).toBeVisible();
  await expect(
    conversation.getByRole("button", { name: "继续处理目标" }),
  ).toBeDisabled();
  await expect(page.getByText(/private deployed/)).toHaveCount(0);
  writeFileSync(state.waiting, "ready");
  await expect(
    conversation.getByText(/知识来源权限已撤销，本次处理已终止/),
  ).toBeVisible({ timeout: 60000 });
  await expect(page.getByText(/private deployed/)).toHaveCount(0);
  await expect(
    conversation.getByRole("button", { name: "继续处理目标" }),
  ).toBeDisabled();
  await expect(
    conversation.getByRole("button", { name: "停止 Agent" }),
  ).toHaveCount(0);
  expect(
    await page.evaluate(() => [localStorage.length, sessionStorage.length]),
  ).toEqual([0, 0]);
});
