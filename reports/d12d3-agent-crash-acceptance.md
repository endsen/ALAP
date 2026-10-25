# D12d.3 部署 Agent 强制中断与取消恢复

2026-10-24，第十八批；关联 EVAL-08/17 与持久化取消边界。D12d.3 尚未完成。

复用既有新镜像/d12_002、隔离 HTTPS cancel_hold 替身及独立常驻 Agent。两供应商格式各运行保存取消请求后中断、未取消的中断对照，共四项。服务端发送第一个不完整工具参数片后等待 release，客户端已提交 model_reserved、实际状态 RUNNING。只对专用 agent-drill 容器发送 SIGKILL，核对退出码 137 且 OOMKilled=false；没有停止或强杀常规 Agent/Engine/Gateway。

停止后 API 状态/轨迹与中断前完全一致，不能凭进程已死就伪装终态。随后释放旧 HTTPS 连接并显式启动原容器中的新 worker 进程；无人工 advance、无 checkpoint 种子替换或数据库手工修改。取消组通过真实 API 保存的意图恢复后收尾 CANCELLED/done，轨迹 prior_stage=inflight/model_outcome_unknown=true；对照组收尾 FAILED/MODEL_INTERRUPTED，不自动重放不确定模型调用。

四项部署案例全部通过。每项预算预留保留、iterations=1、HTTPS 请求=1、无 model_completed、零工具/提案/计划/审批/Run/Task/Command/Dataset 写入。确认终态后再次重启 worker，等待新进程空 tick，状态和轨迹不变；全部场景结束后再核对请求总数仍各为 1。见 `d12d3-agent-crash-evidence.json` 与 `d12d3-agent-crash-run.txt`。

完整后端 **615 项通过（579.66 秒）**，真实 PostgreSQL/NATS 集成未跳过，格式/lint、契约/OpenAPI、生成及依赖检查通过；见 `d12d3-agent-crash-backend-validation.txt`。本批只增加验收入口/故障脚本，无产品业务、公共契约、Web、迁移、依赖或镜像变更；不重复上一批已通过的部署浏览器验收。证据属于显式 SIGKILL/显式重新启动，不是自动重启策略、物理断电、已提交工具恢复或现场设备安全停止。普通 HTTPS 替身，无线上模型调用。后续继续剩余矩阵、权限与预算场景，不进入长测/D13，未推送 GitHub。

最终八服务运行、控制模式 ACTIVE、d12_002/新镜像摘要一致，首页 200/匿名 API 401。测试库/角色/token/启用测试配置/活动运行/待确认取消/待发布事件均为 0，命令保持 45，15 份 COMMITTED 文件校验通过，QA 端口与隔离模型网络移除。见 `d12d3-agent-crash-final-runtime.json`。
