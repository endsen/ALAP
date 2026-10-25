# D12d.3 HTTPS 重试边界

2026-10-24，第十四批；关联 EVAL-17/21。D12d.3 尚未完成。

扩展验收 fixture 的 max_attempts 配置，并复用流式故障的终态、数据库和用量断言。两种供应商格式各覆盖连续 429 与部分 SSE 后超时，共四项。专用 profile 为 timeout_seconds=2、max_attempts=3；请求经部署 API、独立常驻 Agent、实际 HTTPS/SSE 替身，不调用线上供应商、不手动推进 Agent。产品代码、镜像、依赖、公共契约及 Web 没有变更。

四项部署验证通过：连续 429 各产生三次 HTTPS 请求，部分不完整工具分片后保持连接六秒的场景各只有一次请求。最终 FAILED/done、MODEL_FAILURE，iterations=1，预算预留保留；无成功模型事件、无工具提交/提案，以及计划/审批/Run/Task/Command/Dataset 写入。全部场景结束后再次核对请求次数，未见常驻 worker 重放。API 保留未决逻辑请求、reported_tokens 与费用为 null；不宣称供应商实际计费为零。见 `d12d3-retry-https-evidence.json` 和 `d12d3-retry-https-run.txt`。

替身与模型专项 81 项通过。完整后端 **604 项通过（545.98 秒）**，真实 PostgreSQL/NATS 集成未跳过，Ruff/格式、生命周期参考、合订本、OpenAPI/契约、依赖检查通过，见 `d12d3-retry-https-backend-validation.txt`。无需重复未改动 Web 的浏览器门禁。重试后成功、预算耗尽、取消和剩余权限矩阵仍待补，不进入 D12d.4 或 D13，未推送 GitHub。

取消路径源码审查：AgentRuntime.cancel 与 step 均持有相同运行独占锁，PostgresAgentStore.exclusive 使用 pg_try_advisory_lock；已有 `tests/integration/test_background_workers.py` 明确验证运行中取消得到 RUN_BUSY，不能拿模型客户端的 Event 取消单元测试代替用户 API 取消验收。后续应独立复现并明确请求/确认语义，本批未修改该行为。

最终八服务恢复运行，控制模式 ACTIVE，首页 200/匿名 API 401。测试库/角色、有效 token、启用测试配置、活动运行和待发布事件均为 0；设备命令保持 45，原有 15 份 COMMITTED 文件校验和通过，QA 端口与隔离模型网络已移除。见 `d12d3-retry-https-final-runtime.json`。
