import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
const state = JSON.parse(
  readFileSync(process.env.ALAP_COMPOSE_BROWSER_STATE!, "utf8"),
);
for (const c of state.cases || []) {
  test(`resident Agent → offline ${c.vendor} API → human approval → dataset`, async ({
    page,
  }) => {
    let advances = 0;
    page.on("request", (r) => {
      if (r.url().endsWith("/advance")) advances++;
    });
    await page.goto(`/workspace/${c.experiment}`);
    await page.getByLabel("平台访问令牌").fill(state.owner);
    await page.getByRole("button", { name: "进入工作区" }).click();
    await expect(
      page.getByRole("status").filter({ hasText: "实时同步" }),
    ).toBeVisible();
    await page
      .getByLabel("选择 Agent", { exact: true })
      .selectOption(c.id + "@1");
    await page
      .getByLabel("实验目标", { exact: true })
      .fill("模拟仪器零场 IV 验收；仅生成提案，等待人工审批。");
    const created = page.waitForResponse(
      (r) => r.url().endsWith("/agent-runs") && r.request().method() === "POST",
    );
    await page.getByRole("button", { name: "提交目标" }).click();
    const run = await (await created).json();
    await expect(
      page.getByRole("button", { name: "转为计划草案" }),
    ).toBeVisible({ timeout: 60000 });
    expect(advances).toBe(0);
    const headers = { Authorization: `Bearer ${state.owner}` };
    const denied = await page.request.post("/api/v1/agent-runs", {
      headers: {
        ...headers,
        "Idempotency-Key": createHash("sha256").update(c.id).digest("hex"),
      },
      data: {
        experiment_id: "EXP-SIM-001",
        definition_ref: c.id + "@1",
        goal: "Scope denial drill",
      },
    });
    expect(denied.status()).toBe(403);
    expect((await denied.json()).error.code).toBe("FORBIDDEN");
    const snapshot = await (
      await page.request.get(`/api/v1/experiments/${c.experiment}/snapshot`, {
        headers,
      })
    ).json();
    expect(snapshot.runs).toEqual([]);
    expect(snapshot.approvals).toEqual([]);
    const trace = await (
      await page.request.get(`/api/v1/agent-runs/${run.id}/trace`, { headers })
    ).json();
    const calls = trace.items
      .map((r: any) => r.event)
      .filter((e: any) => e.type === "model_completed");
    expect(calls).toHaveLength(2);
    for (const call of calls) {
      expect(call.actual_model).toBe("offline-" + c.vendor);
      expect(call.usage).toEqual({
        prompt_tokens: 100,
        completion_tokens: 50,
        total_tokens: 150,
      });
      expect(call.attempts).toHaveLength(1);
      expect(call.attempts[0].vendor).toBe(c.vendor);
    }
    await page.getByRole("button", { name: "转为计划草案" }).click();
    await page.getByRole("button", { name: "提交计划校验" }).click();
    await expect(
      page.getByText("计划已提交校验。设备尚未执行，请继续请求审批。"),
    ).toBeVisible();
    async function confirm(name: string) {
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
    await page.getByRole("button", { name: "请求审批", exact: true }).click();
    await confirm("请求审批");
    await page.getByRole("button", { name: "批准", exact: true }).click();
    await confirm("批准计划");
    await page.getByRole("button", { name: "创建执行 Run" }).click();
    await confirm("启动 Run");
    await page.getByRole("tab", { name: "实验数据" }).click();
    await page
      .getByRole("link", { name: "查看曲线" })
      .click({ timeout: 90000 });
    await expect(
      page.getByRole("heading", { name: "IV 测量曲线" }),
    ).toBeVisible();
    const pending = page.waitForEvent("download");
    await page.getByRole("button", { name: "下载原始 HDF5" }).click();
    const bytes = readFileSync((await (await pending).path())!);
    expect(bytes.subarray(0, 8).toString("hex")).toBe("894844460d0a1a0a");
    await expect(
      page.getByText(createHash("sha256").update(bytes).digest("hex"), {
        exact: true,
      }),
    ).toBeVisible();
    expect(advances).toBe(0);
  });
}
