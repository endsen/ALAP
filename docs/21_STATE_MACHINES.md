# 21 · D02 完整领域状态与转换规则

状态：D02 设计与纯领域规则已落地；数据库事务、设备/身份验证与恢复执行尚未实现。本章替代第 07 章的混合概览图作为实现依据。代码位于 `src/alap/domain/lifecycle.py`；结构源为 `contracts/lifecycle.schema.json`，测试防止枚举漂移。

## 1. 六种对象与初始条件

| 对象 | 初始状态 | 创建时必须满足（由 D03/D04 应用层执行） |
|---|---|---|
| Run | READY | 已验证不可变 PlanRevision，审批未过期/撤销且版本与范围完全匹配；保存启动者和幂等键 |
| Task | PENDING | 所属 Run/Plan 内的固定节点及 attempt_no；依赖图已验证；不因重试改变计划定义 |
| Command | NOT_DISPATCHED | 唯一 command_id，固定 payload hash、TaskAttempt、资源/epoch/租约/策略/技能版本；未交付网络 |
| Approval | PENDING | 固定计划 hash、作用域、申请者、expires_at；批准者不能由模型产生 |
| Lease | ACTIVE | 在事务中取得所有资源 claim，当前 epoch、单调 token、有效期合法、资源无隔离；不设虚假的“待领取有效租约” |
| Dataset | STAGING | 确定 dataset_id、Run/Task/Command 来源；文件尚未发布 |

`Record` 可重建任意合法持久状态，但不是创建这些业务对象的授权 API。状态类型严格区分：Run.READY 不接受 Task.READY 的枚举实例。Run 不含 DISPATCHED；该状态仅属于 Task/Command。计划草稿/校验/审批不属于 Run 执行状态。

## 2. 转换接口与信任边界

输入为不可变 Record（kind、subject_id、state、version、binding_hash）、事件、expected_version、经过认证的 Actor、证据引用及显式时钟 now。输出 Decision 含新版本、事件、操作者、证据 ID 和必须执行的 effects；函数无网络/数据库/设备调用，输入不被修改。

只有状态表列出的事件可以转换；禁止任意 set_state。相同状态的续租/重复授权失效观察也递增版本。终态重复事件由应用层幂等记录返回原结果，不能再次改变版本。终态结果矛盾时创建异常/对账事件，不静默覆写已经确认的历史结果。

证据必须绑定同一个 kind/id/version/hash，且 valid_from ≤ now < valid_until；每种事实只允许一个证据引用。时间戳必须带时区，截止时刻即失效。expected_version 冲突先拒绝，不能以重试直接覆盖。

**证据是受信任应用适配器生成的判定输入，不是数字签名或事实验证器。** 不能将 HTTP 请求里的布尔值或字符串直接映射成 Evidence/Actor。Gateway 原始回执必须先核对身份、command_id、payload hash、epoch、序号与签名/认证通道，再由应用层结合数据库状态形成当前版本的短期判定；原始回执及其核验记录必须持久保存。权限/读回/哈希的真实验证在 D03–D05/D09 实现。

绑定 hash 的范围：Run/Task 为固定计划版本及其资源范围；Command 为完整固定命令载荷；Approval 为固定计划及授权包络/期限；Lease 为资源、holder、epoch、token、策略及允许续租范围（当前租约截止时间属于受版本控制的可变字段）；Dataset 为固定采集来源。不得通过一次转换换成另一个 hash。

## 3. 权限主体

- engine：已认证的确定性执行服务；聚合任务/命令结果，不能凭自身权限编造仪器完成。
- gateway：经认证的该设备执行器回执入口；它不能审批计划。
- reconciler：受限恢复服务，结合命令 journal、实际读回和现场证据进行对账。
- operator：具有该实验/资源控制权限的用户入口；可请求暂停/取消，不可宣称设备成功。
- approver：具有对应计划/风险审批权的用户入口。
- data_service：负责实际数据持久化与校验的服务。
- timer：受控到期检测服务；不能单凭消息时间戳认定到期，使用数据库/受控时钟验证。

这里的 authority 是用例执行身份类别，不替代 RBAC/ABAC；`control_authorized/approval_authorized` 等事实要求先核验用户、实验、设备、风险范围。

## 4. 证据事实词典

