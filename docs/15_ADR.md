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


## D03 开发基线决策（2026-10-17）

- ADR-020：PostgreSQL 18 + Psycopg 3.3.6，使用 Alembic 1.20.0（SQLAlchemy 2.1.5）管理三个显式迁移批次。迁移使用审阅后的 SQL，不引入领域 ORM；锁定依赖，数据库集成测试禁止内存替身。[Psycopg 安装](https://www.psycopg.org/psycopg3/docs/basic/install.html)、[Alembic 事务迁移](https://alembic.sqlalchemy.org/en/latest/tutorial.html)。
- ADR-021：D03 仅创建发放门关闭的 READY Run，固定 task_identities 与 attempt_no=1；实际 Task 表、资源领取及执行放在 D04。审批失效时只对从未发放的 Run 建立静止证据，未知执行态拒绝处理。
- ADR-022：应用用例以受信任身份和配置端口作为边界，D03 显式测试身份及资源/风险 scope；不把内部 actor ID 参数宣称为 HTTP 认证。身份与成员共享锁串行化权限修改。每次启动用数据库当前时钟核验期限。
- ADR-023：幂等唯一约束使用 INSERT ON CONFLICT DO NOTHING 等待获胜事务，再在 READ COMMITTED 新语句读取提交结果；避免在已失败事务继续查询。过期记录本期不自动回收，重复键不能重新产生副作用。

状态为 Accepted for development；完整操作及边界见 D03_DATABASE_DEVELOPMENT.md。不代表现场批准。


## D04 开发基线决策（2026-10-18）

- ADR-024：中央 PostgreSQL 与近端 SQLite journal 分开持久化；模拟设备动作记录另存文件，以真实进程退出验证不会盲重放。近端文件不充当中央业务权威。
- ADR-025：发送尝试先于传输提交，未知结果牺牲可用性而不重试动作；显式恢复依赖可验证结果，无法证明时持续隔离。
- ADR-026：离线 HMAC 及 POSIX 单进程锁只用于当前模拟适配器；生产 mTLS、凭据生命周期及目标操作系统适配另行验收。恢复代际采用全部网关确认的保守全局屏障。

状态为 Accepted for development；不是现场批准。细节见 D04_EXECUTION_DEVELOPMENT.md。

## D05 开发基线决策

- ADR-027：首个正式采集适配为 IV/HDF5；不可覆盖文件先持久化，Dataset/血缘/event 后原子提交。Manifest 引用原发放读回快照，不能拿计划版本冒充设备观察。
- ADR-028：JetStream 为至少一次通知；发布 claim 独立存储，旧 token 不确认新领取；inbox 与投影效果原子提交，乱序不会回退对象。
- ADR-029：停止为独立持久请求，绑定原 epoch/命令/载荷；模拟有限动作边界确认，提前停止记录拦截迟到原包。所有停止已确认才允许资源释放/代际切换。

以上为开发基线，不代替生产身份/网络安全或真实设备急停审批。验证范围与限制见 D05 开发说明。

## D06 开发基线决策

- ADR-030：首版提供显式 Chat Completions 协议，OpenAI/DeepSeek 参数独立映射；能力声明不等同实际兼容。Responses 与自定义端点另行验收。
- ADR-031：模型仅产生提案；SSE 终态、唯一调用 ID、授权输入工具集合和 Schema 全部校验后才交付。部分流失败不重试拼接，不自动切换供应商。
- ADR-032：官方域名 HTTPS allowlist、无重定向/环境代理、环境变量 SecretStore；token 保守预留约束尝试预算，未知 usage 不为零。生产密钥/出站策略与费用账单需后续服务实现。

状态：Accepted for development。协议与现场/生产验收分别记录，详见 D06 开发交接。

## D07 开发基线决策

- ADR-033：LangGraph 负责 Agent 条件路由，ALAP PostgreSQL 负责 JSON checkpoint/提案/工具 ledger 同事务提交；不以框架回放代替副作用幂等。
- ADR-034：Agent/Skill 导入不执行；发布静态契约/依赖/权限校验后固定版本。运行 bundle 固定，但禁用或撤权阻止后续调用；execution Skill 只交给实验引擎。
- ADR-035：模型调用前预留预算并提交 inflight；未提交结果的模型调用恢复时失败，不盲重试。上下文以完整安全边界和配对工具交换为单位，记录裁剪来源。

状态：Accepted for development。生产身份、管理 API、交互式恢复与长期知识仍需后续验收。

## D08 开发基线决策

- ADR-036：MCP 首版固定 2025-11-25 Streamable HTTP 子集，审核 IP/URL、拒绝重定向/环境代理；发现不授权，仅可信管理员批准的结构化作用域只读工具可进入 Agent。
- ADR-037：知识/记忆/分析携带不可变来源版本与 hash，ACL/成员/数据状态在读取、checkpoint 恢复及提交时重新检查；旧上下文不延续撤销权限。
- ADR-038：远端调用先写 INFLIGHT，未知结果不重放，已成功结果供 checkpoint 恢复复用；数据事件唤醒按证据去重和预算限制，计划按结构内容建立数据库唯一业务指纹。

状态：Accepted for development。协议版本扩展、身份服务、常驻 worker 和科学算法验收分别交付。

## ADR-039 · D09 本地身份与独立资源授权

采用可撤销、短时效、数据库仅存摘要的 opaque Bearer token 作为本地部署首个身份适配。管理角色与实验/仪器/风险授权独立；可信运维初始化身份，不提供匿名自助升级。OIDC/JWKS/refresh-token 适配留给企业部署扩展，不能将当前身份实现称为 SSO。

## ADR-040 · 通用 API 幂等保守恢复

模型/远端调用不能与 HTTP 请求账本假装处于一个数据库事务。API 先写 INFLIGHT，再调用已有业务用例，最后保存脱敏结果；中断窗口返回 EXECUTION_UNKNOWN 而非自动重试。已知请求重放仍复核当前权限，检索/分析不缓存已过期授权结果。D03 原子业务幂等继续有效。

## ADR-041 · 单一接口契约与未知指标

HTTP 路由和请求校验来自生成的 OpenAPI，版本化共享结构仍来自 JSON Schema。仪器没有新鲜遥测时为 UNKNOWN；usage 未返回时标未知，费用/延迟无依据为 null。D09 使用数据库 trace 聚合当前主体实验指标，不包装为供应商账单或全平台可观测性。

## ADR-042 · D10 同源 Web 与内存身份

Web 使用 Next.js App Router；浏览器调用同源 API，由构建时受控服务地址代理。opaque Bearer 只放内存，不进入 localStorage/sessionStorage/URL；刷新重新登录。企业 SSO 与持久会话另行设计。前端权限只服务交互，后端逐请求鉴权才是依据。

## ADR-043 · D10 事件驱动快照与有限预览

SSE 通知到达后重新读取权威快照，游标缺口触发重同步；失联禁用写操作，撤权清除数据。曲线端点通过数据服务先后检查 scope/checksum，限制有限 IV 序列和预览点数，原始文件单独下载。审批和 Run 操作绑定版本，未知提交保留幂等键，不自动生成新请求重放。
