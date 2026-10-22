# D12d.3 首批故障证据与交接

日期：2026-10-21。**本批验证不等于 D12d.3 整项通过**，不启动 D12d.4/D13。

- 已核对 EVAL-01–24 的证据层级、测试引用和缺口，详见 `docs/D12D_FAULT_MATRIX.md`。U/I/P/C/F 明确区分，现有正常链路不替代注入测试。
- 独立 Engine 与 Gateway 进程之间新增真实 socket 代理故障，专项 **2 项通过（18.70 秒）**。转发前断开：一个 UNKNOWN Command、动作 0，重启仍保持恢复阻断；执行完成后丢弃响应：一个 UNKNOWN Command、动作 1，重复同命令仍动作 1，重启对账后 PAUSED，后继冻结。连续调度观测没有自动重发。`reports/d12d3-wire-faults.txt` 为专项报告；HTTP 仅在 loopback，非生产 mTLS/真实设备 ACK 验收。
- 实际 Compose NATS 停服后创建唯一未审批测试计划，数据库两条事件持续待发布、API snapshot event_cursor=2，无 Run/审批。恢复后待发布 0、JetStream 消息 564→566；再重启 outbox 后仍 566，设备命令保持 30。使用正常常驻服务、真实 broker 进程和持久卷，无进程内发布替身。证据 `reports/d12d3-messaging-evidence.json`，实际开始/结束时间包含在报告中；不是 24 小时负载。
- 演练前要求无活动 Run/outbox 积压，维护锁防止与备份/其它模拟维护并发。finally 恢复 NATS/outbox，撤销本次两个令牌；审计和未审批计划保留。进程故障使用随机隔离数据库，结束后清理测试库/角色。没有真机、外部模型或凭据调用。
- 新增检查入口与测试选择参数，不改领域/应用/适配器业务行为，不新增依赖、迁移或公共契约。Web 未改，不重复 D12d.2 的完整浏览器门禁。
- 统一后端门禁 **574 项通过（437.62 秒）**，真实 PostgreSQL/NATS 集成未跳过，Ruff/格式、契约/OpenAPI、生成文档及依赖检查通过，见 `d12d3-backend-validation.txt`。最终八服务运行、模式 ACTIVE、首页 200/匿名 API 401；QA 端口关闭，测试库/角色、有效 token、活动 Run、待发布事件均为 0，命令总数保持 30，见 `d12d3-final-runtime.json`。

剩余工作：实际模型 HTTP 异常/注入与运行期撤权、批准后变更、活动数据失败、过期/不稳回读、其它权限与逐页异常路径。实现审查另发现边缘失联监护与证书主体/资源映射不能由当前中心 UNKNOWN/mTLS 链验证替代；详见矩阵，必须继续处理。当前及 D12d.2 本地变更均未推送 GitHub。
