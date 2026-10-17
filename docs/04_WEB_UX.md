# 04 · Web UI/UX 与交互详细设计

> v3.1 开发基线；原始 v3.0 保存在根目录合订本与 ZIP。新增平台范围见第 17、18 章，契约规则见第 19 章，实施顺序以第 20 章为准。

完整控制台的导航、Skills/MCP/模型/用量等新增页面规范见 [17_AGENT_CONSOLE.md](17_AGENT_CONSOLE.md)。以下保留实验工作台的详细规范。

## 1. 页面结构

| 路由 | 主要元素 | 关键操作 | 权限 |
|---|---|---|---|
| `/dashboard` | 实验总览、设备健康、待办审批、警告 | 进入 Run | 登录只读以上 |
| `/workspace/:experimentId` | 会话列表 / Agent Chat / 任务与工具轨迹 | 提交目标、查看计划、打开审批 | 研究员+ |
| `/experiments` | 列表、过滤器、实验状态 | 创建/归档 | 研究员+ |
| `/experiments/:id/studio` | DAG、任务属性、版本 diff、依赖验证 | 审批/提交/暂停 | 有授权者 |
| `/instruments` | 网关、设备状态、实际值、租约、驱动版本 | 只读自检、申请控制 | 操作员+ |
| `/instruments/:id` | 连接信息、能力、状态时间戳、历史和安全摘要 | 发起经审批操作 | 精细授权 |
| `/data/:datasetId` | 曲线、通道、时间线、导出、溯源 | 比较/下载 | 有数据权限者 |
| `/approvals` | 审批队列、风险和差异、有效期 | 批准/拒绝/要求修改 | 指定审批者 |
| `/agents` | Agent 配置、模型、Prompt 版本、Tools/Skills | 编辑草案、发布版本 | 管理员 |
| `/audit` | trace、run、actor、命令、错误 | 查询审计 | 有审计权限者 |

## 2. 核心 Agent Workspace（三栏 + 详情抽屉）

```text
┌────────────────────────────────────────────────────────────────────────────────────┐
│ ALAP / Workspace       Experiment EXP-012 · RUNNING         [告警 1] [用户/身份]  │
├────────────┬──────────────────────────────────────┬────────────────────────────────┤
│ 会话/实验   │ Agent 对话与结构化卡片                │ Task / Instrument Monitor       │
│ EXP-012    │ 用户：测量磁场历史对应的 IV            │ Run R-009: RUNNING              │
│ EXP-011    │ [PlanProposal v3] [查看差异] [审批]  │ Temp: STABLE @ 10:22:03        │
│ EXP-010    │ [工具调用] analyze_iv [展开]         │ Field: 50mT @ 10:22:04         │
│            │ [数据集] DATA-100 [查看曲线]         │ Keithley: MEASURING            │
│            │ [警告] Gateway 心跳超时               │ Tasks: 2/5 complete            │
├────────────┴──────────────────────────────────────┴────────────────────────────────┤
│ [暂停新任务] [取消实验] [申请人工接管]  [输入实验目标或分析问题...] [发送]       │
└────────────────────────────────────────────────────────────────────────────────────┘
```

页面核心心智模型：**对话仅用于沟通；计划卡片是执行前的事实；右栏为服务器/设备权威状态；审批是具体命令许可**。

## 3. 统一 UI 状态规范

| 组件 | 状态 | 可见行为 | 错误恢复 |
|---|---|---|---|
| Agent Message | QUEUED/STREAMING/COMPLETE/ERROR | 流式回答；错误保留原请求 ID | 可“重试生成”，不会重试物理命令 |
| Tool Card | PROPOSED/VALIDATING/RUNNING/SUCCEEDED/FAILED/BLOCKED | 显示工具、脱敏参数、授权依据、持续时间 | BLOCKED 展示策略原因 |
| Plan Card | DRAFT/VALIDATED/AWAITING_APPROVAL/APPROVED/SUPERSEDED | diff、资源、风险、版本 | 修改后旧审批失效 |
| Task Card | PENDING/READY/RUNNING/WAITING_RESOURCE/UNKNOWN/FAILED/DONE | 命令和设备实际值关联 | UNKNOWN 显示人工核对路径 |
| Device Card | ONLINE/STALE/OFFLINE/FAULT/INTERLOCKED | **时间戳 + 实际值 + 数据鲜度** | STALE 不显示可执行按钮 |
| Dataset Card | STAGING/VALIDATING/COMMITTED/CORRUPT | 仅 COMMITTED 可公开读取 | 失败保留审计和诊断 |
| Approval | PENDING/APPROVED/REJECTED/EXPIRED/REVOKED | 显示审批人、作用域和有效期 | 无法批准过期提案 |