| 事实 | 可信来源与含义 |
|---|---|
| authorization_valid / authorization_invalid | 审批用例：固定计划/包络/策略版本相符且许可当前有效，或明确失效；有效性每次调度重核 |
| control_authorized / approval_authorized / cancellation_authorized | 权限用例：该主体对当前对象具备对应控制/审批/停止请求权限 |
| approval_window_valid / expiry_reached | 审批或租约用例：批准期限有效，或受控 now 已达到 expires_at；事务取得锁后检查 |
| plan_current / plan_changed | 计划仓储：引用版本仍是当前可执行版本，或已被更改/替代 |
| lease_valid / epoch_current | 租约用例：资源集合完整、所有权/token/epoch 匹配、未过期且无隔离；epoch 当前已握手生效 |
| renewal_before_expiry / renewal_window_valid | 续租用例：现租约未过期；新期限严格延长且不超审批/策略上限，所有者与 token 不变 |
| preconditions_fresh | 设备监测/规则引擎：实际读回质量、采样窗口、斜率、单位与鲜度满足计划；不是单次心跳 |
| resources_busy | 租约用例：至少一个资源不可领取；不能在等待事务中长期占有部分资源 |
| run_dispatch_allowed / dispatch_disabled | Run 用例：调度门开启或已关闭；恢复或停止期间禁止新的命令发放 |
| command_prepared / journal_prepared | 中央命令台账：固定命令与待发送项已纳入当前事务，不代表 Gateway 已持久接收 |
| gateway_authenticated | 入口适配器：回执身份与目标设备/epoch/命令/载荷匹配 |
| journal_accepted / journal_running | Gateway 日志：接收或写前 RUNNING 已持久记录；网络 ACK 单独不能证明动作成功 |
| execution_finished / execution_active | Gateway 或对账服务：原命令动作已结束或仍在运行；不得借此重新调用执行方法 |
| success_verified / result_durable | 技能执行/数据服务：读回/稳定/结果判据通过；最终执行结果已落盘可查询 |
| safe_stop_confirmed / device_quiescent | 现场受控停止已确认；设备无未核对的在途动作且符合该技能交接条件，不等于通用断电/零输出 |
| never_executed / no_dispatch | 对账可证明命令未发生物理执行；中央在持锁检查后确认未进入 DISPATCHED；发送失败不是这类证据 |
| outcome_uncertain / failure_confirmed | 结果未知（例如 ACK 丢失）或可确认失败；两者不能互相代替 |
| reconciliation_complete | 恢复用例：原命令/设备/资源已核对，报告有出处与责任主体；无法证明的保持对账中 |
| recovery_stop_authorized | 恢复用例：有权经专门停止通道请求原动作受控终止，不要求授予新实验执行权限 |
| command_running / command_succeeded / command_failed / command_cancelled / command_terminal | 锁定的原 Command 状态：运行、成功、已知失败/执行前拒绝、取消或已确认终态；不接受未经校验的广播文本 |
| dependencies_succeeded / dependency_failed | Task DAG：全部前置成功；或存在已确认失败/跳过/取消的依赖，且无 UNKNOWN 依赖冒充失败 |
| all_tasks_succeeded / children_quiescent | Run 聚合：所有计划任务成功；或所有子任务/命令均无在途/未知动作，且设备符合交接条件 |
| run_cancel_requested / cancellation_complete | Run 控制：取消意图已持久化；未启动任务已取消且在途任务已确认安全结束，无未知子项 |
| datasets_committed | 数据用例：该技能要求的全部数据已真实 COMMITTED；不产出数据的技能必须由锁定 Skill 契约证明不适用 |
| no_inflight_commands | 租约用例：资源所有关联命令都不在 DISPATCHED/ACCEPTED/RUNNING/VERIFYING/CANCEL_REQUESTED/UNKNOWN/NEEDS_RECONCILIATION |
| upload_complete / artifact_durable | 数据服务：上传完整且持久存储确认；仅收到上传请求不算完成 |
| checksum_verified / manifest_valid / metadata_prepared | 数据服务：重新校验内容 hash，完整 Manifest/血缘验证通过，元数据准备好与状态/event 同事务提交 |
| corruption_verified | 数据完整性检查：有可查证的损坏证据；保留原始文件和来源，不以覆盖方式修复 |

