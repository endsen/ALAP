import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
const reportPrefix = process.env.ALAP_SCREENSHOT_PREFIX || "d10";
const state = () =>
  JSON.parse(
    readFileSync(
      process.env.ALAP_WEB_TEST_STATE || "/tmp/alap-d10-web.json",
      "utf8",
    ),
  );
async function login(page: Page, actor = "owner") {
  await page.goto("/");
  await page.getByLabel("平台访问令牌").fill(state()[actor]);
  await page.getByRole("button", { name: "进入工作区" }).click();
  await page
    .getByRole("link", { name: "零场 IV 响应研究", exact: true })
    .click();
  await expect(
    page.getByRole("status").filter({ hasText: "实时同步" }),
  ).toBeVisible();
}
async function confirm(page: Page, name: string) {
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "确认" + name, exact: true }),
  ).toBeDisabled();
  await dialog.getByRole("checkbox").check();
  await dialog
    .getByRole("button", { name: "确认" + name, exact: true })
    .click();
  await expect(dialog).not.toBeVisible();
}
test("real simulated experiment: goal, plan, approval, Run, verified curve and download", async ({
  page,
}) => {
  await login(page);
  await page
    .getByLabel("选择 Agent", { exact: true })
    .selectOption("planner@1");
  await page.screenshot({
    path: `../../reports/${reportPrefix}-workspace.png`,
    fullPage: true,
  });
  await page
    .getByLabel("实验目标", { exact: true })
    .fill("测量零场 IV 响应 <script>window.injected=true</script>");
  await page.getByRole("button", { name: "提交目标" }).click();
  await page.getByRole("button", { name: "继续处理目标" }).click();
  await page.getByRole("button", { name: "转为计划草案" }).first().click();
  await page.getByRole("button", { name: "提交计划校验" }).click();
  await expect(
    page.getByText("计划已提交校验。设备尚未执行，请继续请求审批。"),
  ).toBeVisible();
  await page.getByRole("button", { name: "请求审批", exact: true }).click();
  await confirm(page, "请求审批");
  await page.getByRole("button", { name: "批准", exact: true }).click();
  await confirm(page, "批准计划");
  await expect(
    page.getByRole("status").filter({ hasText: "实时同步" }),
  ).toBeVisible();
  await page.screenshot({
    path: `../../reports/${reportPrefix}-plan.png`,
    fullPage: true,
  });
  await page.getByRole("button", { name: "创建执行 Run" }).click();
  await confirm(page, "启动 Run");
  await page.getByRole("tab", { name: "实验数据" }).click();
  await page.getByRole("link", { name: "查看曲线" }).click({ timeout: 60000 });
  await expect(
    page.getByRole("heading", { name: "IV 测量曲线" }),
  ).toBeVisible();
  await expect(page.locator("svg")).toBeVisible();
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载原始 HDF5" }).click();
  const download = await downloaded;
  expect(
    readFileSync((await download.path())!)
      .subarray(0, 8)
      .toString("hex"),
  ).toBe("894844460d0a1a0a");
  await page.screenshot({
    path: `../../reports/${reportPrefix}-data.png`,
    fullPage: true,
  });
  expect(await page.evaluate(() => "injected" in window)).toBe(false);
  expect(
    await page.evaluate(() => [localStorage.length, sessionStorage.length]),
  ).toEqual([0, 0]);
});
test("observer cannot write; reload discards token", async ({ page }) => {
  await login(page, "observer");
  await expect(page.getByLabel("实验目标", { exact: true })).toBeDisabled();
  await page.getByRole("tab", { name: "计划与审批" }).click();
  await expect(
    page.getByRole("button", { name: "批准", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByText("当前身份没有人工审批权限。")).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "进入实验工作区" }),
  ).toBeVisible();
});
test("SSE disconnect blocks writes and snapshot reconnect restores them", async ({
  page,
}) => {
  await login(page);
  await page.route("**/events", (route) => route.abort());
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(page.getByText("连接中断 · 状态可能过期")).toBeVisible();
  await expect(page.getByLabel("实验目标", { exact: true })).toBeDisabled();
  await page.unroute("**/events");
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "实时同步" }),
  ).toBeVisible();
  await expect(page.getByLabel("实验目标", { exact: true })).toBeEnabled();
});
test("mobile login remains accessible and fits viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, "observer");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: `../../reports/${reportPrefix}-mobile.png`,
    fullPage: true,
  });
});
test("version conflict keeps confirmation open and does not claim success", async ({
  page,
}) => {
  await login(page);
  await page.getByRole("tab", { name: "计划与审批" }).click();
  await page.getByRole("button", { name: "请求审批", exact: true }).click();
  await page.route("**/approval-requests", (route) =>
    route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "VERSION_CONFLICT", request_id: "browser-fault-test" },
      }),
    }),
  );
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("checkbox").check();
  await dialog
    .getByRole("button", { name: "确认请求审批", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
});
test("SSE access revocation clears protected workspace", async ({ page }) => {
  await login(page, "observer");
  await page.route("**/events", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: 'event: stream.error\ndata: {"code":"FORBIDDEN"}\n\n',
    }),
  );
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(page.getByText("访问已中止")).toBeVisible();
  await expect(page.getByRole("tab", { name: "计划与审批" })).toHaveCount(0);
});
test("create sample and experiment, display unknown instruments", async ({
  page,
}) => {
  await login(page);
  await page.getByRole("link", { name: "← 全部实验" }).click();
  await page.getByRole("button", { name: "新建实验" }).click();
  await page.getByText("添加样品记录", { exact: true }).click();
  await page.getByLabel("样品名称", { exact: true }).fill("浏览器验证样品");
  await page.getByRole("button", { name: "保存样品" }).click();
  await page.getByLabel("实验名称", { exact: true }).fill("浏览器创建实验");
  await page
    .getByRole("combobox", { name: "样品", exact: true })
    .selectOption({ label: "浏览器验证样品" });
  await page
    .getByLabel("研究目标", { exact: true })
    .fill("仅创建记录，不授予设备权限");
  await page.getByRole("button", { name: "创建实验", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "浏览器创建实验" }),
  ).toBeVisible();
  await expect(
    page.getByText("尚未分配设备范围。请联系管理员配置。"),
  ).toBeVisible();
  await page
    .getByRole("navigation")
    .getByRole("link", { name: "设备" })
    .click();
  await expect(page.getByText("状态未知")).toHaveCount(3);
  await expect(page.getByText("尚无可验证的新鲜读回")).toHaveCount(3);
});
test("expired identity returns login instead of retaining private content", async ({
  page,
}) => {
  await login(page);
  await page.route("**/snapshot", (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: '{"error":{"code":"UNAUTHENTICATED"}}',
    }),
  );
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "进入实验工作区" }),
  ).toBeVisible();
  await expect(page.getByRole("tab")).toHaveCount(0);
});

