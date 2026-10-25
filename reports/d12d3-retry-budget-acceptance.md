# D12d.3 重试成功与预算边界

2026-10-24，第十九批；关联 EVAL-17/21。D12d.3 尚未整体完成。

仅扩展验收 fixture 的 token_budget、本地 HTTPS 替身及独立入口；产品业务、迁移、公共契约、Web、依赖和部署镜像不变。两种供应商各三个场景，共六项实际 API/常驻 worker/HTTPS 验证通过，不调用线上供应商。所有模型 profile timeout_seconds=2、max_attempts=3。

成功对照：第一请求返回 429，第二请求返回合法只读文本与一份 usage。每项 COMPLETED、result 为固定只读总结、iterations=1、一个 model_completed，内含两个不同 attempt ID；服务端确认两次请求，每次保护性预留 OpenAI 9705 / DeepSeek 9700。API model_completions=1、recorded_attempts=2、logical_requests=1、reported_tokens=100/50/150，费用仍 null。150 只是最终替身响应的报告值，不是两次远端请求的真实费用/消耗证明。

累计预算边界：运行 token_budget=48000，目标包含额外 15000 字节合法文本；实际单次预留 OpenAI 24704 / DeepSeek 24699。每项只发一次请求且返回 429，下一次预留会超过总预算，虽然 max_attempts=3 也不再连接，最终 FAILED/MODEL_FAILURE。服务端始终保持可返回 429，没有通过模拟断网强迫停止。断言实际次数×预留≤预算且下一次会超限；保留 runtime 48000 预留和一个未决逻辑请求，usage/费用为 null。

调用前边界：运行 token_budget=4096，等于输出上限而不足以容纳输入，Agent 在模型预留/连接前以 TOKEN_BUDGET 失败。实际 HTTPS 请求为 0、iterations=0、reserved_tokens=0、logical_requests=0，无伪造成功事件。

所有场景工具/提案/计划/审批/Run/Task/Command/Dataset 写入均为 0。每项三次重复读取用量相同；全部完成后显式重启专用 worker，等待新进程空 tick，再核对统计与轨迹相同、请求数不变。见 `d12d3-retry-budget-evidence.json` 和 `d12d3-retry-budget-run.txt`。失败场景的 API recorded_attempts=0 仅表示无已提交完成尝试记录，不能当作没有远端调用；服务端请求数独立记录。

模型与替身专项 **83 项通过（0.96 秒）**。完整后端 **617 项通过（573.84 秒）**，真实 PostgreSQL/NATS 集成未跳过，格式/lint、契约/OpenAPI、生成与依赖检查通过，见 `d12d3-retry-budget-backend-validation.txt`。未修改产品 Web，不重复上一批浏览器验收；不声称真实账单、全部多完成/跨实验聚合、上下文或并发预算已验。继续剩余权限/版本漂移矩阵，不进入长测/D13，未推送 GitHub。

2026-10-25 续接完成环境恢复和审计：八服务运行、模式 ACTIVE、schema=d12_002，镜像摘要与第十七批升级一致；首页 200/匿名 API 401。测试库/角色/token/启用测试配置/活动运行/待确认取消/待发布事件均为 0，命令保持 45，15 份 COMMITTED 文件校验通过，QA 端口与隔离模型网络移除。见 `d12d3-retry-budget-final-runtime.json`。
