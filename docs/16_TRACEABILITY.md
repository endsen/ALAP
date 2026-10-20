# 16 · 需求—模块—契约—验证追踪表

> v3.1 开发基线；原始 v3.0 保存在根目录合订本与 ZIP。新增平台范围见第 17、18 章，契约规则见第 19 章，实施顺序以第 20 章为准。

本表用于设计验收、Issue/PR 评审，完整需求见 `02_SRS.md`；测试编号参见 `12_EVALUATION.md`。

| 需求 | 负责模块/章节 | 契约入口 | 关键验证 |
|---|---|---|---|
| FR-001 | API Auth，04/11 | `openapi.yaml` security | Observer 设备写 403，EVAL-14 |
| FR-002 | Experiment Service，07/09 | `POST /experiments` | 幂等键、重复提交 |
| FR-003 | Planner Agent，05/06 | Agent Manifest + Proposal JSON 示例 | EVAL-01，计划 DAG 校验 |
| FR-004 | Approval Service，04/07 | `POST /experiments/{id}/approvals` | EVAL-12 |
| FR-005 | Agent Registry，05 | `agent_manifest.schema.json` | 配置版本 hash |
| FR-006 | Tool/Skill Registry，05/11 | Schema + Tool Metadata | EVAL-02/EVAL-03 |
| FR-007 | Device Registry，08 | `capability.schema.json`, instruments API | EVAL-14，离线禁写 |
| FR-008 | Scheduler，07 | Command Envelope/Resource Lease | EVAL-06 |
| FR-009 | Gateway/CommandLedger，07/08 | `command.schema.json` | EVAL-04/EVAL-05 |
| FR-010 | ExperimentView，06/09 | Dataset API/ABAC | 跨实验数据拒绝 |
| FR-011 | Data Service，09 | Dataset Manifest | EVAL-10 |
| FR-012 | SSE Service，04/10 | `GET /experiments/{id}/events` | EVAL-07 |
| FR-013 | Run Control，04/07 | `POST /runs/{id}/actions` | EVAL-09 |
| FR-014 | Multi-Agent Coordinator，06 | Proposal/Agent Manifest | EVAL-13 |
| FR-015 | Safety Gateway，08/11 | Command Policy/Fencing | EVAL-02/EVAL-14 |
| FR-016 | Agent Platform，05/06 | Autonomy Envelope | 越界变新提案 |
| FR-017 | Workflow Manager，07 | Plan Revision | EVAL-12 |
| FR-018 | Data Explorer，04/09 | Dataset API | 校验和/元数据导出 |
| FR-019 | Gateway/Deploy，08/13 | Capability + Command | 站点离线演练 |
| FR-020 | Skills Registry，05 | Agent Manifest | 技能版本锁定 |

## 发布审核

1. 所有 MUST 需求均有至少一个通过的自动化或现场测试及存档的结果链接。
2. 所有可影响物理世界的操作，在现场安全清单中有责任人及对应厂商规程。
3. `EVAL-02,03,04,05,06,09,10,11,12,14` 为阻断项；不允许以 Agent 自评“已安全”代替。
4. 文档更改必须更新追踪表；若 OpenAPI/Schema 更新而前端/网关未更新，发布不通过。

## v3.1 新增追踪

| 需求 | 设计入口 | 实施阶段 | 验证 |
|---|---|---|---|
| FR-021/022 | 18 多供应商、17 模型页 | P3/P4/P5 | EVAL-16/17/18 |
| FR-023 | 17 Skills、05 Registry | P3/P4/P5 | EVAL-19 |
| FR-024 | 17 MCP、11 权限 | P3/P4/P5 | EVAL-20 |
| FR-025 | 17 Dashboard、13 观测 | P4/P5 | EVAL-22 |
| FR-026 | 17 用量、18 Adapter | P3/P4/P5 | EVAL-21 |
| FR-027 | 17 轨迹、13 观测 | P2/P3/P4/P5 | EVAL-22 |
| FR-028 | 17 知识、05 Context | P3/P4/P5 | EVAL-23 |
| FR-029 | 17 页面与权限 | P4/P5 | EVAL-18/24 |