时间窗证明的是判定仍可用，不能让旧设备读数因重新包装 Evidence 获得新鲜度；原始 observed_at 必须参加 preconditions_fresh 的计算。

## 5. 暂停、取消、重试与 UNKNOWN

首期只在有限任务边界暂停：Run 请求暂停后关闭新调度，正在执行的 Task 可正常完成；全部子项安静后 Run 才 PAUSED。Task/Command 不提供暂停后重发的快捷路径。需要中断当前动作则走 cancel 和受控停止；以后扩展中间 checkpoint 必须另作 ADR。

取消是请求。动作已经完成的回执可以使取消中的 Command 经 VERIFYING 走成功；Run 只有全部任务都成功才允许 completion_won_race，混合成功/取消则必须确认 cancellation_complete 后 CANCELLED。无确认则 UNKNOWN。任何 Run 终态均要求 children_quiescent，不能让一个任务失败掩盖另一个仍在输出。

UNKNOWN 立刻冻结调度并隔离相关资源。只能先进入 NEEDS_RECONCILIATION，再依据原动作证据恢复 RUNNING/VERIFYING 或落入已确认终态。Run 完成对账后默认 PAUSED；显式 resume 要重新核对权限/租约/前置条件。即使证明原命令从未执行，也关闭为 REJECTED_BEFORE_EXECUTE，使用新 ID 和明确的新执行尝试，不能把原命令改回 NOT_DISPATCHED。

首期失败后的新尝试放入显式新 Run/TaskAttempt；原 Task 与 Command 终态不重开。D03 保留 attempt_no，但不实现自动物理重试。

## 6. 转换 effects 必须落地

- freeze_dispatch：关闭相关 Run 的新发放入口；Task/Command/Approval/Lease 的影响按关联 Run 扩展。
- enable_dispatch：只用于 Run 的显式 resume，且所有门禁已通过；不解除任何资源隔离。
- quarantine_resources：持久阻止相关资源被任何新持有者领取。租约 EXPIRED/REVOKED 不自动清除隔离；清除需另一个有读回与对账证据的恢复事务。
- request_safe_stop：写入高优先级停止请求，事务提交后由近端厂商策略执行；不是立即停止证明。
- invalidate_authorization：使授权不再能用于新命令；已有授予与物理动作的处置见第 22 章撤销时序。
- revoke_data_access：停止该数据及受影响派生结果的正式发布，记录完整性事故；已经完成的物理动作不回退。

纯函数只返回 effects。持久化状态但丢弃 effects 是实现错误，必须在 D03–D05 集成测试中验证原子提交。一次领域转换生成一个事实事件；多对象联动在同一短事务中完成。

## 7. 完整转换表

以下由 `scripts/build_lifecycle_reference.py` 从代码生成；未列出的转换一律拒绝。权限与事实必须同时满足。

<!-- BEGIN GENERATED TRANSITIONS -->

### RunState

状态：`READY`、`WAITING_RESOURCE`、`RUNNING`、`VERIFYING`、`PAUSE_REQUESTED`、`PAUSED`、`CANCEL_REQUESTED`、`SUCCEEDED`、`FAILED`、`CANCELLED`、`UNKNOWN`、`NEEDS_RECONCILIATION`

