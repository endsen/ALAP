# ALAP · Autonomous Laboratory Agent Platform

面向实验室的专用 Agent 平台：通过多供应商 API 接入 LLM，由 Planner、Instrument、Analysis Agent 规划和分析实验，由确定性引擎及 Gateway 执行已授权任务。

**当前完成的是 v3.1 企划修订及D02 状态领域内核及持久化事务设计。尚无运行中的 Web、API、Agent Runtime、数据库或设备服务。** 各层实际进度见 [实施状态](IMPLEMENTATION_STATUS.md)。

## 文档入口

- [v3.1 完整企划](ALAP_Engineering_Design_v3.1_完整合订本.md)：由 `docs/01–22` 生成。
- [平台控制台与页面](docs/17_AGENT_CONSOLE.md)：Skills、MCP、仪表板、模型、用量、轨迹与知识。
- [LLM API 接入](docs/18_LLM_INTEGRATION.md)：首批 OpenAI/DeepSeek，多协议适配、凭据与能力。
- [领域与契约决策](docs/19_CONTRACT_DECISIONS.md)：计划、条件、来源、事件游标及恢复边界。
- [分层交付计划](docs/20_DELIVERY_PLAN.md)：P0–P7 依赖与质量门禁。
- [完整状态机](docs/21_STATE_MACHINES.md)：六类对象、证据守卫、失败语义及可执行规则。
- [持久化事务设计](docs/22_PERSISTENCE_TRANSACTIONS.md)：表约束、锁顺序、事务、迁移批次与故障验收。
- [企划评审](PROJECT_REVIEW.md)：保留原始发现，附本轮问题处理状态。

原始 v3.0 合订本与 ZIP 保持不变，作为历史输入。v3.1 代表开发基线，不代表现场安全批准。

## 本地环境与检查

基础层当前使用 Python 3.14（本机 3.14.7）；框架与硬件 SDK 在后续各层接入时验证兼容性，不能假定本阶段环境已适合所有驱动。版本调整需更新工程配置、锁文件及 CI。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-build-isolation --no-deps -e .
.venv/bin/python scripts/check.py
```

检查包括 Ruff、状态转换参考表漂移、文档生成漂移、OpenAPI 生成漂移、10 份 JSON Schema 及实例、完整 OpenAPI 规范、领域/契约测试、依赖一致性。全套检查不调用外部模型、不连接仪器或数据库。`requirements-contracts.txt` 保留最早 v3.0 校验依赖；当前开发环境以 `requirements-dev.lock` 为准。

编辑 `docs/` 或契约源后更新生成文件：

```bash
.venv/bin/python scripts/build_lifecycle_reference.py
.venv/bin/python scripts/build_design.py
.venv/bin/python scripts/build_openapi.py
```

不要直接编辑生成合订本或 `contracts/openapi.yaml`。仅跑契约检查可用 `.venv/bin/python contracts/validate_contracts.py`；运行领域测试用 `.venv/bin/python -m pytest -q`。

## 目录与依赖边界

```text
docs/                       模块化企划、领域规则、分层计划
contracts/*.schema.json     共享数据结构的唯一来源
contracts/openapi.base.yaml 手写 API 路由与非共享结构
contracts/openapi.yaml      生成后的规范
contracts/examples/        模拟正例与模拟技能参数约束
src/alap/domain/            无网络/数据库/框架依赖的领域规则
src/alap/contracts.py      离线 Schema 校验与领域规则入口
scripts/                    生成与统一质量检查
tests/                      契约、领域及跨接口一致性测试
.github/workflows/          GitHub CI 配置（初始提交已通过）
```

后续按依赖增加 application、持久化/消息/模型/MCP 适配器、FastAPI/worker/Gateway 入口，以及 `apps/web`、`infra`。计划路径不提前伪装为可运行组件。

基础校验只是执行前的一道检查；它不验证真实授权、租约、仪器实时状态或数据文件存在。模拟例子中的参数不得用于真实设备。
