# 06 · 多 Agent 协作与集中仲裁协议

> v3.1 开发基线；原始 v3.0 保存在根目录合订本与 ZIP。新增平台范围见第 17、18 章，契约规则见第 19 章，实施顺序以第 20 章为准。

## 1. Agent 角色划分

| 角色 | 输入 | 输出 | 允许副作用 |
|---|---|---|---|
| Planner Agent | 实验目标、设备能力、状态快照、历史数据摘要 | 版本化 PlanProposal / ReplanProposal | **无物理写** |
| Instrument Agent | 授权范围内的设备能力、只读状态与所属实验数据 | 状态解释、局部测量 Proposal、诊断结果 | 只读与提案；执行端由 Gateway 完成 |
| Measurement Agent | 实验技能、设备能力组合、计划参数 | IV/RH 等 Skill Plan | 无直接跨设备控制 |
| Analysis Agent | Dataset Manifest 与授权数据 | 统计、图表、异常、后续测量提议 | 无物理写 |
| Reviewer / Policy Engine | 候选计划、安全规则、资源和审批范围 | VALID / REJECT / REQUIRE_APPROVAL | 决策结果，不直达仪器 |

## 2. 协同基本协议

`OBSERVE → PROPOSE → VALIDATE → ARBITRATE → APPROVE → SCHEDULE → EXECUTE → VERIFY → PUBLISH → REPLAN`。任何 Agent 即使能看见其他设备的状态，也不能直接向该设备发送未授权任务。

### 2.1 TaskProposal（局部建议，不能直接执行）

```json
{
  "proposal_id": "P-012",
  "experiment_id": "EXP-012",
  "source_agent_run_id": "AR-101",
  "based_on_snapshot_version": 18,
  "proposal_type": "add_measurement",
  "requested_resources": ["magnet-01", "keithley-01"],
  "operation": "field_dependent_iv",
  "parameters": {"field_points_mT": [35, 40, 45]},
  "evidence_dataset_ids": ["DATA-009"],
  "reason": "在数据集中检测到可能的非线性特征，需复核",
  "risk_level": "operator_review"
}
```

上例是局部 TaskProposal，必须经 Planner 转换为含 tasks 的 PlanProposal，不能提交给完整计划 API。Proposal 是建议；字段可经 Schema 和服务器规则校验，但**只有 Scheduler 持有效授权和设备锁才能形成命令**。

### 2.2 规划快照版本

每个 Proposal 绑定 `snapshot_version` 和计划 `revision`；状态变化导致资源可用性或安全前提失效时，系统要求重新规划/重新审批。旧计划不通过隐式迁移获得新权限。

## 3. 事件驱动而非 Agent 无限对话

建议让 Agent 订阅**业务领域事件**，而非互相持续闲聊：`dataset.committed.v1`、`device.status_changed.v1`、`analysis.completed.v1`、`proposal.rejected.v1`。只有与其 scope 匹配的 Agent 会被唤醒；每个唤醒有预算/去重及最大再规划次数，防止循环自激。

## 4. 任务仲裁规则（确定性）

1. 验证 Agent 身份、实验归属、操作类型和 Proposal Schema。
2. 对所有目标设备建立可排序资源集合，拒绝未授权或故障设备。
3. 校验任务 DAG 无循环、前置约束满足、数据时间新鲜。
4. 检查实验/设备级并发预算与风险等级。
5. 生成 Plan revision，必要时等待有效期内的人类审批。
6. 对多设备任务先做资源预留/租约排序，防止死锁；失败释放已预留项。
7. 下发有限生效期的 CommandEnvelope，执行器二次核对。
8. 执行完成将实际结果和来源写回实验权威状态，再触发可选 replan。

## 5. 自治等级建议

| 等级 | 允许能力 | 示例 |
|---|---|---|
| L0 | 只读监控 | 温度查看 |
| L1 | 执行预先人工批准的固定流程 | 已核准 IV Scan |
| L2 | 在批准的 envelope 内局部调整非危险算法参数 | 数据拟合采样密度建议、有限自适应 |
| L3 | 提出新计划并请求授权 | 新的磁场扫描区间 |
| L4 | 在预先明确的实验边界中自动批准低风险局部计划 | 仅在独立策略允许、完成现场风险评审后启用 |

自治级别不能覆盖设备安全硬限制。MVP 默认 L0/L1，L2 需逐设备启用；L4 不纳入 MVP。

## 6. 数据共享约定

不同 Agent 访问的不是同一份 LLM 对话，而是统一的 `ExperimentView`：`experiment_id`、`snapshot_version`、最新有效设备读数及时间戳、task 结果、可访问 Dataset Manifest、异常摘要。数据权限按实验和仪器双重过滤。

## 7. 协作失败模式

- 两个 Agent 提出同一任务：业务指纹去重，同一版本可聚合 Evidence，不能产生两个设备命令。
- 重规划计划冲突：采用 optimistic concurrency (`expected_revision`)，409 触发重新加载。
- Agent 离线：执行中的有限任务不依赖 Agent 存活；新规划暂停。
- Agent 反复提案：设置次数上限、冷却周期、需有新证据或人工复核。
- 资源抢占：依据显式优先级和人工接管规程，不使用自然语言协商决定最终资源所有权。

## 8. 示例：磁场历史影响零场 IV

`Planner(设置测量目标)` → `Temp Agent(报告温度稳定建议)` → `Scheduler(核验温控稳定)` → `Magnet Gateway(经授权设定磁场与回零)` → `SourceMeter Gateway(IV 扫描)` → `Dataset COMMITTED` → `Analysis Agent(计算 Ic± 与 η)` → `Planner(提出密集磁场扫描建议)` → `Operator Approval` → `下一 Run`。稳定判据必须基于传感器读数、滑动窗口和设备规程；“磁场目标为 0”不意味着样品内部无残余磁通。

## D08 内部协作实现

AnalysisCoordinator 从权威 dataset.committed 事件生成作用域分析引用，再启动 Analysis 或 Planner。以 actor/experiment/definition/证据指纹去重，固定 Run ID 修复创建与 claim 绑定间中断；新证据受冷却与次数预算约束。跨 Run 的相同结构计划由业务指纹约束阻断，未做自然语言近似去重。本期没有常驻多 Agent 事件 worker，也不通过自然语言协商授予执行权。
