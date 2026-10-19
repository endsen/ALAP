# 05 · Agent Platform 与 Runtime 详细设计

> v3.1 开发基线；原始 v3.0 保存在根目录合订本与 ZIP。新增平台范围见第 17、18 章，契约规则见第 19 章，实施顺序以第 20 章为准。

## 1. 边界与组件

**Agent Platform** 是可配置的智能执行环境，不是物理设备控制平面。它包含 `Agent Registry`、`Configuration Versioning`、`Model Adapter`、`Prompt/Context Builder`、`Agent Loop`、`Tool Registry`、`Skill Registry`、`Memory`、`Trace`、`Evaluation`。Agent 对实验的影响通过 `PlanProposal`/`TaskProposal` 输出，由 Experiment Engine 审核处理。

## 2. 运行模型

| 对象 | 生命周期 | 存储 |
|---|---|---|
| AgentDefinition | DRAFT→PUBLISHED→DEPRECATED | Registry + immutable versions |
| AgentInstance | CREATED→READY→RUNNING→WAITING_INPUT→COMPLETED/FAILED/CANCELLED | agent run table + checkpoint |
| AgentTurn | RECEIVED→REASONING→TOOL_REQUESTED→TOOL_DONE→RESPONDED | structured trace |
| ToolInvocation | VALIDATING→AUTHORIZED/BLOCKED→EXECUTING→SUCCEEDED/FAILED/UNKNOWN | tool call ledger |

Agent Instance 与“每台硬件”的部署不是一一对应的。一个 Gateway 可管理多台仪器，多个逻辑 Agent 可共享同一个 LLM，**但写权限仍受设备租约唯一性约束**。

## 3. Agent Loop 标准流程

```text
receive message / event
  → load immutable AgentDefinition version
  → build context (goal, allowed tools, scoped experiment snapshot, provenance)
  → call model (bounded tokens/time/iterations)
  → validate model output structure
    ├─ final answer → persist trace → return
    ├─ read-only tool → authorize + execute → append result → loop
    ├─ write proposal → validate → persist PROPOSED → return proposal ID
    └─ invalid/disallowed → BLOCK + audit → bounded repair or stop
```

所有工具调用必须有**执行前校验**（Schema、调用者、实验范围、权限、风险、速率预算）；工具结果中含不可信文本，绝不能覆盖高优先级约束。

## 4. Agent 配置（示例）

```yaml
agent_id: inst-keithley-01
version: 3
kind: instrument
model_ref: model-profile-default
system_prompt_ref: prompts/keithley-v2
max_iterations: 12
max_runtime_seconds: 180
allowed_tools: [read_instrument_state, propose_iv_measurement]
scoped_instruments: [keithley_2450_01]
scoped_experiments: [EXP-012]
autonomy_level: L2
skill_refs: [iv_measurement@1]
context_policy: experiment_snapshot_only
```

生产时 `model_ref` 是管理员审批的服务引用，不能让用户随意填写未知 URL/密钥。配置必须包含 hash、发布人、发布时间、变更差异。JSON Schema 参见 `contracts/agent_manifest.schema.json`。

## 5. Tools、Skills、Workflows 三层抽象

- **Tool**：最小 API，例如 `read_temperature`、`get_dataset_summary`、`propose_measurement`；有输入输出 Schema、权限、成本和重试分类。
- **Skill**：可复用的高阶实验能力，例如 `iv_measurement@1`；引用工具/确定性脚本、先验条件、产出数据模式和需要的资源。
- **Workflow**：跨 Agent/设备的 DAG，有版本、依赖、条件和审批边界。

建议的工具元数据：`tool_id`, `version`, `input_schema`, `output_schema`, `side_effect` (`none|proposal|physical_write`), `required_scopes`, `timeout`, `retry_policy`, `owner`, `safety_class`。**物理写工具不直接注册给一般 LLM**：模型只能调用经过编排的 proposal API；Scheduler/Gateway 独立执行。

## 6. Context & Memory

四类隔离：Agent thread checkpoint、Experiment snapshot（权威结构化状态）、长期知识/文献索引、已提交实验数据。模型上下文仅注入必要摘要和带出处的引用，不复制所有日志/大数组。

