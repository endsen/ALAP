import { test, expect } from "@playwright/test";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
const state = JSON.parse(
  readFileSync(process.env.ALAP_COMPOSE_BROWSER_STATE!, "utf8"),
);
test(`deployed ${state.mode} artifact disables data and recovers on retry`, async ({
  page,
}) => {
  await page.goto(`/data/${state.dataset}`);
  await page.getByLabel("平台访问令牌").fill(state.owner);
  await page.getByRole("button", { name: "进入工作区" }).click();
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "数据文件缺失、损坏或校验不一致" }),
  ).toContainText("数据文件缺失、损坏或校验不一致");
  const download = page.getByRole("button", { name: "下载原始 HDF5" });
  await expect(download).toBeDisabled();
  await expect(page.getByRole("heading", { name: "IV 测量曲线" })).toHaveCount(
    0,
  );
  await expect(page.locator("svg")).toHaveCount(0);
  writeFileSync(`${state.directory}/ready`, "ready");
  await expect.poll(() => existsSync(`${state.directory}/restored`)).toBe(true);
  await page.getByRole("button", { name: "重新获取状态" }).click();
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "数据文件缺失、损坏或校验不一致" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "IV 测量曲线" }),
  ).toBeVisible();
  await expect(page.locator("svg")).toBeVisible();
  await expect(download).toBeEnabled();
  const pending = page.waitForEvent("download");
  await download.click();
  const bytes = readFileSync((await (await pending).path())!);
  expect(createHash("sha256").update(bytes).digest("hex")).toBe(state.checksum);
});