上述是规划追踪，不代表用例已执行。当前基础层代码与测试见根目录 IMPLEMENTATION_STATUS.md。

## D02 已执行与后续验证

| 需求范围 | 已落地证据 | 尚未验证 |
|---|---|---|
| FR-004 审批版本绑定 | lifecycle 的审批状态、证据 hash/版本/期限测试 | 数据库权限、计划不可变性、撤销并发（D03） |
| FR-009 命令执行 | tests/test_lifecycle.py：ACK 不代表成功、UNKNOWN 隔离、原命令不重放、取消竞争 | Gateway journal、实际 fencing 与故障恢复（D04） |
| FR-011 数据发布 | 提交证据守卫、损坏后撤回状态；共享状态 Schema | 文件持久化与数据库提交中断（D05） |
| FR-012 事件恢复 | 第 22 章锁顺序、outbox/游标/快照事务方案 | 真实事务、消息重复与 SSE 恢复（D03/D05/D09） |
| 跨接口一致性 | tests/test_contract_consistency.py：六种枚举与共享 Schema、OpenAPI 引用一致 | 实际 API 行为（D09） |

D02 完整本地检查输出保存在 reports/d02-validation.txt；不等价于集成/现场 EVAL 通过。


## D03 验证映射

| 需求 / 故障场景 | 实现与数据库测试 | 边界 |
|---|---|---|
| FR-002 / DB-01 | create_experiment、幂等唯一键；同键并发、不同载荷冲突 | 内部应用服务，HTTP 409 映射在 D09 |
| FR-003/004/017 / DB-02 | 不可变计划、资源/风险权限、审批 hash/版本/期限、替代与撤销；两连接启动竞争、实际 DB 时钟过期 | READY Run，无物理发放 |
| FR-001/010 | 显式 principal/membership；禁用、资源范围、跨实验访问及复合外键拒绝 | 真实登录/RBAC 前端尚未接入 |
| FR-012/027 / DB-04 | 故障注入验证状态/effects/证据/审计/cursor/outbox 全部回滚 | NATS/SSE 在 D05/D09 |
| FR-012 / DB-12 | REPEATABLE READ 快照期间另一事务提交，快照状态与 cursor 保持一致 | 无浏览器事件订阅 |
| 工程迁移 | D03 三批空库 up/down/up、数据库约束与不可变触发器 | 生产使用前向修复，不执行破坏性 down |

测试文件：tests/integration/test_persistence.py；结果见 reports/d03-validation.txt。D04–D13 场景未因此完成。


## D04 验证映射

| 需求 / 场景 | 实现与测试 | 边界 |
|---|---|---|
| FR-003/009，DB-03 | 固定 DAG 任务、三模拟设备、多资源及跨实验竞争 | 内部用例，未部署 worker |
| FR-004/009，DB-05/06 | 发放前重新授权、持久投递、ACK 丢失及进程退出恢复、重复 ID、乱序回执 | 离线 HMAC，非真机认证 |
| FR-009，DB-07/11 | 旧 fencing/epoch 拒绝、租约过期保留 claim、握手恢复代际 | 全局保守阻断，未做生产备份恢复演练 |
| FR-012/027，DB-04 | UNKNOWN 与隔离/审计/outbox 注入失败全部回滚 | 未发布 NATS/SSE |
| 稳定条件 | 原始时间、质量、单位、容差、斜率、持续窗口及鲜度 | 短时模拟窗口，不是设备校准 |

证据：tests/integration/test_execution.py、tests/test_stability.py、reports/d04-validation.txt。IV 数据发布及完整暂停取消恢复属于 D05，不能据此宣布完整 EVAL 通过。

## D05 验证追踪

