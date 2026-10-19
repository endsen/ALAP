# D07 · 专用 Agent 与 Skills 开发交接

本期基于 D05/D06 本地代码，尚未上传 GitHub。目标是内部可运行的 Planner/Instrument 智能决策层，不是 Web 或仪器控制服务。

## 实现

- `application/agent_config.py`：Agent/Skill 导入、发布验证、禁用、不可变版本绑定。导入只接受结构化数据，没有 shell、包安装、Python 模块加载或任意 URL 下载。
- 新共享 `skill_manifest` Schema 区分 instruction/context 与 execution/engine，含来源、维护者、依赖、权限、资源、输入输出 Schema、前置条件和成功判据；内容/hash 固定。依赖必须已发布，禁止循环；Skill 引用不扩大 Agent 工具/资源权限。
- `application/agent_runtime.py`：Planner 与 Instrument 共用受限循环，提供 `read_snapshot@1` 和 `propose_plan@1`。目标和快照进入模型；工具参数由共享契约、资源范围、Skill 参数范围、DAG、快照版本和当前成员权限共同检查。
- `adapters/agents/langgraph.py`：LangGraph 1.2.16 实际路由 inspect → model/tools/recover → inspect，单步 advance 与连续 run 两种入口。远端 LangSmith tracing 显式禁用；不使用云端 Agent 服务。
- `adapters/postgres/agents.py` 与迁移 d07_001：注册表、Agent Run、逻辑 checkpoint、trace、工具 ledger、PROPOSED 提案。注册内容/运行绑定/提案/trace 的数据库触发器防止覆盖；会话 advisory lock 排除同一 Run 的并发 worker。
- `application/models.py` / `adapters/llm/chat.py`：assistant 工具调用与 tool 结果配对、多轮历史序列化；孤立结果、未完成调用、重复结果、夹入消息均在网络前拒绝。

## 持久化与恢复选择

使用 ALAP 自有 PostgreSQL JSON checkpoint，而非 LangGraph 默认 memory saver 或其单独提交的 checkpointer 表。LangGraph 负责路由；checkpoint、工具结果 ledger、提案和 trace 在同一短事务提交，模型网络调用在事务外。没有 pickle/任意对象反序列化。

模型调用前先预留预算并提交 inflight。若进程在模型完成但结果提交前崩溃，恢复记录 MODEL_INTERRUPTED 并终止，需要新建 Run，不偷偷再次消费 API 预算。已提交的工具结果和提案恢复后不重做；工具阶段数据库中途失败完全回滚，下次可安全提交一次。

数据库仅存提案，不创建 approval、plan_revision、实验 Run 或硬件 command。提案与 D03 保存正式计划之间仍需应用 API/审核入口，留给 D09。即使 proposal 内容符合契约也不构成设备授权。

## 版本、权限与上下文

发布时持久化 Agent/Skill/工具/模型的完整绑定与 hash；新建运行不重新读取同名可变模型/工具映射。运行再保存上述绑定及执行 Skill 契约的固定快照与 hash。后续版本不改变旧运行；禁用 Agent 或绑定 Skill 会阻止旧运行的新调用。每次恢复和提交重新检查 principal、实验 membership、资源 scope；撤权后拒绝读取和继续运行。

系统策略固定版本 `alap-policy@1`；未知 prompt 引用拒绝发布。用户目标、Skill 指令、工具结果均放在数据消息，不进入系统权限层。已知 `sk-…` 凭据格式在目标和最终文本中脱敏；这不是通用 DLP，调用方仍不得提交敏感材料。

Context Builder 保留完整安全策略、实验快照/审批边界/UNKNOWN 与目标；无法容纳时失败。可删减 Skill 文本和历史，但记录删减引用，且工具调用/结果作为完整交换保留。命令和审批信息按仪器 scope 过滤；快照明确标识为数据库状态，不把配置或数据库状态冒充新鲜物理读回。长期知识、文献、已提交 Dataset 的上下文检索属于 D08，当前提案拒绝未经注入的数据证据 ID。

预算包含持久迭代数、工具数、token 预留、墙钟截止时间与上下文字节。每轮保守预留最多 profile.context_tokens，未知 usage 不按零扣减；实际 usage 在 trace 独立记录，不声称是精确费用计费。

## 运行方式

内部调用顺序：构建 `PostgresAgentStore` / `AgentRegistry`，导入并发布 Skill 与 Agent；构建 `AgentRuntime` 注入固定 ModelClient factory 与受控执行 Skill 契约；调用 `runtime.start(actor, experiment_id, definition_ref, goal)`，再用 `LangGraphAgentRunner.run/advance` 推进。外部请求不能直接指定 actor 或任意 model_factory。

```bash
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-build-isolation --no-deps -e .
# 数据库/JetStream 启动方法同 D05；迁移执行到 d07_001
.venv/bin/python -m pytest tests/integration/test_agents.py tests/test_agent_context.py tests/test_models.py -q
.venv/bin/python scripts/check.py
```

## 验证与边界

真实 PostgreSQL + 实际 LangGraph + 离线 ModelClient 验证：目标→合法提案、Instrument 只读多轮、数据库重启式对象重建、失败回滚后恢复、已提交提案不重放、未提交模型调用不重试、角色/资源越权、撤权、Skill 禁用/未发布/版本固定、注入、非法参数/证据、快照变化、预算耗尽、并发 worker 和上下文裁剪。D06 协议测试继续覆盖 OpenAI/DeepSeek 适配。

本期不重新调用付费模型；没有声称真实 LLM 的规划准确率或真实仪器验收通过。D06 DeepSeek 合成协议联调结果仍独立保存。本期全套门禁通过：348 项测试（81.32 秒），含新增 38 项 PostgreSQL/LangGraph、5 项多轮协议、2 项上下文测试；Ruff/格式、生成一致性、11 份 Schema/实例、完整 OpenAPI 和 pip check 全部通过。报告见 reports/d07-validation.txt。

仍有边界：注册表管理为可信内部接口，生产管理身份/RBAC/API 在 D09；只支持内置工具、instruction 文本和受控 engine execution 元数据；没有任意代码 Skill worker。运行以 READY/RUNNING/COMPLETED/FAILED/CANCELLED 为首批状态，交互补充输入和真正多 Agent 协作未实现。运行锁持有期间，另一进程 cancel 会返回 RUN_BUSY；正在调用模型的 worker 支持通过 Event 取消。跨进程取消请求接口属于后续服务层。

## 依据与下一期

LangGraph API 依据：[官方持久化说明](https://docs.langchain.com/oss/python/langgraph/persistence)。本项目明确采用 ALAP 的事务 checkpoint 与提案 ledger，未将框架的自动重放当作设备幂等保证。

D08：MCP 发现与授权、作用域知识/记忆、Analysis 与基于已提交数据的再规划。先补足授权与证据边界，再接外部工具；不自动推进 Web 或真机。
