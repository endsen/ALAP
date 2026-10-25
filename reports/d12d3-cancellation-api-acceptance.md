# D12d.3 当前取消 API 边界

2026-10-24，第十五批；关联 EVAL-17、Agent 所有权与取消语义。D12d.3 尚未完成，运行中取消请求机制仍是产品缺口。

新增部署入口，经真实 Web/API、独立常驻 Agent 与隔离 HTTPS/SSE 模型替身验证两供应商各两种场景。未改产品业务代码、公共契约、Web、镜像、迁移或依赖。使用既有 read_timeout 模式和 2 秒 profile，无线上供应商调用、无真机操作。

调用前：只停止专用 agent-drill，正式 API 创建 READY AgentRun 后取消，状态 CANCELLED/done。相同 Idempotency-Key 重放返回完全相同结果；重启专用 worker，最终模型请求为 0、iterations=0、预算预留为 0，轨迹末项 cancelled。

调用中：等待服务端确认发送第一片不完整工具 SSE，实际状态 RUNNING 时调用取消，返回 409 RUN_BUSY；随后读取仍 RUNNING，不声称已接收取消请求。模型超时后 FAILED/done、MODEL_FAILURE，iterations=1、预算预留保留、HTTPS 请求为 1。当前 cancel 与 step 共用非阻塞运行独占锁，调用中的取消不会持久化请求，也不会向其他进程传播取消信号。

四项部署场景全部通过，各终态再次取消都返回原结果，轨迹不增加；工具/提案、计划/审批/Run/Task/Command/Dataset 写入均为 0。所有场景完成后重新核对请求次数，未发现重放。证据 `d12d3-cancellation-api-evidence.json`，执行日志 `d12d3-cancellation-api-run.txt`。

完整后端 **604 项通过（549.73 秒）**，真实 PostgreSQL/NATS 集成未跳过，格式/lint、契约/OpenAPI、生成一致性和依赖检查通过，见 `d12d3-cancellation-api-backend-validation.txt`。本批建立可复现边界证据，没有实现运行中取消；下一批应先明确持久化请求、owner 权限、进程间观察、提交前复查、终态竞争和 UI 请求/确认语义，再实现与验收，不能通过移除运行锁解决取消。D12d.4、D13 尚未启动，未推送 GitHub。

最终八服务运行、模式 ACTIVE、首页 200/匿名 API 401；测试库/角色/token/启用测试配置/活动运行/待发布事件均为 0，命令保持 45，原有 15 份 COMMITTED 数据文件校验通过，QA 端口与隔离模型网络已移除。见 `d12d3-cancellation-api-final-runtime.json`。