| 需求/故障 | 实现 | 验证证据 |
|---|---|---|
| FR-011 / DB-09 正式数据与恢复 | DatasetService、Hdf5Store、数据/血缘迁移 | test_datasets、test_artifacts：半上传、事务失败、重复提交、损坏、权限与不重复采集 |
| FR-012 / DB-10 事件投递与去重 | EventService、JetStreamPublisher、inbox/projection | test_events：真实 JetStream ACK 丢失、重投、事务回滚、乱序、游标与权限撤销 |
| DB-08 暂停/取消竞争 | ControlService、Gateway stop journal | test_control：有限边界暂停、完成竞争、未发送取消、停止未知、迟到原包与重启 |
| DB-07/11 资源及代际屏障 | release/bind_gateway/finish_recovery | 停止确认未完成时拒绝资源复用和 epoch 切换 |
| DB-12 一致性快照 | read_snapshot/after | 同事务状态与 cursor、正式 Manifest 可见性、按游标分页补事件 |

本轮统一检查报告为 reports/d05-validation.txt；该报告是本地 Linux 集成证据，未运行本轮远程 CI，不等价于完整生产/现场 EVAL。

## D06 验证追踪

| 需求/验收 | 本期证据 | 后续边界 |
|---|---|---|
| FR-021/022 / EVAL-16 | tests/test_models.py：两个供应商同 Planner 请求统一输出、实际模型与版本；DeepSeek 三项真实联调报告 | OpenAI 无真实凭据，未做实联；Agent Planner 在 D07 |
| EVAL-17 | 分片、重复 ID/键、非法参数/用量、截断、429/超时/取消、预算与响应上限；错误不带远端敏感正文 | 不执行任何设备/工具，多轮 Agent 历史由 D07 扩展 |
| EVAL-18 | 缺失能力/凭据、配置版本、域名策略、外部 Schema 引用拒绝 | 管理界面、集中密钥与生产身份在后续期 |

证据：reports/d06-validation.txt、reports/d06-deepseek-smoke.json；范围见 docs/D06_MODEL_DEVELOPMENT.md。

## D07 验证追踪

| 需求/验收 | 本期实现与证据 | 后续边界 |
|---|---|---|
| FR-020/023 / EVAL-19 | Skill 契约、不可变注册、依赖检查、发布/禁用与运行绑定；tests/integration/test_agents.py | 管理 UI/API、任意代码 worker 未实现 |
| EVAL-03 | 数据消息与系统策略隔离、工具 allowlist、参数/资源/成员权限再次验证 | 不是模型抗注入准确率统计 |
| EVAL-08 | 事务回滚后恢复、已提交提案不重复、inflight 模型保守终止；真实 PostgreSQL/LangGraph | 无模型到 Gateway 直连；现场恢复由执行层验收 |
| EVAL-01/02 | 合法目标产生契约有效提案，越界参数、证据与快照被拒绝 | 本期不自动审批、保存正式计划或执行设备 |
| FR-021/022 | 多轮工具消息配对，协议历史错误在联网前拒绝；tests/test_models.py | 本期没有新增真实 LLM 规划联调 |

上下文预算与完整交换测试见 tests/test_agent_context.py；全套结果见 reports/d07-validation.txt。

## D08 验证追踪

| 需求/验收 | 本期证据 | 后续边界 |
|---|---|---|
| FR-024 / EVAL-20 | 回环真实 HTTP MCP、发现无授权、Schema 变化撤销、作用域注入、防重放和错误测试 | 不含公网兼容性/OAuth/stdio worker |
| FR-028 / EVAL-23 | 来源版本/ACL、实验/仪器/Agent 记忆隔离、旧 checkpoint 撤权生效 | 首版子串检索，无向量 RAG |
| EVAL-10/13 | 实际 HDF5 checksum、COMMITTED 门禁、分析血缘、数据事件/计划结构去重、预算与中断恢复 | 描述统计不代替物理判据；无常驻协作 worker |

tests/integration/test_resources.py、tests/test_mcp_policy.py；完整验收见 reports/d08-validation.txt，范围见 D08 开发交接。

## D09 实现追踪

