# D12d.3 MCP Schema 漂移与在途撤权

2026-10-26，第二十七批。关联 FR-006/010/014/024/027、NFR-001/002/012 与 EVAL-20。D12d.3 尚未完成。

沿用后端 a7a87199/Web fd41b31a、d12_002，以及独立回环 MCP 容器、受限 Agent 数据库角色、管理容器注册/真实 HTTP 发现、管理 HTTP API 授权。没有放宽地址或数据库权限；本地 TLS 模型替身，无线上模型或真机。专用测试 MCP 连接 timeout=60 秒，服务响应屏障 50 秒上限。

**4 项常驻部署案例通过**，OpenAI/DeepSeek 格式各两项：

- Schema 漂移：已审批旧工具并发布绑定的 Agent v2，在真实 HTTPS 首片后将服务端 outputSchema.value 从 integer 改为 string，再放行模型响应。运行期实际 tools/list 发现新 hash，使旧工具 current=false、旧 grant revoked=true；新增工具 current=true 但 grant 数为 0。运行 FAILED/MCP_REVOKED，未发送 tools/call，无 mcp_calls/Agent ledger/history/提案。
- 在途撤权：服务端收到真实 tools/call、核对注入的实验和设备范围并阻塞响应；父进程只读确认 mcp_calls=INFLIGHT 后，经管理 HTTP API revoke，随后释放真实响应。返回值不发布到 Agent，mcp_calls=UNKNOWN、result=null；FAILED/MCP_REVOKED、Agent ledger/history/提案均为 0。此 UNKNOWN 表示远端已处理但当前结果不可用于继续，不代表远端操作已撤回。

每项 HTTPS 模型请求 1；证据中的 mcp_requests 仅计 tools/call，漂移为 0、在途为 1，不含初始化/通知/工具发现。四项计划/审批/Run/Task/Command/Dataset 写入均为 0。在途失败后重新授予原工具权限，然后所有终态统一重启 worker 并等待新进程空 tick；状态/轨迹/ledger/请求数保持不变，没有 UNKNOWN 重放。此为终态不重放，不是主动恢复 SUCCEEDED 缓存的测试。

证据 `d12d3-mcp-runtime-evidence.json`，日志 `d12d3-mcp-runtime-run.txt`。完整后端 **642 项通过（587.88 秒）**，真实 PostgreSQL/NATS 未跳过，Ruff/格式、契约/OpenAPI/生成文档和依赖检查通过，见 `d12d3-mcp-runtime-backend-validation.txt`。收尾八服务运行、模式 ACTIVE、d12_002/镜像一致；首页 200/匿名 API 401。测试库/角色/token/启用测试配置及身份/成员权限/MCP 连接与授权/活动运行/待确认取消/待发布事件均为 0；命令保持 45、15 份 COMMITTED 文件校验通过，QA 端口和隔离模型网络移除，见 `d12d3-mcp-runtime-final-runtime.json`。fixture 在场景结束后恢复 Schema 标记；finally 移除专用 MCP/worker/模型容器和网络、撤销所有测试工具 grant、禁用连接及模型/Agent v1/v2/Skill/令牌，审计历史保留。

本批仅扩展验收 fixture/入口/记录，无产品业务、迁移、依赖、镜像、Web/API 契约变化，不重复浏览器验收。下一批优先补 MCP SUCCEEDED 结果已落盘而 Agent checkpoint 未提交的独立进程恢复及缓存撤权；完整受限字段/页面矩阵继续保留。不进入 D12d.4/D13，未推送 GitHub。
