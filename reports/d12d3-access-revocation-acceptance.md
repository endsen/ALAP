# D12d.3 提交人撤权后的受限终态收尾

2026-10-25，第二十三批，关联 FR-010（访问隔离）、FR-014（提案边界）、FR-027（受控轨迹）、NFR-001/002/012（授权、一致性、最小权限）与 EVAL-22；实现 Agent 当前成员/设备范围复核及 checkpoint/trace 同事务约束。D12d.3 尚未完成。

原实现只拒绝访问，可能令撤权后的 AgentRun 长期保持 READY/RUNNING。新数据库测试先复现：主体禁用、成员撤权、设备范围缩减在调用前/模型返回前/已提交工具请求三个位置均未收尾，首轮 10 失败/2 通过（其中一项为新增端口尚未实现），见 `d12d3-access-revocation-before.txt`。

已编码 AgentStore.fail_revoked_access 端口及 PostgreSQL 适配器；运行时仅在 FORBIDDEN 后持原 session advisory lock 进入收尾，检查同一提交人、固定 bundle hash、当前主体/成员/资源权限失效。只有非终态且当前权限仍失效才 CAS 更新 FAILED/ACCESS_REVOKED，并同事务追加 blocked trace，记录 prior_stage 和 model_outcome_unknown。保留已提交 history/pending/预算，未提交模型结果、工具 ledger 和提案不发布；原访问仍返回 FORBIDDEN，不提供撤权后的状态读取例外。普通工具拒绝、错误 actor 或权限已恢复不能借此强制失败；已完成运行不改写。

修复后与既有 Agent/知识撤权/取消联动专项 **68 项通过（95.89 秒）**，见 `d12d3-access-revocation-targeted.txt`。随后新增三类提案提交前撤权、真实数据库审计触发器拒绝与整事务回滚、所有权连接终止不重连、撤权在收尾前恢复的两种竞态，完整后端 **638 项通过（609.75 秒）**，包含本批全部 19 项新增测试；真实 PostgreSQL/NATS 未跳过，Ruff/格式、契约/OpenAPI/生成文档和依赖检查通过，见 `d12d3-access-revocation-backend-validation.txt`。终态后重授权不重放，模型结果未知时即使恢复权限也按 MODEL_INTERRUPTED 处理。

本批更新源代码、端口、测试和持久化设计章节及生成合订本；无新迁移、依赖、HTTP/Web 契约。普通数据库调用前/返回前钩子提供 I 级竞态证据，不冒充真实 HTTPS/独立进程部署证据。尚未重建部署镜像，既有部署镜像仍为上一基线，不能将环境健康视为新修复已部署。环境收尾：八服务运行、模式 ACTIVE、schema d12_002/既有镜像一致；首页 200/匿名 API 401。测试库/角色/token/启用测试配置/活动运行/待确认取消/待发布事件以及本批沿用核对的测试身份权限均为 0；命令保持 45、15 份 COMMITTED 文件校验通过，QA 端口和隔离模型网络移除。见 `d12d3-access-revocation-final-runtime.json`。

下一批先按部署升级流程验证新镜像与非管理员提交人在真实 HTTPS 响应期间撤权，再补 MCP 授权故障及受限字段/页面矩阵。不启动 D12d.4/D13，未推送 GitHub。
