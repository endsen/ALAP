# 19 · v3.1 契约与领域规则

本章规定首轮基础实现的语义。旧 v3.0 文件保留为历史输入；当前机器可读契约在根目录 `contracts/`。v3.1 首次落地采用报文版本 2.0（与企划版本、REST `/api/v1` 独立），不存在已部署 v1 数据迁移需求。

## 计划模型

`TaskProposal` 是局部建议，仅作为 Planner 输入；当前不接受其直接执行。`PlanProposal` 是完整候选计划；通过校验后才能形成不可变 `PlanRevision`。统一字段为 `based_on_snapshot_version`，REST 不再使用含义模糊的 `based_on_revision`。

每个 Task 具备 `resource_id`（主执行设备）、`required_resources`（含读回依赖设备）、`skill_ref`（固定版本）、`parameters`、`depends_on`、`preconditions`、`success_condition`、`timeout_s`。计划资源集合必须恰好覆盖所有任务资源，不可有未声明的资源。条件引用的设备必须在该任务的资源集中。

稳定条件必须包含设备、观测量、目标、SI 单位、容差、最大斜率、持续窗口与最大读数年龄。Schema 检查形状；领域校验检查 DAG、资源/引用、有限数值与条件约束；执行前再检查真实时间序列及设备策略。单个读数不能证明稳定窗口成立。

Skill 参数依据发布的输入 Schema 二次验证；未知技能拒绝，不允许自由参数直接进入执行器。基础层测试只使用显式标记的模拟技能配置。

计划版本绑定 experiment、revision、snapshot、资源/策略/能力版本及全部任务。服务器用 `alap-json-v1` 编码（UTF-8、排序对象键、紧凑 JSON、禁止非有限数字、数组顺序保留）计算 SHA-256；这是后端规范，不宣称 RFC 8785。前端只使用服务器返回 hash，不自行跨语言计算。整数与浮点表示不同可导致不同 hash；此时重新审核，不放宽匹配。

审批必须带 `If-Match`，匹配实验快照 revision；plan_revision_id/hash 另行精确绑定。修改参数、条件、技能、资源或版本都会导致原授权不匹配。基础层生成 hash 不等于授予审批，数据库不变性与原子校验在后续阶段实现。

## 数据与事件

Dataset Manifest 的独立 Schema 和 REST 公共字段保持一致，公开响应额外限定 `status=COMMITTED`。每个参与设备必须有对应的策略/能力版本映射，采集结束不早于开始。形状校验不能证明文件存在，发布仍要求持久文件、实际校验和及元数据事务。

所有实验事件保留 `aggregate_id/aggregate_seq` 表示对象顺序，新增 `experiment_seq` 表示实验内持久事件流游标；SSE id 使用后者。数据库事务中锁定实验计数器、递增序号、写状态及 outbox；事务回滚一并回滚。不同实验无全局有序保证。

实验快照包含 `event_cursor`，同一一致性读取得状态与水位；从该游标补事件。超过保留期明确 `RESYNC_REQUIRED`。无该实验读取权限不能订阅；首期实验流不做逐事件部分过滤。用户权限撤销后关闭订阅，不能继续发送缓存事件。LLM Token 分片使用临时流，不能冒充持久实验事实。

统一数据发布事件为 `dataset.committed.v1`；采集完成但未发布不触发分析。任务最终完成为 `task.succeeded.v1`；设备状态为 `device.status_changed.v1`。

## 命令与恢复（执行层待实现）

命令绑定 `control_epoch`、`fencing_token`、`lease_id`、计划 hash、策略/能力/技能版本。epoch 是恢复代际标识，Gateway 只接受已通过受认证恢复流程绑定的精确 epoch，不能根据任意命令自动切换。相同 epoch 内 token 单调递增；数据库恢复后暂停写入口，对账所有 Gateway，再显式建立新 epoch 和租约。

近端命令处理：校验授权 → 同一 command_id 比对 payload hash → 持久写入 ACCEPTED → 写前持久 RUNNING → 单设备串行执行 → 读回与结果落盘 → 返回结果。重启见 ACCEPTED/RUNNING 的非终态命令一律先对账，不重发。对于已有终态，查询只返回原结果；同 ID 不同 payload 拒绝。

UNKNOWN 阻塞相关后继和资源复用，直到取得设备/journal 证据并完成对账。Run、Task、Command 各自完整状态表与恢复证据类型是 P2 的进入门槛；旧第 07 章图仅作概览，不能直接生成调度实现。

## 契约维护

JSON Schema 是共享结构的唯一源；`contracts/openapi.base.yaml` 存手写 REST 路由，脚本生成 `contracts/openapi.yaml`，将共享结构装入 components。CI 检查生成结果无漂移并执行完整 OpenAPI 规范校验。具体 UI 管理接口在 P3/P4 逐模块补齐，不把规划中的路由称作已实现服务。
