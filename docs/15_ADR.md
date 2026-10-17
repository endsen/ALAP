# 15 · Architecture Decision Records（ADR）与开放设计问题

> v3.1 开发基线；原始 v3.0 保存在根目录合订本与 ZIP。新增平台范围见第 17、18 章，契约规则见第 19 章，实施顺序以第 20 章为准。

**ADR 格式**：编号、状态、决策、背景、备选方案、原因、影响与复审触发。此处状态为本设计建议的 *Proposed*，不是项目现场已审批通过。

## ADR-001：Planner 集中决策，Instrument Agent 局部自治
- **状态**：Proposed
- **决策**：实验级计划由 Planner 形成建议、Scheduler 仲裁；设备 Agent 限定在已授权能力和范围内。
- **备选**：每个设备 Agent 完全点对点自主；中央 Planner 控制每个采样点。
- **理由**：集中仲裁更容易保证资源独占和可追溯；边缘自治减轻延迟/断网影响。
- **后果**：引入 Proposal/Approval/Lease 机制；不追求完全 P2P 自主。

## ADR-002：Agent Platform 与 Experiment Engine 解耦
- **状态**：Proposed
- **决策**：LLM 规划/记忆用 Agent Runtime，真实任务状态/审批/设备命令由确定性 Engine 管理。
- **理由**：LLM 可更换，模型重试不能隐式复现硬件副作用。
- **影响**：两套状态体系需通过 ID/事件/CommandLedger 对账。

## ADR-003：Web 使用 Next.js，API 使用 FastAPI
- **状态**：Proposed
- **理由**：Web 应用丰富，Python 仪器/分析生态成熟。
- **取舍**：需要明确 OpenAPI 代码生成与前后端类型一致性。

## ADR-004：MVP 采用模块化单体与独立 Gateway
- **状态**：Proposed
- **理由**：早期不拆多余微服务，先解决领域边界与安全。
- **触发复审**：多团队独立部署、流量瓶颈或强隔离需求。

## ADR-005：PostgreSQL 为业务状态权威，NATS 为事件通知
- **状态**：Proposed
- **理由**：事务权威和至少一次消息分发分离；Outbox/消费幂等使故障恢复可控。
- **风险**：事件重复，必须业务去重；消息层 exactly-once 不能推出设备 exactly-once。

## ADR-006：Gateway 就近运行，复用旧桥接
- **状态**：Proposed
- **理由**：不同物理地点 TCP/GPIB/USB 均可兼容，采样和故障处理靠近设备。
- **风险**：旧桥接功能差异很大，必须逐个适配/认证。

## ADR-007：MVP 数据使用 PostgreSQL + HDF5/Zarr
- **状态**：Proposed
- **理由**：结构化状态与科学数组分离，便于原始数据溯源。
- **复审**：多站点海量流数据/远程访问对对象存储要求提升。

## ADR-008：所有物理副作用必须使用 CommandLedger 与 UNKNOWN
- **状态**：Proposed
- **理由**：网络 ACK 丢失无法证明物理操作没发生，禁止盲重试。
- **影响**：增加对账 UI 与人工介入工作量，但更符合硬件控制的可靠性需求。

## ADR-009：硬件安全不依赖 AI / Browser
- **状态**：Proposed
- **理由**：模型不确定、网络可能中断，紧急安全必须由独立系统保证。
- **验收**：需逐设备安全负责人签字，不能靠文档声明已安全。

## ADR-010：ARTEX 借鉴设计思想，不移植不受控代码
- **状态**：Proposed
- **理由**：借鉴 Planner–Worker/共享状态/事件溯源，不把安全测试领域的命令模型直接带进仪器控制；ARTEX 源仓库历史版本与许可需单独核查。

## 开放问题（Open Decisions）

| ID | 待确认 | 决策责任方 | 影响 |
|---|---|---|---|
| OD-01 | 各设备具体型号、固件、原始桥接 API | 仪器维护负责人 | Capability、Driver、安全 |
| OD-02 | 网络拓扑、VPN/mTLS 和边缘 PC OS | 基础设施 | Gateway/安全 |
| OD-03 | 系统峰值并发 Run 与数据吞吐 | 产品/现场 | 性能、存储、调度 |
| OD-04 | 真机审批人、是否双人审批、24h 值守 | 实验室负责人 | 安全/权限 |
| OD-05 | 云模型或本地模型，科研数据是否可外发 | 数据治理负责人 | LLM/存储/网络 |
| OD-06 | 事件保留期、实验数据保存期 | 数据治理负责人 | SSE/备份 |
| OD-07 | RPO/RTO 目标 | 项目负责人 | 备份/运行恢复 |
| OD-08 | 物理同步精度、硬触发/DAQ 是否存在 | 实验工程师 | 工作流设计 |
| OD-09 | 是否采用完整 Bluesky/QCoDeS RunEngine | 实验工程师 | Skill Execution |

## 决策变更流程

开放问题形成备选与样机证据 → 形成 ADR → 产品/架构/仪器安全负责人评审 → 状态改 Accepted → 更新 SRS、Schema、测试与部署规程。未经批准不得将 Proposed 视为生产配置。

## v3.1 开发基线决策

以下状态为 Accepted for development（依据本轮用户授权与工程实现选择），不代表真机安全审批。

- ADR-011：专用 Agent 由 ALAP 管理，模型经 API 适配；首批 OpenAI/DeepSeek，能力检测与供应商协议分离。
- ADR-012：独立 Skills、MCP、模型、用量、轨迹、知识管理页面纳入正式范围。
- ADR-013：按 P0–P7 分层实施；端到端验证在依赖就绪后执行，不提前构造演示替代后端。
- ADR-014：`contracts/` 为共享结构唯一源，生成 OpenAPI 共享组件；根 `src/alap/` 为模块化后端，领域不依赖框架。
- ADR-015：实验 SSE 使用 experiment_seq，保留 aggregate_seq；快照同时提供水位。
- ADR-016：命令绑定恢复 epoch；恢复流程拒绝默认重放；完整事务/状态表在 P2 前冻结。

OD-05 中接入方式已确认为 API；模型供应商、真实凭据和具体科研数据出域许可仍按部署环境确定。旧 ADR 的现场相关 Proposed 状态保持，不能由开发基线代替现场签署。

## D02 开发基线决策（2026-10-17）

- ADR-017：Run/Task/Command 独立状态；首期在有限 Task 边界暂停，终态不重开。UNKNOWN 必须先对账，原命令不回到 NOT_DISPATCHED。
- ADR-018：状态转换为无 I/O 的纯决策，证据绑定对象/版本/hash/期限；实际认证与证据核验由受信任应用适配器完成，状态与 effects/audit/outbox 原子落库。
- ADR-019：租约终态不等于资源可用；claim、fencing 与隔离独立持久化。PostgreSQL 采用显式锁顺序与约束，网络调用在事务外。

状态为 Accepted for development；完整说明见第 21、22 章。真实数据库与设备故障验收尚待 D03–D05。
