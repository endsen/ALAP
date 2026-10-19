import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
const state = () =>
  JSON.parse(
    readFileSync(
      process.env.ALAP_WEB_TEST_STATE || "/tmp/alap-d10-web.json",
      "utf8",
    ),
  );
async function login(page: Page, path: string, actor = "owner") {
  await page.goto(path);
  await page.getByLabel("平台访问令牌").fill(state()[actor]);
  await page.getByRole("button", { name: "进入工作区" }).click();
}
async function confirm(page: Page, label: string) {
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("checkbox").check();
  await dialog
    .getByRole("button", { name: `确认${label}`, exact: true })
    .click();
  await expect(dialog).not.toBeVisible();
}
test("admin can import, validate, publish and inspect an immutable Skill version", async ({
  page,
}) => {
  await login(page, "/skills");
  await page.getByLabel("Skill 标识", { exact: true }).fill("console_guide");
  await page
    .getByLabel("指令与操作知识")
    .fill("Only propose approved measurements.");
  await page.getByLabel("来源", { exact: true }).fill("alap:test");
  await page.getByLabel("维护者").fill("owner");
  await page.getByLabel("成功判据").fill("reviewed proposal");
  await page.getByRole("button", { name: "保存草稿" }).click();
  await page
    .getByRole("link", { name: "console_guide@1", exact: true })
    .click();
  await page.getByRole("button", { name: "发布前校验" }).click();
  await expect(page.getByText("已完成", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "发布版本", exact: true }).click();
  await confirm(page, "发布版本");
  await expect(page.getByRole("button", { name: "禁用版本" })).toBeVisible();
  await page.getByRole("button", { name: "基于此版本修订" }).click();
  await expect(page.getByLabel("配置版本", { exact: true })).toHaveValue("2");
  await page
    .getByLabel("指令与操作知识")
    .fill("Revised safe proposal guidance.");
  await page.getByRole("button", { name: "保存草稿" }).click();
  await page
    .getByRole("link", { name: "console_guide@2", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "版本详情 · console_guide@2",
      exact: true,
    }),
  ).toBeVisible();
  await page.getByLabel("比较版本引用").fill("console_guide@1");
  await expect(
    page.locator("pre").filter({ hasText: "content:" }),
  ).toContainText("Revised safe proposal guidance");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "../../reports/d11-skills.png",
    fullPage: true,
  });
});
test("credentials stay masked and model configuration is versioned without a live model call", async ({
  page,
}) => {
  await login(page, "/settings");
  await page.getByLabel("凭据引用", { exact: true }).fill("console-secret");
  await page.getByLabel("新密钥").fill("synthetic-only-never-a-real-key");
  await page.getByRole("button", { name: "加密保存凭据" }).click();
  await expect(
    page.getByText("******** · 已配置", { exact: false }),
  ).toBeVisible();
  await expect(page.getByLabel("新密钥")).toHaveValue("");
  await expect(page.locator("body")).not.toContainText(
    "synthetic-only-never-a-real-key",
  );
  await page.getByRole("link", { name: "模型", exact: true }).click();
  await page.getByRole("button", { name: "供应商连接", exact: true }).click();
  await page.getByLabel("连接标识", { exact: true }).fill("console_connection");
  await page.getByLabel("凭据引用", { exact: true }).fill("console-secret");
  await page.getByRole("button", { name: "保存新版本" }).click();
  await expect(
    page.getByRole("heading", { name: "console_connection@1", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "模型配置", exact: true }).click();
  await page.getByLabel("模型配置标识").fill("console_model");
  await page.getByLabel("连接标识", { exact: true }).fill("console_connection");
  await page.getByLabel("供应商模型名称").fill("synthetic-model");
  await page.getByLabel("能力声明 · streaming").selectOption("declared");
  await page.getByLabel("能力声明 · tools").selectOption("declared");
  await page.getByRole("button", { name: "保存新版本" }).click();
  await expect(
    page.getByRole("heading", { name: "console_model@1", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "创建修订版本" }).click();
  await expect(page.getByLabel("模型配置版本", { exact: true })).toHaveValue(
    "2",
  );
  await page.getByRole("button", { name: "保存新版本" }).click();
  await expect(
    page.getByRole("heading", { name: "console_model@2", exact: true }),
  ).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "../../reports/d11-models.png",
    fullPage: true,
  });
});
test("Agent draft binds actual model, permissions and budgets before publication", async ({
  page,
}) => {
  await login(page, "/agents");
  await page.getByLabel("Agent 标识", { exact: true }).fill("console_agent");
  await page.getByLabel("模型版本引用").fill("console_model@1");
  await page.getByLabel("工具授权", { exact: false }).fill("propose_plan@1");
  await page
    .getByLabel("设备作用域", { exact: false })
    .fill("sim-temp, sim-magnet, sim-smu");
  await page.getByLabel("Token 预算", { exact: true }).fill("128000");
  await page
    .getByLabel("Skills 绑定", { exact: false })
    .fill("set_temperature@1, set_field@1, iv_measurement@1");
  await page.getByLabel("实验作用域", { exact: false }).fill("EXP-CONSOLE");
  await page.getByRole("button", { name: "保存草稿" }).click();
  await page
    .getByRole("link", { name: "console_agent@1", exact: true })
    .click();
  await page.getByRole("button", { name: "发布前校验" }).click();
  await expect(page.getByText("已完成", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "发布版本", exact: true }).click();
  await confirm(page, "发布版本");
  await expect(page.getByRole("button", { name: "禁用版本" })).toBeVisible();
  await page.getByLabel("测试实验 ID").fill("EXP-CONSOLE");
  await page.getByLabel("测试目标").fill("验证受控模拟提案");
  await page.getByRole("button", { name: "创建测试运行", exact: true }).click();
  await confirm(page, "创建测试运行");
  await page.getByRole("button", { name: "推进测试一步", exact: true }).click();
  await confirm(page, "推进测试一步");
  await page.getByRole("button", { name: "推进测试一步", exact: true }).click();
  await confirm(page, "推进测试一步");
  const trial = JSON.parse(
    await page
      .locator("pre")
      .filter({ hasText: '"definition_ref": "console_agent@1"' })
      .innerText(),
  );
  const trace = await page.request.get(`/api/v1/agent-runs/${trial.id}/trace`, {
    headers: { Authorization: `Bearer ${state().owner}` },
  });
  expect(trial.status, JSON.stringify((await trace.json()).items)).toBe(
    "COMPLETED",
  );
  await expect(
    page.locator("pre").filter({ hasText: '"proposal_ids"' }),
  ).toBeVisible();
  await page.getByRole("button", { name: "禁用版本", exact: true }).click();
  await confirm(page, "禁用版本");
});
test("MCP discovery uses actual local HTTP server and requires separate grant", async ({
  page,
}) => {
  await login(page, "/mcp");
  await page.getByRole("button", { name: "连接测试与工具发现" }).click();
  await confirm(page, "连接测试与工具发现");
  await expect(page.getByText("lookup", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "核实授权范围" }).click();
  await page.getByLabel("使用者身份").fill("owner");
  await page.getByLabel("所属实验").fill("EXP-SIM-001");
  await page.getByRole("button", { name: "批准只读工具", exact: true }).click();
  await confirm(page, "批准只读工具");
  await expect(
    page.locator("pre").filter({ hasText: '"side_effect": "none"' }),
  ).toBeVisible();
  await page.getByRole("button", { name: "撤销工具授权", exact: true }).click();
  await confirm(page, "撤销工具授权");
  await expect(
    page.locator("pre").filter({ hasText: '"revoked": true' }),
  ).toBeVisible();
});
test("knowledge import, retrieval and access revocation operate on actual sources", async ({
  page,
}) => {
  await login(page, "/knowledge");
  await page
    .getByRole("combobox", { name: "选择实验", exact: true })
    .selectOption("EXP-SIM-001");
  await page.getByLabel("知识来源标识").fill("console_source");
  await page.getByLabel("来源地址或说明").fill("alap:synthetic");
  await page
    .getByLabel("文档或记忆内容")
    .fill("Controlled proposal evidence alpha.");
  await page.getByRole("button", { name: "导入来源" }).click();
  await expect(
    page.getByRole("heading", { name: "console_source@1" }),
  ).toBeVisible();
  await page.getByLabel("检索文本").fill("alpha");
  await page.getByRole("button", { name: "检索", exact: true }).click();
  await expect(page.locator("blockquote")).toContainText("alpha");
  await page.getByLabel("共享或撤销的使用者身份").fill("observer");
  await page.getByRole("button", { name: "共享来源", exact: true }).click();
  await confirm(page, "共享来源");
  await page.getByRole("button", { name: "撤销来源访问", exact: true }).click();
  await confirm(page, "撤销来源访问");
});
test("dashboard drills into scoped traces and unknown usage is not zero", async ({
  page,
}) => {
  await login(page, "/dashboard");
  await page
    .getByRole("combobox", { name: "选择实验", exact: true })
    .selectOption("EXP-SIM-001");
  await expect(page.getByRole("heading", { name: "实验仪表板" })).toBeVisible();
  await expect(page.getByText("费用估算", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "查看调用轨迹" }).click();
  await expect(
    page.getByRole("combobox", { name: "选择实验", exact: true }),
  ).toHaveValue("EXP-SIM-001");
  await page.getByRole("button", { name: "仪器命令", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "实验关联轨迹" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "审计", exact: true }).click();
  await expect(
    page.getByRole("cell").filter({ hasText: "importSkill" }).first(),
  ).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "../../reports/d11-audit.png",
    fullPage: true,
  });
});
test("non-admin cannot open administration and offline mode disables writes", async ({
  page,
  context,
}) => {
  await login(page, "/models", "observer");
  await expect(
    page.getByText("需要平台管理员权限", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "设置", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "退出", exact: true }).click();
  await login(page, "/skills");
  await context.setOffline(true);
  await expect(page.getByRole("button", { name: "保存草稿" })).toBeDisabled();
  await context.setOffline(false);
});
test("permission denial clears previously loaded configuration", async ({
  page,
}) => {
  await login(page, "/skills/iv_guidance@1");
  await expect(
    page.getByRole("heading", { name: "版本详情 · iv_guidance@1" }),
  ).toBeVisible();
  await page.route("**/api/v1/skills?*", (route) =>
    route.fulfill({
      status: 403,
      contentType: "application/json",
      body: JSON.stringify({ error: { code: "FORBIDDEN" } }),
    }),
  );
  await page.getByRole("button", { name: "刷新目录" }).click();
  await expect(
    page.getByText("权限或会话已变化，已清除当前页面", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "版本详情 · iv_guidance@1" }),
  ).toHaveCount(0);
});

test("mobile console remains within viewport and keyboard confirmation can be dismissed", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, "/settings");
  await expect(
    page.getByRole("heading", { name: "系统配置与保留策略" }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await page.getByRole("button", { name: "撤销全部会话" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "../../reports/d11-mobile.png",
    fullPage: true,
  });
});