| 起始状态 | 事件 → 目标 | 主体 | 必需证据事实 | effects |
|---|---|---|---|---|
| READY | `resources_unavailable` → WAITING_RESOURCE | engine | resources_busy | — |
| WAITING_RESOURCE | `resources_acquired` → READY | engine | authorization_valid, lease_valid | — |
| READY | `start` → RUNNING | engine | authorization_valid, lease_valid, preconditions_fresh, run_dispatch_allowed | — |
| RUNNING | `tasks_succeeded` → VERIFYING | engine | all_tasks_succeeded, children_quiescent | — |
| VERIFYING | `complete` → SUCCEEDED | engine | all_tasks_succeeded, children_quiescent, datasets_committed | — |
| READY, WAITING_RESOURCE, PAUSED, RUNNING, VERIFYING, PAUSE_REQUESTED, CANCEL_REQUESTED | `fail` → FAILED | engine | children_quiescent, failure_confirmed | freeze_dispatch |
| READY, WAITING_RESOURCE | `pause` → PAUSED | operator | children_quiescent, control_authorized | freeze_dispatch |
| RUNNING, VERIFYING | `pause` → PAUSE_REQUESTED | operator | control_authorized | freeze_dispatch |
| PAUSE_REQUESTED | `pause_confirmed` → PAUSED | engine | children_quiescent, dispatch_disabled | freeze_dispatch |
| PAUSED | `resume` → READY | operator | authorization_valid, children_quiescent, control_authorized, lease_valid, preconditions_fresh | enable_dispatch |
| READY, WAITING_RESOURCE, PAUSED, RUNNING, VERIFYING, PAUSE_REQUESTED | `cancel` → CANCEL_REQUESTED | operator | control_authorized | freeze_dispatch, request_safe_stop |
| CANCEL_REQUESTED | `cancel_confirmed` → CANCELLED | engine | cancellation_complete, children_quiescent | freeze_dispatch |
| CANCEL_REQUESTED, PAUSE_REQUESTED | `completion_won_race` → SUCCEEDED | engine | all_tasks_succeeded, children_quiescent, datasets_committed | freeze_dispatch |
| READY, WAITING_RESOURCE, PAUSED | `authorization_lost` → PAUSED | engine | authorization_invalid, children_quiescent | freeze_dispatch |
| RUNNING, VERIFYING, PAUSE_REQUESTED | `authorization_lost` → PAUSE_REQUESTED | engine | authorization_invalid | freeze_dispatch |
| READY, WAITING_RESOURCE, RUNNING, VERIFYING, PAUSE_REQUESTED, PAUSED, CANCEL_REQUESTED | `uncertain` → UNKNOWN | engine | outcome_uncertain | freeze_dispatch, quarantine_resources |
| UNKNOWN | `begin_reconciliation` → NEEDS_RECONCILIATION | reconciler | dispatch_disabled | freeze_dispatch, quarantine_resources |
| NEEDS_RECONCILIATION | `reconciled_pause` → PAUSED | reconciler | children_quiescent, reconciliation_complete | freeze_dispatch |
| NEEDS_RECONCILIATION | `reconciled_success` → VERIFYING | reconciler | all_tasks_succeeded, children_quiescent, reconciliation_complete | freeze_dispatch |
| NEEDS_RECONCILIATION | `reconciled_failure` → FAILED | reconciler | children_quiescent, failure_confirmed, reconciliation_complete | freeze_dispatch |
| NEEDS_RECONCILIATION | `reconciled_cancel` → CANCELLED | reconciler | cancellation_complete, children_quiescent, reconciliation_complete | freeze_dispatch |

### TaskState

状态：`PENDING`、`READY`、`WAITING_RESOURCE`、`DISPATCHED`、`RUNNING`、`VERIFYING`、`CANCEL_REQUESTED`、`SUCCEEDED`、`FAILED`、`CANCELLED`、`SKIPPED`、`UNKNOWN`、`NEEDS_RECONCILIATION`

