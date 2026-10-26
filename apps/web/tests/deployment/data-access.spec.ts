import { test, expect } from "@playwright/test";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
const state = JSON.parse(
  readFileSync(process.env.ALAP_COMPOSE_BROWSER_STATE!, "utf8"),
);
test("loaded dataset hides protected content after scope reduction", async ({
  page,
}) => {
  await page.goto(`/data/${state.dataset}`);
  await page.getByLabel("平台访问令牌").fill(state.observer);
  await page.getByRole("button", { name: "进入工作区" }).click();
  await expect(page.locator("svg")).toBeVisible();
  const download = page.getByRole("button", { name: "下载原始 HDF5" });
  await expect(download).toBeEnabled();
  writeFileSync(`${state.directory}/ready`, "ready");
  await expect.poll(() => existsSync(`${state.directory}/revoked`)).toBe(true);
  const denied = page.waitForResponse(
    (r) => r.url().endsWith("/download") && r.status() === 403,
  );
  await download.click();
  await denied;
  await expect(
    page.getByRole("alert").filter({ hasText: "你没有此资源或操作的权限" }),
  ).toContainText("你没有此资源或操作的权限");
  await expect(download).toBeDisabled();
  await expect(page.locator("svg")).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "来源与采集记录" }),
  ).toHaveCount(0);
  writeFileSync(`${state.directory}/hidden`, "hidden");
  await expect.poll(() => existsSync(`${state.directory}/restored`)).toBe(true);
  await page.getByRole("button", { name: "重新获取状态" }).click();
  await expect(page.locator("svg")).toBeVisible();
  await expect(download).toBeEnabled();
  const pending = page.waitForEvent("download");
  await download.click();
  const bytes = readFileSync((await (await pending).path())!);
  expect(createHash("sha256").update(bytes).digest("hex")).toBe(state.checksum);
});