身份/授权、管理 API、SSE 和密钥接口由 `application/api.py`、`adapters/api`、`adapters/postgres/api.py` 与 `adapters/secrets/encrypted.py` 实现；核心 REST 和管理操作以 `contracts/openapi.base.yaml` operationId 定位。`tests/integration/test_api.py` 覆盖无身份、角色/实验/仪器隔离、审批版本、并发/未知不重放、SSE 重放/撤权、凭据保密、管理生命周期、真实 HTTP 与数据下载；既有 D03–D08 门禁继续回归。生产身份供应商、完整计费、部署容量和现场未用本期测试代替。

| D09 需求范围 | 本期实现与验证 | 仍待后续验收 |
|---|---|---|
| FR-001/002/004/013，NFR-002 | 真正令牌、角色/范围检查、审批链、版本冲突、并发幂等和未知不重放 | Web 操作与生产身份提供方 |
| FR-010/011/012 | 校验后的数据下载、事务内事件页范围检查、SSE 续传/撤权 | 浏览器重连体验与负载 |
| FR-022/023/024/028/029 | 版本配置、凭据加密、Skill/Agent/MCP/知识管理 HTTP | 供应商连通性测试 UI、SSO、主密钥轮换 |
| FR-025/026/027，NFR-009/012 | 实验仪表板读模型；按供应商/模型/Agent/UTC 日统计已记录用量；受限 trace/提案与审计 | 费用价格版本、完整 Gateway 流量、生产 TLS 与性能 |

## D10 实现追踪

| 需求范围 | 实现与验证位置 | 保留边界 |
|---|---|---|
| FR-001/002/004/013，NFR-002 | `apps/web/src/components` 目标、计划差异、审批确认、状态请求；浏览器全流程、只读和冲突路径 | 任意参数编辑器、SSO 尚未实现 |
| FR-010/011/012 | `lib/events.ts`、`lib/hooks.ts` 游标/重连；`application/series.py` 校验曲线；单元/API/浏览器测试 | 压力容量、实时遥测属后续验收 |
| FR-023/026，NFR-009/012 | 持久 Agent Run/提案/轨迹、未知设备状态、错误和加载提示 | 全平台管理/统计页面 D11；部署 D12 |

实际通过项与报告见 `IMPLEMENTATION_STATUS.md`，启动与测试 fixture 边界见 D10 开发交接。模型采用离线替身，设备为模拟器，不构成真实供应商或现场验收。

## D11 实现追踪

| 需求范围 | 实现和验收证据 | 范围限制 |
|---|---|---|
| FR-005/021/022/023 | 控制台 Agent/模型/Skills 版本编辑、校验/发布、差异、禁用、受控测试；tests/integration/test_console.py、Web console.spec.ts | 固定指令策略；Skill 不绕过审批直接执行 |
| FR-024/028 | 真实回环 MCP 发现与独立授权/撤销；知识来源导入、检索/共享/撤销 | HTTP 子集、文本检索，无 stdio/OAuth/向量索引 |
| FR-025/026/027 | 当前用户/实验指标、模型/Agent/UTC 日期筛选、分组 Run 下钻、三类轨迹 | 费用和未返回用量显示未知，命令台账非实时通信 |
| FR-001/029、NFR-002 | 用户/角色比较更新与审计、凭据掩码、直接路由权限、断线禁写、403 清屏 | 本地令牌；企业身份与常驻部署后续验收 |
| NFR-009/012 | TypeScript、表单边界单元测试、真实 API 浏览器回归、桌面/移动端截图 | Chromium 本机验证，非跨浏览器或压力测试 |

入口：docs/D11_PLATFORM_CONSOLE_DEVELOPMENT.md。完成状态及实际测试数以 IMPLEMENTATION_STATUS.md 和 reports/d11-* 验收报告为准。

## D12a 实现追踪（D12 进行中）