test("snapshot loading is explicit; resync event restores authoritative state", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("平台访问令牌").fill(state().owner);
  await page.getByRole("button", { name: "进入工作区" }).click();
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(
    "**/snapshot",
    async (route) => {
      await held;
      await route.continue();
    },
    { times: 1 },
  );
  await page
    .getByRole("link", { name: "零场 IV 响应研究", exact: true })
    .click();
  await expect(
    page.getByRole("status").filter({ hasText: "正在读取权威状态" }),
  ).toBeVisible();
  release();
  await expect(
    page.getByRole("status").filter({ hasText: "实时同步" }),
  ).toBeVisible();
  await page.route(
    "**/events",
    (route) =>
      route.fulfill({
        status: 409,
        contentType: "application/json",
        body: '{"error":{"code":"RESYNC_REQUIRED"}}',
      }),
    { times: 1 },
  );
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(
    page.getByText("事件序列已重新同步，当前显示服务器快照。"),
  ).toBeVisible();
  await expect(
    page.getByRole("status").filter({ hasText: "实时同步" }),
  ).toBeVisible();
});

test("revoked knowledge status hides cached content and waits for authoritative closure", async ({
  page,
}) => {
  let revoked = false;
  let ended = false;
  const view = () => ({
    id: "ui-revoked",
    experiment_id: "EXP-SIM-001",
    definition_ref: "planner@1",
    revision: ended ? 4 : 3,
    status: ended ? "FAILED" : "RUNNING",
    goal: revoked ? "内容不可访问" : "private cached goal",
    result: null,
    ...(revoked ? { access_error: "SOURCE_REVOKED" } : {}),
  });
  await page.route("**/api/v1/experiments/*/agent-runs?*", (route) =>
    route.fulfill({ json: { items: [view()] } }),
  );
  await page.route("**/api/v1/agent-runs/ui-revoked", (route) =>
    route.fulfill({ json: view() }),
  );
  await page.route("**/api/v1/agent-runs/ui-revoked/proposals", (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: "cached-proposal",
            state: "PROPOSED",
            proposal: {
              reason: "private cached proposal",
              tasks: [],
              requested_resources: [],
            },
          },
        ],
      },
    }),
  );
  await page.route("**/api/v1/agent-runs/ui-revoked/trace", (route) =>
    route.fulfill({
      json: {
        items: [
          { seq: 1, event: { type: "tool", content: "private cached source" } },
        ],
      },
    }),
  );
  await login(page);
  await page.getByRole("button", { name: /private cached goal/ }).click();
  const conversation = page.locator(".conversation");
  await expect(
    conversation.getByText("private cached proposal", { exact: true }),
  ).toBeVisible();
  revoked = true;
  await expect(
    conversation.getByText(/知识来源权限已撤销，等待后台结束处理/),
  ).toBeVisible();
  await expect(
    conversation.getByRole("button", { name: "继续处理目标" }),
  ).toBeDisabled();
  await expect(
    conversation.getByRole("button", { name: "停止 Agent" }),
  ).toHaveCount(0);
  await expect(conversation.getByText(/private cached/)).toHaveCount(0);
  await expect(
    conversation.getByText("查看处理轨迹", { exact: false }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /private cached goal/ }),
  ).toHaveCount(0);
  ended = true;
  await expect(
    conversation.getByText(/知识来源权限已撤销，本次处理已终止/),
  ).toBeVisible();
  await expect(
    conversation.getByTitle("FAILED", { exact: true }),
  ).toBeVisible();
});

