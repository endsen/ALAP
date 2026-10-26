import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

// UI fault injection only; deployed HTTP scope enforcement has its own drill.
for (const failure of ["download", "series"] as const) {
  test(`dataset ${failure} denial hides protected panels and retries from fresh reads`, async ({
    page,
  }) => {
    const state = JSON.parse(
      readFileSync(
        process.env.ALAP_WEB_TEST_STATE || "/tmp/alap-d10-web.json",
        "utf8",
      ),
    );
    const manifest = JSON.parse(
      readFileSync("../../contracts/examples/dataset_manifest.json", "utf8"),
    );
    let allowed = true;
    let manifests = 0;
    let series = 0;
    const denied = {
      status: 403,
      json: { error: { code: "FORBIDDEN", message: "Scope revoked" } },
    };
    await page.route("**/api/v1/datasets/ui-access", (route) => {
      manifests++;
      return route.fulfill(allowed ? { json: manifest } : denied);
    });
    await page.route("**/api/v1/datasets/ui-access/series", (route) => {
      series++;
      return route.fulfill(
        failure === "series" && series === 1
          ? denied
          : {
              json: {
                points: [
                  [0, 0],
                  [1, 1],
                ],
                total_points: 2,
                downsampled: false,
              },
            },
      );
    });
    await page.route("**/api/v1/datasets/ui-access/download", (route) =>
      route.fulfill(denied),
    );
    await page.goto("/data/ui-access");
    await page.getByLabel("平台访问令牌").fill(state.owner);
    await page.getByRole("button", { name: "进入工作区" }).click();
    const download = page.getByRole("button", { name: "下载原始 HDF5" });
    if (failure === "download") {
      await expect(page.locator("svg")).toBeVisible();
      await download.click();
    }
    const error = page
      .getByRole("alert")
      .filter({ hasText: "你没有此资源或操作的权限" });
    await expect(error).toBeVisible();
    await expect(download).toBeDisabled();
    await expect(page.locator("svg")).toHaveCount(0);
    await expect(
      page.getByRole("heading", { name: "来源与采集记录" }),
    ).toHaveCount(0);
    await expect(
      page.getByText(manifest.checksum_sha256, { exact: true }),
    ).toHaveCount(0);
    allowed = false;
    await page.getByRole("button", { name: "重新获取状态" }).click();
    await expect.poll(() => manifests).toBe(2);
    await expect(error).toBeVisible();
    await expect(download).toBeDisabled();
    await expect(page.locator("svg")).toHaveCount(0);
    expect(series).toBe(1);
    allowed = true;
    await page.getByRole("button", { name: "重新获取状态" }).click();
    await expect(page.locator("svg")).toBeVisible();
    await expect(download).toBeEnabled();
    await expect(error).toHaveCount(0);
    expect(manifests).toBe(3);
    expect(series).toBe(2);
  });
}