| 需求范围 | 实现及验证入口 | 尚未覆盖 |
|---|---|---|
| FR-008/009/019、NFR-002/007 | Gateway HTTP 端口、独立模拟子进程；`test_gateway_process.py` 三设备/HDF5、重启和丢响应一次动作对账 | 常驻 Scheduler、服务端强杀矩阵、跨站点现场 |
| FR-011、NFR-008 | 跨进程采集/提交/确认，重启后回执与动作次数核对 | 集群备份恢复、24 小时数据完整性验收 |
| NFR-012 | `test_gateway_transport.py` HTTPS/mTLS、签名/请求绑定、拒绝重定向及非法入口 | 生产证书注册/轮换/撤销、完整平台 TLS |

本工作项没有修改共享公共 API 或设备命令 Schema。实际状态、报告与后续 D12b–d 门禁见 `D12_INTEGRATION_DEPLOYMENT.md` 及实施状态，不把局部测试作为整期验收。

## D12b.1 实现追踪（常驻服务前置项）

| 需求范围 | 实现及验证入口 | 范围限制 |
|---|---|---|
| FR-008、NFR-002/007 | `adapters/postgres/engine_owner.py` 专用连接/单实例锁；`test_engine_recovery.py` 双进程争用、连接终止、旧实例不重连 | 尚未装配常驻 Scheduler；不等同于跨网络零时延停机 |
| FR-009/013、NFR-004/007 | `application/engine_recovery.py` 恢复屏障；`ExecutionService.cancel_prepared_on_recovery` 事务证据取消和同事务审计 | UNKNOWN/矛盾证据/未确认停止继续阻塞，不自动安全停止或恢复 Run |
| FR-011、NFR-008 | 已采集但未提交的数据保持 VERIFYING，启动闸门不打开 | 数据恢复用例已有，常驻恢复编排仍需接入 |

报告 `reports/d12b1-validation.txt`，数量与最终结果以实施状态为准。D12a 的远端 Gateway 与 D12b.1 的中央所有权是不同边界，两者均不能独自替代完整部署验收。

## D12b.2 实现追踪（独立常驻执行进程）

| 需求范围 | 实现及验证入口 | 仍待验证 |
|---|---|---|
| FR-004/008/009/014 | `engine_worker.py` 审批/依赖/租约守卫、每轮受控推进；`test_engine_worker.py` 多 Run 争用、撤销审批、续期和过期隔离 | 多实例部署策略、吞吐/压力和真实设备 |
| FR-011/013、NFR-008 | 数据提交失败不重采；已有取消请求确认；暂停需显式 resume；启动时补交采集结果 | 跨机器备份恢复、完整故障矩阵 |
| NFR-002/007/012 | `adapters/engine/server.py` 专用 owner 和网络 Gateway 装配；`test_engine_process.py` 两独立进程闭环、竞争启动、SIGTERM、动作完成后强杀/重启、断开所有权连接退出 | 长时间运行、网络黑洞、多站点证书/身份、运维监控 |

本轮完整后端报告 `reports/d12b2-validation.txt`。未接 Agent/outbox 常驻 worker，不把独立执行引擎称为完整平台常驻部署。

## D12b.3 实现追踪（Agent/outbox 常驻 worker）

| 需求/边界 | 实现 | 验证证据 |
|---|---|---|
| FR-023/026，Agent 上下文/预算/版本与轨迹 | 复用 AgentRuntime，实验白名单轮询，原提交者权限；API/后台/图统一每步锁 | `test_background_workers.py` 多步推进/范围/撤权/公平分页 |
| 未知模型结果不重试、状态提交原子性 | 预算占位；持锁连接提交 checkpoint/轨迹/提案；连接失去后不重连提交 | 锁连接终止、后台/手动争用、独立进程 inflight 恢复 |
| PostgreSQL/outbox 权威，通知至少一次 | 独立 JetStream 发布循环，ACK 后提交，claim 过期重领，稳定事件 ID | 发布进程重启/正常退出、丢 ACK 重连与持久消息去重；既有 inbox 原子性测试 |
| 可恢复进程与最小权限 | 专用 service 主体，逐 Run 复核；Agent 无 Gateway，脱敏日志，SIGTERM/SIGINT | 撤权停止下一次受理、当前模型取消、两个独立 CLI 退出 |