test("cancel intent stays running until worker acknowledgement", async ({
  page,
}) => {
  let requested = false;
  let ended = false;
  const view = () => ({
    id: "ui-cancel",
    experiment_id: "EXP-SIM-001",
    definition_ref: "planner@1",
    revision: ended ? 4 : 3,
    status: ended ? "CANCELLED" : "RUNNING",
    goal: "cancellable goal",
    result: null,
    cancel_requested: requested,
  });
  await page.route("**/api/v1/experiments/*/agent-runs?*", (route) =>
    route.fulfill({ json: { items: [view()] } }),
  );
  await page.route("**/api/v1/agent-runs/ui-cancel", (route) =>
    route.fulfill({ json: view() }),
  );
  for (const suffix of ["trace", "proposals"]) {
    await page.route(`**/api/v1/agent-runs/ui-cancel/${suffix}`, (route) =>
      route.fulfill({ json: { items: [] } }),
    );
  }
  await page.route("**/api/v1/agent-runs/ui-cancel/cancel", (route) => {
    requested = true;
    return route.fulfill({ json: view() });
  });
  await login(page);
  await page.getByRole("button", { name: /cancellable goal/ }).click();
  const conversation = page.locator(".conversation");
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
  ended = true;
  await expect(conversation.locator('[title="CANCELLED"]')).toBeVisible();
  await expect(
    conversation.getByText("已请求取消，等待后台确认", { exact: true }),
  ).toHaveCount(0);
});