### 6.1 Context Builder 输入契约
`(agent_id, config_version, experiment_id, user_message, run_snapshot_version, selected_dataset_ids, tool_policy_version)`；输出包括 token budget、引用的状态版本、数据来源和裁剪记录。过期状态不可用于批准设备写。

### 6.2 压缩策略
按消息优先级保留：System/Policy 引用 → 未完成任务与批准边界 → 最近工具结果 → 相关数据摘要 → 旧对话摘要。压缩必须保留未知状态/失败原因与来源；不得将未经验证的推断变成事实。

## 7. Model Adapter

统一接口包含 `generate(messages, tools, max_output_tokens, timeout, trace_context)`，返回 `text`、结构化 tool calls、token usage、model identifier、finish reason、错误分类。流式 token 仅影响聊天 UI，不影响物理执行授权。

超时/限流重试仅适用于**无副作用模型调用**；每一次模型再生成必须产生新的 trace，不能自动再次发起既有硬件命令。

## 8. 权限模型与注入防护

- 系统配置、用户消息、外部文献、仪器日志严格区分可信等级；外部文本只是资料，不能授予工具权限。
- LLM/Agent 不是授权来源；Tool Gateway 通过 code-based policy 验证 JWT scopes + 实验资源范围 + 工具安全级别。
- 模型输出的计划经过 Schema 和规则引擎检验，包括资源可用、参数上下界、依赖闭环、版本有效性。
- 对数据检索、工具调用参数、文件路径做 allowlist，禁止任意 shell、任意网络访问或裸 SCPI 等默认能力。

## 9. Trace 与可重现性

每个 Agent 调用记录 `trace_id`、`agent_run_id`、`agent_definition_version`、`model_id`、`prompt_template_hash`、`context_refs`、`tool_version`、`tool_input_hash`、`decision_type`、`outcome`、`token/cost`；敏感信息脱敏。模型回答不保证逐 token 可重复，但应该重建决策依据和输入数据版本。

## 10. 检查点与恢复

LangGraph checkpointer 可持久化智能体线程并支持交互中断；**恢复只恢复逻辑决策过程**。若检查点中出现任何已提交的物理命令，必须先与 Experiment Engine 的 `command_ledger` 对账：`SUCCEEDED` 不重做，`UNKNOWN` 需查询真实状态，`NOT_DISPATCHED` 才能继续正常调度。Human-in-the-loop 审批需将审批范围与具体 plan hash 绑定。

## 11. Agent 测试契约

每个 AgentDefinition 发布前必须通过：结构化输出验证、恶意 Prompt 注入测试、工具越权测试、过期数据测试、预算耗尽测试、提案来源追踪测试。详见 `12_EVALUATION.md`。

## 12. v3.1 管理能力

多供应商 API 的配置、能力矩阵、统一流、错误/用量规范见第 18 章。Skills 分为 instruction/execution，MCP 发现与授权分离，平台管理流程见第 17 章。角色均由 ALAP 实现，不依赖供应商托管 Agent。MCP 是工具接入方式，Skills 是版本化能力，两者都受同一权限层约束。

## 13. D07 实现落点

Planner/Instrument 的 model/tools/recover 条件路由已用 LangGraph 实现。采用 ALAP PostgreSQL JSON checkpoint，与工具 ledger、PROPOSED 提案原子提交；不使用独立自动重放机制处理实验副作用。已有结果恢复不重做，未提交的模型调用保守终止。角色/Skill/工具/模型快照固定，运行时重新检查成员权限、版本禁用、预算和快照。多轮 tool 消息成对校验，上下文裁剪记录来源并保留安全边界。具体可运行范围、验证和未实现状态见 D07_AGENT_SKILLS_DEVELOPMENT.md；正式计划审核/API、WAITING_INPUT、MCP/知识与 Analysis 属于后续期。

## 14. D08 实现落点

Analysis 角色、受控 MCP 只读工具、scoped_knowledge 与数据分析工具已接入同一运行循环。知识、记忆和分析都带来源引用，checkpoint 恢复及提交重新检查授权/启停/数据状态；资料不能成为权限。Context Builder 可注入不可静默丢弃的分析证据。首版为文本子串检索和确定性 IV 描述统计，没有向量 RAG、自动知识写入或物理判据推断。协议与算法边界见 D08_MCP_KNOWLEDGE_ANALYSIS.md。
