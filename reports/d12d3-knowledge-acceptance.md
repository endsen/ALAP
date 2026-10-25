# D12d.3 知识检索注入与运行中撤权验收

测试日期：2026-10-22；2026-10-23 续接收尾；第九批，关联 FR-020–029 的 Agent/上下文/知识权限边界、NFR-002 与 EVAL-03/23。D12d.3 未完成。

新增 `tests/integration/test_knowledge_process_faults.py`，专项 **4 项通过（9.53 秒）**。使用真实 PostgreSQL 与版本化来源，独立 fork 子进程运行产品 AgentWorker/AgentRuntime；父进程仅发送 tick 调度信号及通过资源服务撤权。模型是子进程内 ScriptedModel，未调用供应商 API，也不是独立 HTTPS 或 Compose 常驻循环验收。

| 场景 | 观察结果 |
|---|---|
| 正常检索对照 | 真实 search_knowledge 结果进入第二轮上下文，正常结束，只读 |
| 文献诱导越权 | 注入内容确实出现在 tool 消息，携带 untrusted_source_not_authority，未提升为 system；离线模型返回 execute_device，工具白名单以 TOOL_FORBIDDEN 阻断，Agent FAILED |
| 检索后、下一次模型调用前撤权 | SOURCE_REVOKED，模型总调用保持 1，缓存来源读取被拒绝 |
| 第二轮模型响应期间撤权 | SOURCE_REVOKED，模型总调用 2，结果提交被拒绝；后续 tick 不重放模型 |

四项均只有一次已授权知识检索，无 Agent 提案、计划、审批、执行 Run、Task、Command 或 Dataset 写入。撤权不能撤回此前已经交给模型的上下文；本测试只验证后续使用/提交阻断。脚本化恶意响应不证明真实模型抵抗提示注入的质量。

## 发现的实现缺口

撤权两项的 checkpoint 仍为 RUNNING，分别停在 model/inflight，result=null；后续 tick 继续返回 SOURCE_REVOKED。当前 `PostgresAgentStore.load/commit` 重检来源，导致 `AgentRuntime` 无法通过常规加载/提交写入 FAILED 收尾。这是安全拒绝已有、运行状态收尾未完成，不能宣称完整撤权闭环通过。

下一批优先实现受限的撤权终态收尾：保留历史审计和未知调用事实，禁止再读取/返回已撤销内容、禁止重放模型、禁止提交提案；须验证并发撤权/取消与 owner 锁边界。不能简单关闭 load/commit 的来源检查。真实部署 API/页面对已撤权轨迹的最小状态呈现也尚待验证。

首轮测试将既有错误码误写为 TOOL_NOT_ALLOWED，且将 result=null 误判为应无字段；修正为 TOOL_FORBIDDEN 与 null 后四项重跑通过，未放宽产品校验。

完整后端门禁 **585 项通过（536.46 秒）**，真实 PostgreSQL/NATS 集成未跳过；Ruff/格式、生命周期参考、合订本、OpenAPI/契约和依赖检查通过，见 `reports/d12d3-knowledge-backend-validation.txt`。

2026-10-22 完成测试后，恢复 Compose 的自动审批因服务额度耗尽无法完成，操作未执行；2026-10-23 续接后经正常审批重试成功。最终八服务运行、控制模式 ACTIVE，仅 Web 发布 127.0.0.1:3000；首页 200、匿名 API 401。测试库/角色、有效 token、启用测试配置、活动运行及待发布事件均为 0，部署命令保持 45，15 份 COMMITTED 文件校验通过、无临时故障备份；QA 端口及隔离模型网络已移除。见 `reports/d12d3-knowledge-final-runtime.json`。测试库内撤权 RUNNING 缺口与正常部署无活动运行分开记录，不以测试库清理称为产品终态修复。

本批无产品代码、契约、依赖或 Web 变更；沿用最近完整 Web 门禁，不重复浏览器测试。未推送 GitHub，未进入长测或现场。