颜色不是唯一状态表达：必须同时给文字、图标/状态说明，满足基本无障碍要求。

## 4. 用户关键交互（状态与错误处理）

### 4.1 提交实验请求
用户输入 → API 创建 message → `agent.run.created` → token stream（可选） → `plan.proposed` → 计划卡片。模型推理失败展示“未产生计划”，禁用“执行”而不是展示貌似正常的部分计划。

### 4.2 审批计划
点击审批 → 弹窗展示目标设备、动作、参数边界、潜在危险、设备最新状态及**plan_version** → 二次确认 → 后端核验 `If-Match`/版本 → 返回 Approval ID。版本冲突 409 时重新加载 diff，不可沿用旧审批。

### 4.3 暂停/取消
“暂停”指**停止调度新的任务、请求当前任务到达安全中断点**；不是直接保证设备立即停止。“取消”显示 `CANCEL_REQUESTED`，直到 Gateway 确认安全结束才变为 `CANCELLED`；不明状态显示 `UNKNOWN/NEEDS_ATTENTION`。

### 4.4 人工接管
显式“申请接管” → 展示原租约持有人及当前运行任务 → Scheduler 协调回收/安全停止 → 重新确认现场状态 → 发放新的单调 fencing token → 日志记录接管者与原因。不可仅靠前端隐藏按钮来保证安全。

## 5. SSE 事件与页面刷新策略

1. `GET /api/v1/experiments/{id}/events?after={seq}` 返回 SSE；每条有 `id: <experiment_seq>`。
2. 浏览器记录最近成功应用的 experiment_seq；断线使用 `Last-Event-ID` 或 `after` 续传。若采用原生 EventSource，使用经过 CSRF 防护的同源 HttpOnly session cookie；若用 Bearer token，则使用支持 Authorization Header 的 fetch streaming 客户端。
3. 若事件保留窗口已过，服务返回明确的 `RESYNC_REQUIRED` 语义；先 `GET /experiments/{id}` 获取权威快照，再续接事件。
4. 消息去重依赖 `(experiment_id, experiment_seq)`；必须对乱序情况延迟处理/请求快照；浏览器不可将 SSE 当作命令是否执行的证据。
5. 曲线数据通过 dataset API / 专用数据读取接口获取，事件仅引用 dataset ID，不直接传数 MB 原始数组。

## 6. 前端组件规范

- `PlanDiff`: 显示旧/新版本、改变的步骤/参数/资源和审批状态。
- `DeviceStatus`: `observed_at`、`staleness_ms`、目标与实际、连接/告警与控制 owner，支持离线占位。
- `ToolTrace`: 发起者、工具名、输入脱敏、验证/授权节点、错误类型、trace_id、持续时间。
- `ApprovalDrawer`: 执行影响、权限范围、风险级别、TTL、Revocation 链接。
- `DatasetPlot`: 轴单位、采样时间窗、数据修订、导出摘要与可复现条件。
- `RunTimeline`: 时间顺序显示 Agent 提案、用户审批、调度、网关确认、分析与人工接管。

## 7. 验收检查

- 错误、慢网、断线、事件重放后，Web 状态与数据库一致；任何时间不能用“完成”掩盖 `UNKNOWN`。
- 至少一轮可用性测试覆盖实验创建、计划审核、运行监控、数据查看、异常介入与复盘。
- Observer 不能通过页面或直接 API 调用获得设备写权限。
- 页面必须区分“命令已发送”“设备已确认执行”“读回验证成功”三个状态。