统一报告 `reports/d12b3-validation.txt`；完整部署 E2E、Compose、备份恢复与 24 小时实际长测仍待 D12c/d，不能用上述短测代替。

## D12c.1 实现追踪（初始化与数据库权限分离）

| 需求/部署边界 | 实现 | 验证 |
|---|---|---|
| 第 11/13 章权限与 Secret 管理 | 新库/迁移角色/runtime 分离、私有文件、来源互斥、无管理员凭据继承 | 角色属性/归属、目录与文件权限、不可提权及 CLI 脱敏 |
| 审计/不可变记录与迁移权威 | runtime 拒绝 DDL/TRUNCATE/禁用触发器/版本修改，显式 Alembic 升级 | 9 类 SQL 拒绝、SET ROLE 拒绝、agent_trace 修改拒绝、迁移重复执行 |
| 既有功能在受限权限下兼容 | 业务服务与 worker 使用同一受限 runtime，继续应用层授权 | API 访问与越权拒绝、离线 Agent、三设备/HDF5、outbox 数据库提交 |
| 初始化失败与运维交接 | 拒绝已有资源/覆盖，不完整标记禁止 migrate，连接身份与 manifest 绑定 | 重复初始化/已有目录/错误 manifest/CLI 失败测试 |

报告 `reports/d12c1-validation.txt`。组件级 SQL 权限、网络认证/TLS、Compose 与备份恢复尚未交付，不能据此声明完整生产部署。

## D12c.2 组件权限实现追踪

| 需求/边界 | 实现 | 验证 |
|---|---|---|
| Agent 提案与确定性执行分离 | 独立角色、显式表/列授权、禁用共享 runtime | Agent 写命令/审批、Engine 读模型凭据、outbox 改事件被拒绝 |
| 授权复核与 MCP 发现不授予权限 | 仅锁定函数、受限发现函数、撤销后不能自行恢复 | 并发撤权锁、真实 HTTP MCP、签名漂移及旧签名恢复 |
| 迁移后权限收敛 | 每次 migrate 清除表/列旧 ACL 并重授白名单 | 残留 payload 列授权被移除，published_at 保留 |
| 受限组件业务兼容 | 各组件独立连接文件 | API、离线 Agent、Engine/HDF5、outbox 路径 |

证据：`tests/integration/test_component_roles.py`，统一门禁 `reports/d12c2-validation.txt`；容器部署、网络认证和完整系统 E2E 不在上述测试证明范围。

## D12c.2 容器部署实现追踪

| 需求/部署边界 | 实现 | 验证 |
|---|---|---|
| 独立运行与显式初始化 | 八服务 Compose、维护 profile、私有 prepare、显式 initialize/up | 实际构建启动、初始化空模拟实验、Engine ACTIVE、后台心跳 |
| 网络与数据库权限 | PostgreSQL verify-full/SCRAM，Gateway mTLS，组件 DSN 分离 | 明文/错误密码/无客户端证书拒绝，Agent/Engine/outbox SQL 越权拒绝 |
| 数据与事件权威 | 持久数据库/JetStream/Gateway/artifacts 卷；API/Agent 数据只读 | 实际 outbox ACK、JetStream 留存、数据挂载拒写、重启复验 |
| 前端实际接线 | Next.js 生产镜像、同源 API 代理、仅回环发布 | 首页 200、匿名 API 401、短期 token 认证 200 |
| 可重复验收 | 镜像摘要、代理环境、独立 QA 覆盖和随机测试库 | 官方摘要核对、547 项统一回归、部署材料安全测试 |

实现与操作命令见 `deploy/simulation/README.md`；证据见 `reports/d12c2-compose-acceptance.md` 和 `reports/d12c2-compose-backend-validation.txt`。不将空闲运行时间、卷保留或短测视为 24 小时负载验收、一致性备份恢复或完整平台 E2E。