| 起始状态 | 事件 → 目标 | 主体 | 必需证据事实 | effects |
|---|---|---|---|---|
| PENDING | `dependencies_succeeded` → READY | engine | dependencies_succeeded | — |
| READY | `resources_unavailable` → WAITING_RESOURCE | engine | resources_busy | — |
| WAITING_RESOURCE | `resources_acquired` → READY | engine | lease_valid | — |
| READY | `dispatch` → DISPATCHED | engine | authorization_valid, command_prepared, lease_valid, preconditions_fresh, run_dispatch_allowed | — |
| DISPATCHED | `execution_started` → RUNNING | engine | command_running | — |
| DISPATCHED, RUNNING, CANCEL_REQUESTED | `execution_finished` → VERIFYING | engine | command_succeeded | — |
| VERIFYING | `complete` → SUCCEEDED | engine | command_succeeded, datasets_committed, success_verified | — |
| PENDING, READY, WAITING_RESOURCE | `cancel` → CANCELLED | engine | no_dispatch, run_cancel_requested | freeze_dispatch |
| DISPATCHED, RUNNING, VERIFYING | `cancel` → CANCEL_REQUESTED | engine | run_cancel_requested | freeze_dispatch, request_safe_stop |
| CANCEL_REQUESTED | `cancel_confirmed` → CANCELLED | engine | command_cancelled, device_quiescent | freeze_dispatch |
| PENDING, READY, WAITING_RESOURCE | `skip` → SKIPPED | engine | dependency_failed, no_dispatch | freeze_dispatch |
| PENDING, READY, WAITING_RESOURCE | `validation_failed` → FAILED | engine | failure_confirmed, no_dispatch | freeze_dispatch |
| DISPATCHED, RUNNING, VERIFYING, CANCEL_REQUESTED | `fail` → FAILED | engine | command_failed, device_quiescent | freeze_dispatch |
| DISPATCHED, RUNNING, VERIFYING, CANCEL_REQUESTED | `uncertain` → UNKNOWN | engine | outcome_uncertain | freeze_dispatch, quarantine_resources |
| UNKNOWN | `begin_reconciliation` → NEEDS_RECONCILIATION | reconciler | dispatch_disabled | freeze_dispatch, quarantine_resources |
| NEEDS_RECONCILIATION | `reconciled_success` → VERIFYING | reconciler | command_succeeded, reconciliation_complete | freeze_dispatch |
| NEEDS_RECONCILIATION | `reconciled_running` → RUNNING | reconciler | authorization_valid, command_running, lease_valid, preconditions_fresh, reconciliation_complete | freeze_dispatch |
| NEEDS_RECONCILIATION | `reconciled_failure` → FAILED | reconciler | command_failed, device_quiescent, reconciliation_complete | freeze_dispatch |
| NEEDS_RECONCILIATION | `reconciled_cancel` → CANCELLED | reconciler | command_cancelled, device_quiescent, reconciliation_complete | freeze_dispatch |
| VERIFYING | `verification_failed` → FAILED | engine | command_terminal, device_quiescent, failure_confirmed | freeze_dispatch |

### CommandState

状态：`NOT_DISPATCHED`、`DISPATCHED`、`ACCEPTED`、`RUNNING`、`VERIFYING`、`CANCEL_REQUESTED`、`SUCCEEDED`、`FAILED_CONFIRMED`、`REJECTED_BEFORE_EXECUTE`、`CANCELLED`、`UNKNOWN`、`NEEDS_RECONCILIATION`

| 起始状态 | 事件 → 目标 | 主体 | 必需证据事实 | effects |
|---|---|---|---|---|
| NOT_DISPATCHED | `dispatch` → DISPATCHED | engine | authorization_valid, journal_prepared, lease_valid, preconditions_fresh, run_dispatch_allowed | — |
| NOT_DISPATCHED | `cancel` → CANCELLED | engine | cancellation_authorized, no_dispatch | freeze_dispatch |
| DISPATCHED | `accepted` → ACCEPTED | gateway | gateway_authenticated, journal_accepted | — |
| DISPATCHED, ACCEPTED | `execution_started` → RUNNING | gateway | gateway_authenticated, journal_running | — |
| DISPATCHED, ACCEPTED, RUNNING, CANCEL_REQUESTED | `execution_finished` → VERIFYING | gateway | execution_finished, gateway_authenticated | — |
| VERIFYING | `complete` → SUCCEEDED | gateway | datasets_committed, gateway_authenticated, result_durable, success_verified | — |
| NOT_DISPATCHED, DISPATCHED, ACCEPTED | `reject` → REJECTED_BEFORE_EXECUTE | gateway | gateway_authenticated, never_executed | freeze_dispatch |
| DISPATCHED, ACCEPTED, RUNNING, VERIFYING, CANCEL_REQUESTED | `fail` → FAILED_CONFIRMED | gateway | device_quiescent, failure_confirmed, gateway_authenticated, result_durable | freeze_dispatch |
| DISPATCHED, ACCEPTED, RUNNING, VERIFYING | `cancel` → CANCEL_REQUESTED | engine | cancellation_authorized | freeze_dispatch, request_safe_stop |
| CANCEL_REQUESTED | `cancel_confirmed` → CANCELLED | gateway | device_quiescent, gateway_authenticated, result_durable, safe_stop_confirmed | freeze_dispatch |
| DISPATCHED, ACCEPTED, RUNNING, VERIFYING, CANCEL_REQUESTED | `uncertain` → UNKNOWN | engine, gateway | outcome_uncertain | freeze_dispatch, quarantine_resources |
| UNKNOWN | `begin_reconciliation` → NEEDS_RECONCILIATION | reconciler | dispatch_disabled | freeze_dispatch, quarantine_resources |
| NEEDS_RECONCILIATION | `reconciled_success` → VERIFYING | reconciler | execution_finished, reconciliation_complete | freeze_dispatch |
| NEEDS_RECONCILIATION | `reconciled_running` → RUNNING | reconciler | authorization_valid, execution_active, lease_valid, preconditions_fresh, reconciliation_complete | freeze_dispatch |
| NEEDS_RECONCILIATION | `reconciled_failure` → FAILED_CONFIRMED | reconciler | device_quiescent, failure_confirmed, reconciliation_complete, result_durable | freeze_dispatch |
| NEEDS_RECONCILIATION | `reconciled_cancel` → CANCELLED | reconciler | device_quiescent, reconciliation_complete, result_durable, safe_stop_confirmed | freeze_dispatch |
| NEEDS_RECONCILIATION | `reconciled_not_executed` → REJECTED_BEFORE_EXECUTE | reconciler | never_executed, reconciliation_complete | freeze_dispatch |
| NEEDS_RECONCILIATION | `request_recovery_stop` → CANCEL_REQUESTED | reconciler | execution_active, reconciliation_complete, recovery_stop_authorized | freeze_dispatch, request_safe_stop |

