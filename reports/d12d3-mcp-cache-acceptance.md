# D12d.3 MCP 成功缓存的中断恢复

2026-10-26，第二十八批；关联 FR-006/010/014/024/027、NFR-001/002/007/012 与 EVAL-08/20。D12d.3 尚未完成。

沿用后端 a7a87199/Web fd41b31a、d12_002、独立回环 MCP 服务与本地 TLS 模型替身。临时管理容器进行真实注册/发现，授权/撤权经实际 HTTP API；常驻 Agent 保持原数据库角色，没有放宽地址或权限。

**4 项部署案例通过**：OpenAI/DeepSeek 各保留授权与恢复前撤权。真实远端 tools/call 收到请求后阻塞响应；父进程观察真实 INFLIGHT、Agent checkpoint=RUNNING/tools、history/ledger=0。独立维护进程仅用 SELECT FOR UPDATE 持该 AgentRun 行锁，不改数据，再释放 MCP 响应。等待 mcp_calls=SUCCEEDED/value=3，Agent checkpoint/版本仍旧，pg_blocking_pids 确认 1 个会话被持锁会话阻塞，然后 SIGKILL 专用 worker。四项退出码均 137、非 OOM；杀死后与释放行锁后重复比较完整 checkpoint/版本/缓存/ledger，均保持边界不变。

恢复时先重建独立 MCP 服务，再通过专用启动屏障 exec 原 Agent server；屏障仅用于避免 loopback 服务启动竞争，不替代运行时逻辑。没有手工 advance、终态/缓存 seed 或数据库状态修补。行锁等待与启动屏障均有时间上限，持锁进程 finally 释放事务。

保留授权：恢复 COMPLETED，缓存的 call_id/tool_id/input_hash/state/result 完全保持，Agent ledger/history 各一，模型 iterations=2、预留 128000；模型通过真实 tool exchange 收到 value=3。每项远端 tools/call 总数仅 1、HTTPS 模型请求 2。

恢复前撤权：worker 停止且行锁释放后，经管理 API 撤销旧 grant，再启动恢复。FAILED/MCP_REVOKED，history/ledger=0，iterations=1、预留 64000；原 SUCCEEDED 缓存仍作为审计数据保留，但不进入 Agent 上下文或提案。每项远端 tools/call 1、HTTPS 模型请求 1。未在此路径恢复授权，不将它写成重授权测试。

四项计划/审批/Run/Task/Command/Dataset/提案写入均为 0。所有终态后再次重启 worker、等待新进程空 tick，状态/轨迹/ledger 与调用计数完全不变。证据 `d12d3-mcp-cache-evidence.json`，日志 `d12d3-mcp-cache-run.txt`。其中 mcp_requests 仅计 tools/call，不含恢复时重新握手/发现。

完整后端 **642 项通过（599.42 秒）**，真实 PostgreSQL/NATS 未跳过，Ruff/格式、契约/OpenAPI/生成文档和依赖检查通过，见 `d12d3-mcp-cache-backend-validation.txt`。最终八服务运行、模式 ACTIVE、d12_002/镜像一致；首页 200/匿名 API 401。测试库/角色/token/启用测试配置及身份/成员权限/MCP 连接与授权/活动运行/待确认取消/待发布事件均为 0；命令保持 45、15 份 COMMITTED 文件校验通过，QA 端口和隔离模型网络移除，见 `d12d3-mcp-cache-final-runtime.json`。本批仅新增验收工具、测试启动屏障和记录，无产品业务、迁移、依赖、镜像或 Web/API 契约变化，不重复浏览器验收。finally 清理专用容器/网络、撤销工具授权并禁用连接/模型/Agent v1/v2/Skill/token，保留审计历史。

这是只读 MCP 工具在指定持久化边界的进程崩溃证据，不是物理断电或远端物理写的 exactly-once 保证。下一批优先补受限字段/页面矩阵，继续审查剩余故障组合及边缘失联/证书身份映射缺口。不进入 D12d.4/D13，未推送 GitHub。
