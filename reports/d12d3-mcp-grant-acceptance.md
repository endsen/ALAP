# D12d.3 MCP 常驻部署授权边界

2026-10-25 验证，2026-10-26 收尾完成，第二十六批。关联 FR-006/010/014/024/027、NFR-001/002/012 与 EVAL-20。D12d.3 尚未完成。

使用既有后端 a7a87199/Web fd41b31a、d12_002。新独立 MCP fixture 容器仅共享 agent-drill 的网络空间、绑定 127.0.0.1:8877，不暴露宿主端口；MCPConnection 的显式 loopback 测试选项沿用现有策略，没有放行私网目标或调整角色权限。LLM 为既有本地 TLS/SSE 替身，无线上服务或真机。

首轮注册准备误用 Agent 数据库角色，因无 mcp_connections INSERT 权限被拒，未开始业务场景；日志 `d12d3-mcp-grant-run.txt` 保留。改为临时维护容器共享测试网络空间、单独挂载管理凭据，经真实应用接口和 HTTP transport 注册/发现；该步骤不冒充管理 HTTP API discovery。Agent 自身继续使用原受限凭据，运行期发现复核使用既有受控数据库函数。

**4 项常驻部署案例通过**：OpenAI/DeepSeek 格式各正常对照和模型响应期间撤销 MCP 授权。每个连接发现后数据库 grant 为 0；经现有 HTTP API 明确批准工具、发布绑定 MCP 的 Agent v2。正常路径真实 MCP initialize/list/call、注入当前 experiment_id/instrument_ids，远端逐项核对范围；结果 value=3 经真实 tool exchange 回到第二轮模型，COMPLETED。每项 MCP tools/call 调用 1、HTTPS 模型请求 2（证据中的 mcp_requests 只计 tools/call，不计 initialize/initialized/tools/list），mcp_calls=SUCCEEDED、Agent ledger/history 各一。

撤权场景等待真实 HTTPS 首个工具片段，经管理 HTTP API revoke 后释放剩余模型响应；撤权发生在完整工具请求提交及派发之前。模型完成一次请求，随后 MCP_REVOKED 阻止远端派发，FAILED，MCP 调用/ledger/history 为 0。两类均无提案、计划、审批、Run、Task、Command、Dataset 写入。所有终态后重启 worker、等待新进程空 tick，状态/轨迹/数据库证据和请求计数不变。此重启仅验证终态不重放，不代表进行中的 MCP 恢复。

证据 `d12d3-mcp-grant-evidence.json`，成功运行日志 `d12d3-mcp-grant-rerun.txt`。模型替身协议专项 **24 项通过**，新增四项防伪工具结果检查。完整后端 **642 项通过（649.85 秒）**，真实 PostgreSQL/NATS 未跳过，Ruff/格式、契约/OpenAPI/生成文档和依赖检查通过，见 `d12d3-mcp-grant-backend-validation.txt`。最终八服务运行、模式 ACTIVE、d12_002/镜像一致；首页 200/匿名 API 401。测试库/角色/token/启用测试配置及身份/成员权限/MCP 连接与授权/活动运行/待确认取消/待发布事件均为 0；命令保持 45、15 份 COMMITTED 文件校验通过，QA 端口与隔离模型网络已移除，见 `d12d3-mcp-grant-final-runtime.json`。finally 移除独立 MCP/worker/模型容器及网络，撤销测试工具授权、禁用测试连接、模型、Agent v1/v2、Skill 和令牌，保留审计历史。

本批只新增验收工具、fixture 模型分支及测试，无产品业务/迁移/依赖/镜像/Web/API 契约改动，不重复浏览器验收。尚未覆盖 MCP Schema 漂移、请求在途撤权、未知结果/缓存恢复的部署路径或线上 MCP 服务；下一批优先补这些边界。未进入 D12d.4/D13，未推送 GitHub。