### ApprovalState

状态：`PENDING`、`APPROVED`、`REJECTED`、`EXPIRED`、`REVOKED`、`SUPERSEDED`

| 起始状态 | 事件 → 目标 | 主体 | 必需证据事实 | effects |
|---|---|---|---|---|
| PENDING | `approve` → APPROVED | approver | approval_authorized, approval_window_valid, plan_current | — |
| PENDING | `reject` → REJECTED | approver | approval_authorized | — |
| PENDING, APPROVED | `expire` → EXPIRED | timer | expiry_reached | freeze_dispatch, invalidate_authorization |
| APPROVED | `revoke` → REVOKED | approver | approval_authorized | freeze_dispatch, invalidate_authorization |
| PENDING, APPROVED | `supersede` → SUPERSEDED | engine | plan_changed | freeze_dispatch, invalidate_authorization |

### LeaseState

状态：`ACTIVE`、`RELEASE_PENDING`、`RELEASED`、`EXPIRED`、`REVOKED`

| 起始状态 | 事件 → 目标 | 主体 | 必需证据事实 | effects |
|---|---|---|---|---|
| ACTIVE | `request_release` → RELEASE_PENDING | engine | dispatch_disabled | freeze_dispatch |
| RELEASE_PENDING | `release` → RELEASED | engine | device_quiescent, no_inflight_commands | — |
| ACTIVE, RELEASE_PENDING | `expire` → EXPIRED | timer | expiry_reached | freeze_dispatch, quarantine_resources |
| ACTIVE, RELEASE_PENDING | `revoke` → REVOKED | operator | control_authorized | freeze_dispatch, quarantine_resources |
| ACTIVE | `renew` → ACTIVE | engine | authorization_valid, epoch_current, renewal_before_expiry, renewal_window_valid | — |

### DatasetState

状态：`STAGING`、`VALIDATING`、`COMMITTED`、`CORRUPT`

| 起始状态 | 事件 → 目标 | 主体 | 必需证据事实 | effects |
|---|---|---|---|---|
| STAGING | `upload_complete` → VALIDATING | data_service | upload_complete | — |
| VALIDATING | `commit` → COMMITTED | data_service | artifact_durable, checksum_verified, manifest_valid, metadata_prepared | — |
| STAGING, VALIDATING, COMMITTED | `corruption_found` → CORRUPT | data_service | corruption_verified | revoke_data_access |

<!-- END GENERATED TRANSITIONS -->

## 8. D02 验收范围

`tests/test_lifecycle.py` 验证成功路径、取消/完成竞态、UNKNOWN 不重放、证据串用/过期、版本冲突、资源隔离、审批撤销、数据损坏、终态不可重开和状态可达性。契约测试核对状态枚举与 API 一致。数据库并发、身份认证、真实时序和设备执行尚待后续期验证，本期不宣称通过这些集成场景。
