# 22 · D02 PostgreSQL 数据与事务设计

状态：D02 冻结设计，D03 已据此实现三个迁移批次与应用用例；验证结果见 IMPLEMENTATION_STATUS.md。D04/D05 继续添加执行与数据表，不以 SQLite/内存模拟代替 PostgreSQL。

## 1. 约束与事务选择

以 PostgreSQL 为唯一业务状态权威。默认短写事务采用 READ COMMITTED + 明确行锁和唯一约束；多查询一致性快照使用只读 REPEATABLE READ。需要更强隔离的复杂操作按实测采用 SERIALIZABLE，并在无外部副作用的边界重试整个事务；不能重试已经发往设备的动作。[PostgreSQL 事务隔离](https://www.postgresql.org/docs/18/transaction-iso.html)

锁顺序统一：控制代际行（正常操作 FOR SHARE，恢复操作 FOR UPDATE）→ experiment ID 排序 → approval ID 排序 → resource_control ID 排序 → lease ID 排序 → run ID 排序 → task ID 排序 → command ID 排序 → dataset ID 排序。只取需要的锁，但不得反向补锁。任何操作先确定父对象再锁；资源所有者变化时回滚重读，不在持锁后临时修改另一实验。[PostgreSQL 显式锁](https://www.postgresql.org/docs/18/explicit-locking.html)

所有实验状态写都锁 experiment 行，序列号与状态一起提交；首期接受每实验串行写的开销。网络调用、LLM、采样、文件上传、NATS 发布均在事务之外。事务冲突/死锁允许有界重试数据库工作；命令发送严格另走持久发放协议。

主键、唯一约束、NOT NULL 与复合外键保护身份和所属关系；CHECK 只验证本行可确定不变量，不能用跨表查询或 now() 的动态结果保证有效租约。[PostgreSQL 约束](https://www.postgresql.org/docs/18/ddl-constraints.html)

## 2. 表与约束蓝图

共同约定：ID 用不透明文本/UUID；时间 TIMESTAMPTZ，UTC 输出；hash 为 64 位小写十六进制文本；state_version BIGINT ≥ 0；状态值来自生命周期契约。JSONB 保存结构快照，不用它替代关键外键。表和字段最终 SQL 在 D03–D05 的迁移中落地。

| 表 | 主要字段/键 | 必须成立的不变量 | 实施期 |
|---|---|---|---|
| principals | id PK、issuer、external_subject、kind、disabled_at | UNIQUE(issuer,external_subject)，无明文 API Key；用户与服务均有身份 | D03 |
| samples | id PK、owner_id FK、metadata、version | 实验只能引用有权限的样品，历史引用不级联删除 | D03 |
| experiments | id PK、owner_id FK、sample_id FK、revision、event_cursor、state | revision/event_cursor ≥ 0，所有关联写共用此锁 | D03 |
| experiment_memberships | experiment_id/actor_id 复合 PK、role、scope、version | 成员撤销不删除历史审计；资源级授权由应用验证 | D03 |
| plan_revisions | id PK、experiment_id FK、revision、snapshot_version、canonical_bytes、plan_json、plan_hash、created_by | UNIQUE(experiment_id,revision)，UNIQUE(experiment_id,id)；内容不可 UPDATE，canonical_bytes 为 hash 原文 | D03 |
| approvals | id PK、experiment_id、plan_revision_id、plan_hash、scope_json、binding_hash、state、state_version、requested_by、decided_by、expires_at | 复合 FK 到同实验计划；授权内容/期限不变，状态按表转换，批准人 FK；审批日志追加写 | D03 |
| idempotency_records | actor_id、operation、scope_id、key 复合唯一，request_hash、response_json、status、expires_at | 同 key 不同请求 409；副作用结果与业务同事务，重试不创建第二个 Run | D03 |
| runs | id PK、experiment_id、plan_revision_id、approval_id、state、state_version、dispatch_blocked、binding_hash、created_by | 复合 FK 保证计划与审批属于同实验；启动时校验同计划 hash；固定执行定义 | D03 |
| tasks | id PK、experiment_id、run_id、plan_task_id、attempt_no、state、state_version、binding_hash | UNIQUE(run_id,plan_task_id,attempt_no)；父 Run 的复合外键；失败不复写旧 attempt | D04 |
| task_dependencies | run_id、task_id、depends_on_id 复合 PK | 两端都属于同 Run；禁止 self-edge；无环由领域验证+不可变计划保证 | D04 |
| gateways / instruments | gateway id、身份引用；instrument id、gateway_id、physical_resource_key、版本、读回元数据 | physical_resource_key 唯一，不能以别名绕过单写者；迁移归属需受控处理 | D04 |
| control_generation | singleton key、epoch UUID、mode、version | 单一当前代际，mode=ACTIVE/RECOVERING；恢复锁防并发发放 | D04 |
| resource_controls | instrument_id PK/FK、epoch、last_fencing_token、quarantined、reason、reconciliation_ref | token 单调，隔离与租约失效分离；重置须换 epoch 且所有 Gateway 对账 | D04 |
| leases | id PK、resource_id、holder_run_id、epoch、token、expires_at、scope_hash、state、state_version | UNIQUE(resource_id,epoch,token)，同 owner/token 范围固定；续租只延长期限与版本 | D04 |
| resource_claims | resource_id PK、lease_id UNIQUE、holder_run_id | 每设备最多一个当前 claim；和 lease/resource_control 同事务创建/移除 | D04 |
| command_ledger | command_id PK、experiment_id、run_id、task_id、attempt_no、payload_bytes、payload_hash、instrument_id、lease_id、epoch、token、state、state_version | 复合 FK 固定所属；载荷永久不变；同 command_id 不同 hash 拒绝 | D04 |
| command_deliveries | command_id UNIQUE FK、status、claimed_by、claimed_until、delivery_attempt_id | 待发送与台账同事务建立；DISPATCHED 后不能自动回到待发送队列 | D04 |
| stop_requests | request_id PK、command_id、actor_id、reason、state、dedup_key | 独立高优先级受控停止通道；重复请求不重发普通实验动作 | D04 |
| evidence_records | evidence_id PK、kind/id/version/hash、fact、原始来源引用、valid_from/until、verified_by、verified_at | 证据追加写；包含设备 observed_at 等原始时序；校验主体不能由请求自填 | D03 基础/D04 执行 |
| transition_audit | id PK、对象 kind/id、from/to、old/new_version、event、actor、evidence_ids、effects、trace_id | UNIQUE(kind,id,new_version)，不可任意改写或覆盖 | D03 |
| outbox_events | event_id PK、experiment_id、experiment_seq、aggregate_type/id/seq、event_type、payload、published_at | UNIQUE(experiment_id,experiment_seq)，UNIQUE(aggregate_type,aggregate_id,aggregate_seq) | D03 |
| consumer_inbox | consumer_id/event_id 复合 PK、payload_hash、applied_at | 消费效果与去重记录同事务；同 ID 不同载荷标记冲突 | D05 |
| gateway_receipts | gateway_id/epoch/receipt_seq 唯一、command_id、payload_hash、raw_ref、received_at | 重复幂等；旧/乱序回执不回退状态；字段与身份映射核验 | D04 |
| datasets | id PK、experiment_id/run_id/task_id/command_id、state、state_version、storage_key、manifest_json、checksum、binding_hash、acquired_from/to | 血缘复合 FK；STAGING 可无完整 Manifest；COMMITTED 必须完整且验证，损坏不覆盖原文件 | D05 |
| provenance_edges | source/target 类型与 ID、relation、algorithm_version、parameters_hash | 关系可追踪，访问由关联实验权限过滤；文件发布与正式血缘记录同事务 | D05 |

基础角色与权限细化在 D09 接身份系统；D03 使用显式测试身份并保留同一授权端口，不提供匿名管理员默认权限。Agent/Model/Skill/MCP 表在 D06–D09 增量设计，不为未实现模块预建自由 JSON 垃圾桶。

## 3. 创建与不可变性

plan_revisions 的 canonical_bytes 保留完整原始规范编码，不能从 JSONB 重序列化后宣称得到同一 hash；JSON 数字表示变化可能影响摘要。schema_version、模型来源、策略/能力版本进入固定快照。D03 用仓储限制与数据库更新防护约束不可变列；每次变更新建 revision。

Approval 的资源/动作/参数/期限一旦创建不修改；审批动作只改变状态、决定者和 state_version。Lease 的持有者、epoch、token 不变；续租允许在批准上限内更新 expires_at。Dataset 初期 staging metadata 与正式 Manifest 分开；完整性损坏改变发布状态并追加事故记录，保留原始 manifest/file 证据。

## 4. 核心事务时序

### TX-01 创建实验与幂等响应

验证身份/样品范围 → 插入按 actor+operation+scope 隔离的幂等记录（并发由唯一约束协调）→ 写 Experiment → 分配首个 experiment_seq → 写 outbox/审计及响应 → 提交。冲突请求读取已提交响应；请求 hash 不同返回 409。唯一约束冲突回滚后在新事务读取结果，不在已失败事务里继续查询。

### TX-02 审批与启动

锁 Experiment 与 Approval → 核验 If-Match 对应实验 revision、精确计划/hash、scope、期限、审批主体 → 领域状态转换 → 写 state_version、证据/审计与 outbox → revision/cursor 递增 → 提交。

启动另一个事务锁定相同父对象，重新验证当前 Approval/Plan；创建 Run READY 与任务身份，保存启动幂等响应。审批成功不自动启动。过期判断每次读取权限时主动执行，不能等待定时任务先把 APPROVED 改成 EXPIRED 才停止授权。

### TX-03 领取资源与准备命令

读取完整资源集合 → 按统一顺序取得锁 → 检查 epoch=ACTIVE、全部资源无隔离/有效他人 claim、审批有效、真实状态新鲜 → 原子创建全部 leases/claims、递增资源 token → 写 Command NOT_DISPATCHED、固定载荷及 delivery 意图 → 提交。不具备全套资源则回滚，本事务不保留部分 claim；等待/退避用新的短事务记录。

不在某实验的领取事务中抢先清理另一个实验的过期租约。后者的过期/隔离由其所属实验事务处理。新领取依然检查 expires_at 和 quarantine，即便定时清理尚未执行也不能凭“时间到了”直接接管。

### TX-04 发放与 Gateway 接收

中央发送 worker 按第 1 节统一顺序锁定代际、Experiment、Approval、资源、Lease、Run、Task、Command，重新检查发放门、有效租约与期限 → Command 标 DISPATCHED，delivery 标已尝试、Task 进入 DISPATCHED，写 outbox → 提交 → 发出网络请求。提交后进程崩溃即便可能尚未发包也进入 UNKNOWN 对账，不能盲目重新出队；这用可用性换取避免重复动作。

Gateway 独立持久 journal：认证/限幅/epoch/fencing/幂等 → ACCEPTED 落盘 → RUNNING 写前落盘 → 执行 → VERIFYING/结果落盘。相同 ID/hash 返回已有状态；不同 hash 拒绝。网关重启见非终态记录先对账，不能把重复网络请求转成再次执行。中央 receipt 导入核验原始来源，再基于当前 state_version 构建证据；晚到 ACCEPTED 不可回退已 RUNNING/UNKNOWN 状态。

### TX-05 状态转换、停止与授权撤销

在同一事务更新对象 version、所有 effects、父级聚合、evidence/audit/outbox；例如 UNKNOWN 必须同时关闭 Run 调度并隔离资源。停止请求通过独立队列提交后发送，不在 DB 锁内等待设备响应。已发送请求只显示 CANCEL_REQUESTED，停止确认前不得释放资源。

撤销或到期阻止新的发放许可，并根据设备策略处理已经提交的有限命令。DB 与硬件之间不存在原子撤销：发放事务先于撤销提交的命令可能已被接收或在途，需要 token/许可期限及明确停止协议，不承诺点击撤销瞬间消除物理副作用。Gateway 在每个新命令边界重核有效性；原有有限步骤按批准的失联/停止策略完成或终止。

### TX-06 事件发布与消费

业务事务锁 Experiment，更新状态、revision、event_cursor，同事务 outbox 存 experiment_seq。使用事务性计数器而非 PostgreSQL sequence 保证“已提交实验流”的游标语义。不同实验之间不要求顺序。

发布器用短事务领取 outbox 工作（SKIP LOCKED 只用于队列，不用于分配同一仪器的独占 claim），释放锁后发 NATS；ack 后标记 published。ack 后崩溃会重投，但不能再次执行 Command。消费者依据 event_id 去重，inbox 与本地消费效果同事务提交；跨库消费者各自维护 inbox。NATS 到达顺序不作物理执行依据。

### TX-07 快照与数据提交

UI 快照在同一只读 REPEATABLE READ 事务中取实验相关状态及 event_cursor；事务结束后从该 cursor 读取持久事件。超过保留期明确要求完整重同步；新订阅需检查当前权限。

文件持久写与校验在 DB 事务外完成；选用不可覆盖的 storage_key → 将真实存储确认/校验和作为证据 → 锁定 Dataset/Experiment，在短事务写完整 Manifest/血缘、状态 COMMITTED 和 outbox。DB 失败保留 staging 对象并重核，不重复采集；孤儿文件仅在保留窗口后依据引用和审计清理。状态变 COMMITTED 前任何正式分析/下载入口都拒绝发布。

### TX-08 对账、隔离清除与代际恢复

单资源隔离清除要求：原命令全有确认结果、无在途停止请求、设备符合交接条件、旧 holder 已失效、当前 epoch/身份一致，证据和责任主体齐备；同事务移除旧 claim、记录对账及清除 quarantine。原 EXPIRED/REVOKED Lease 终态保持不变。

数据库恢复先将控制代际置 RECOVERING，暂停一切新发放；联系每个注册 Gateway 收集持久最大 token、命令与实际状态。新 epoch 只通过独立受认证握手绑定，不由普通命令切换。不在线/未完成对账的 Gateway 与设备保持隔离。确认后启用新 epoch、新租约，恢复出站；旧 epoch 命令永久拒绝。此协议在 D04 故障测试实现。

## 5. 迁移顺序与 D03 计划

| 批次 | 建议迁移 | 验证与回退要求 |
|---|---|---|
| D03-001 | principals、samples、experiments、memberships | 空库升级；FK/权限测试身份；隔离测试数据库，不连接生产 |
| D03-002 | plan_revisions、approvals、runs、idempotency | 不可变列、跨实验外键、审批期限、重复请求和版本冲突 |
| D03-003 | evidence_records、transition_audit、outbox | 状态/证据/effects/游标同事务回滚；重复事件不重复写 |
| D04-001 | instruments/gateways、代际、资源/租约、tasks/commands/journal 关联 | 两连接并发领取、epoch 恢复、发放后宕机不重放 |
| D05-001 | datasets、provenance、consumer_inbox | 半上传、hash 不符、commit 中断、重投/乱序 |

D03 将选定并锁版本的迁移工具与驱动接入真实 PostgreSQL，CI 使用隔离数据库。空库 up/down/up 可作为开发迁移检查；含真实实验审计的生产库不得用破坏性 down 脚本回滚，采用前向修复、备份与经审阅的数据迁移。不得添加“清空数据库重建”作为默认启动行为。

## 6. 集成故障用例与分期验证

D03 已验证 DB-01/02/04/12 的数据库范围；D04 已验证 DB-03/05/06/07/11 的离线模拟范围。DB-08/09/10 的完整协议留到 D05，HTTP/SSE 与真机验证仍属后续期。具体证据见第 16 章和实施状态。

DB-01：两个连接使用同一幂等键/不同载荷；相同请求只产生一个对象，冲突返回 409。
DB-02：审批修改/过期与启动并发；持锁后核验，失效许可不能产生新的发放授权。
DB-03：两个 Run 竞争重叠资源，至多一个 holder，不部分占有、不死锁后重复动作。
DB-04：状态已写而 outbox 前崩溃；整个事务回滚，无半提交状态。
DB-05：DISPATCHED 提交后发包前宕机；重启进入 UNKNOWN，不自动发送。
DB-06：设备执行后 ACK 丢失，重连回执乱序；不重复物理动作、不回退终态。
DB-07：租约过期但设备仍工作；资源保持隔离，不能交给新 Run。
DB-08：pause/cancel 与完成并发；显示真实结果，所有子项可核对后才 Run 终态。
DB-09：数据文件已存而 DB 提交失败；无正式 Dataset，恢复不重新测量。
DB-10：outbox 已发布未标记，消费者重投；inbox 与效果原子且不重复计费/动作。
DB-11：DB 备份恢复 token 回退；旧 epoch 拒绝，未握手设备不启用。
DB-12：UI 快照读取间发生事务提交；状态与游标来自同一快照，续订不静默丢事件。


## 7. D03 实施细化

实现位于 `migrations/versions/d03_001～003`、`src/alap/application` 与 `src/alap/adapters/postgres`，操作手册见 `D03_DATABASE_DEVELOPMENT.md`。

- D03 runs 增加固定 `plan_hash` 与 `task_identities`，复合外键同时验证计划/审批/hash；任务身份保存 attempt_no=1，实际 tasks 表留到 D04。
- 创建实验的 revision/cursor 从 0 开始，创建事件同事务递增为 1；所有后续事实事件递增实验 revision/cursor。每对象 audit/outbox 版本从 0 开始，转换递增 1。
- principal 共享锁先于业务锁，membership 共享锁在 experiment 后；身份管理事务必须使用相同顺序。设备 control_generation 锁将在 D04 加入，不能据此省略未来代际门禁。
- 计划 canonical_bytes 是唯一 hash 原文；JSONB 为可查询副本，数据库同时检查字节摘要和 JSON 等价，禁止历史更新/删除。
- outbox 除蓝图字段外存 schema_version、producer、trace_id，创建时校验共享事件契约；事实包络不可变，published_at 单独更新。
- 幂等插入采用 ON CONFLICT DO NOTHING；相同键提交后读取已存响应，避免唯一冲突后的失败事务读。30 天期限仅作保留标记，本期不自动复用旧键。
- expire 在每次许可使用时直接校验数据库当前时间，不依赖 timer；显式 timer 负责过期状态与发放门/effects 同事务落库。
- D03 Run 发放门始终关闭；无设备写入证据，不能开启调度。审批失效冻结未执行 Run；真实执行态处理在 D04 补齐。


## 8. D04 实施细化

实现见 `d04_001_execution.py`、`application/execution.py`、`adapters/gateway/`，操作与限制见 D04_EXECUTION_DEVELOPMENT.md。D03 写入事务现已加入代际共享锁；恢复使用独占代际锁。网关 journal 独立持久化并防止多进程同时持有；中央与网关没有跨库事务，发送前崩溃保守进入 UNKNOWN。新 epoch 采用全部注册网关确认的全局屏障，未完成对账不恢复发放。

D04 仅使用离线认证和模拟设备；stop_requests 预留表不代表停止协议已完成，IV 结果不进入 COMMITTED。D05 必须补齐停止请求在资源释放和恢复中的核验，以及数据提交、消息投递和消费协议。

## 9. D05 实施细化

D05-001 增加 datasets、采集 provenance_edges、不可变 device_snapshots；D05-002 增加独立 event_delivery_claims、consumer_inbox、event_projections；D05-003 增加停止确认结果及身份不变约束。完整实现/故障验收见 [D05 开发说明](D05_DATA_RECOVERY_DEVELOPMENT.md)。

文件操作、NATS publish、Gateway 停止与数据发布确认均在数据库事务外。状态/effects/审计/outbox 同事务；消息消费 inbox/投影同事务；停止确认阻止旧包迟到和提前复用资源。DB-08/09/10 已纳入真实数据库与离线模拟集成测试，HTTP/SSE 和真机仍待对应期。当前保留全部事件及孤儿文件，不做破坏性自动清理。

## D07 Agent 持久化补充

迁移 d07_001 增加 agent_registry/agent_runs/agent_trace/agent_tool_invocations/agent_proposals。注册内容、发布时解析的模型/工具/技能绑定和运行 bundle 不可变，状态/检查点版本可推进。Agent 的逻辑 checkpoint 独立于实验 runs/command_ledger，不修改物理执行状态。

同一 Agent Run 使用 session advisory lock 排他推进；模型调用前短事务预留预算，网络调用期间不持有业务事务。工具结果、PROPOSED 提案、trace 与新 checkpoint 同事务提交，调用 ID 唯一约束防重复；成员/资源/快照与禁用状态在提交前重新校验。只有 run 所属 actor 可恢复，成员撤权即拒绝。本期不实现正式计划/API 推进；不能把 agent_proposals 当可执行命令。

## D08 资源与协作持久化补充

d08_001 增加 knowledge_versions/grants、mcp_connections/tools/grants/calls、dataset_analyses、collaboration_claims、proposal_business_keys。知识/连接/目录内容不可覆盖，ACL 与启停单独变化；分析结果不可变并绑定 dataset/checksum/算法。MCP INFLIGHT 在远端调用前提交，未知不得盲重试；调用成功缓存与 Agent 工具 ledger 分离，checkpoint 恢复先复核再复用。

Agent checkpoint 的 external_refs 在加载和提交内锁定复核；提案与业务指纹、工具 ledger/trace/checkpoint 同事务，冲突整体回滚。数据事件 claim 有固定 Run ID、次数/冷却约束，创建和绑定间中断可恢复。历史 D07 提案建立结构指纹映射，不删除或改写已有提案。

## D09 · API 与身份持久化

迁移 d09_001 为实验增加 title/objective/created_at，并增加 platform_roles、api_tokens、api_credentials、platform_configs、api_requests、api_audit。已有实验的 created_at 是迁移时间，不能当作历史采集时间。token 仅存摘要，凭据仅存绑定引用的认证密文；版本配置在应用入口拒绝覆盖，管理审计不可更新/删除。

API 请求以 actor/operation/path/key 区分，HMAC 绑定请求及 If-Match，INFLIGHT 在调用前提交。跨服务操作不声明同事务，崩溃保留未知并要求检查业务结果；原有实验状态/outbox 原子事务保持。权限变化不产生虚构设备事件；SSE 按当前权限复核并可终止，客户端再获取权威快照。

## D12 · Agent 持久化取消意图

迁移 d12_002 在 agent_runs 增加 cancel_requested_at。该时间记录运行所有者首次提出取消的事实，不推进 checkpoint revision，也不改变 READY/RUNNING；API 返回 cancel_requested=true，不能据此显示 CANCELLED。申请人仍须通过当前成员、资源与来源访问复核。触发器仅允许非终态首次写入时间且其他全部字段不变；已写入时间不可清除或替换，原绑定不可变规则继续有效。重复请求保留首次时间；终态上的取消是无操作。

请求使用短事务锁定 Agent 行，与 checkpoint 提交串行化；模型网络调用仍只持有 session 所有权锁，不持有行锁。持有运行所有权的调用者可立即确认，否则返回已持久化意图，由 worker 后续确认。worker 在推进前、后续工具调用前检查意图，最终提交事务再次锁行复查。若取消请求先取得提交顺序，则从上一个已提交 checkpoint 生成 CANCELLED/done，清空未提交 pending/result，保留历史与预算预留，丢弃本次工具 ledger/提案，并与 cancelled 轨迹同事务提交。轨迹保留 prior_stage 和 model_outcome_unknown。若原终态先提交，晚到的取消不覆盖该终态。模型预留提交被取消截断后不得继续发出模型请求；所有权连接失效仍不得重连提交。

本实现是安全边界取消，不保证立即中断已经发出的模型或只读/MCP 请求；远端副作用及已消费 token 无法撤回，已完成历史提案不会删除。运行时仍受现有超时/预算约束。来源或提交人撤权不由取消请求绕过，失败状态也不能伪装为取消确认。相同 HTTP 幂等键可返回原先的待确认响应，最新状态以随后 GET 为准。当前本地源码/集成验证与实际 Compose 升级验收分开记录，见 IMPLEMENTATION_STATUS.md。
