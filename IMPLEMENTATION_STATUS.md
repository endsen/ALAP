# ALAP 实施状态

更新：2026-10-16。本文件区分“已设计”“已实现”“本地验证”“集成/现场验证”。整体平台尚未完成。

## 分期交接入口

- 分期计划：`docs/20_DELIVERY_PLAN.md` 的 D01–D13；P0–P7 为技术层次，D 编号为额度分批交付单位。
- 当前：**D01 已完成本地交付**；远程 CI 未运行，作为明确的后续验证项保留。
- 下一期：**D02 · 完整状态与事务设计**，尚未启动。
- 下一项具体动作：从 `docs/07_EXPERIMENT_ENGINE.md` 与 `docs/19_CONTRACT_DECISIONS.md` 出发，分别定义 Run/Task/Command 的完整转换及证据要求，再实现纯状态规则和测试，最后落实 PostgreSQL 表与事务设计。D02 不包含直接展开所有数据库、Web 或 Agent 模块。
- 当前无需要续接的运行服务，无真实凭据依赖；`/tmp` 干净环境仅用于复现验证，后续可按 README 重建。
- 本次仅补充额度分期及交接制度，业务代码未变化；检查文档重新生成与漂移一致性，不重复声明新的业务测试结果。

## 本轮交付

| 工作项 | 状态 | 证据与范围 |
|---|---|---|
| BLD-001 企划维护 | 完成 | 20 章模块文档、v3.1 合订本与可重复生成命令；保留 v3.0 |
| BLD-002 工程检查 | 本地完成；远程 CI 未运行 | pyproject、开发依赖锁、统一检查脚本、GitHub Actions 配置 |
| BLD-003 核心契约 | 第一批完成 | 9 个 Schema，计划/条件/数据/事件/命令；共享结构生成 OpenAPI |
| BLD-004 领域规则 | 第一批完成 | DAG、资源覆盖、Skill 参数与成功判据、快照版本、不可变字节/hash、来源和时间范围 |
| BLD-005 完整状态/事务设计 | 下一项 | Run/Task/Command 独立状态表，审批/租约/journal/outbox 的事务边界和恢复 |
| BLD-006/007 持久化与 Simulator | 未开始 | 需 BLD-005 冻结后编码，不使用内存假数据库代替集成验收 |

P0 基线和 P1 第一批已经建立；P1 的领域内核将随 BLD-005 补齐状态模型。尚未宣称所有 P1 业务对象已穷尽。平台新增功能全部纳入 P3–P5，当前没有其 UI 或运行服务。

## 基础测试映射

| 需求/规则 | 实际测试文件 | 能证明的范围 |
|---|---|---|
| FR-003：合法任务/条件/DAG | `tests/test_plans.py` | 形状、拓扑、资源、快照、技能参数、目标与成功条件一致 |
| FR-004：版本绑定基础 | `tests/test_plans.py` | 参数/条件/技能/策略/能力变更引起 hash 变化；输入修改不改变已冻结字节 |
| FR-009：命令契约 | `tests/test_data_commands.py` | epoch/fencing/授权字段存在、时间格式与 deadline；不证明实际授权有效 |
| FR-011：数据契约 | `tests/test_data_commands.py` | 来源覆盖、采集窗口与状态限制；不证明文件已写入 |
| FR-012：游标结构 | `tests/test_data_commands.py` | experiment_seq 与 aggregate_seq 分离；尚未测试真实 SSE 重放 |
| 跨契约一致性 | `tests/test_contract_consistency.py` | API 接受完整 Manifest 和任务条件，拒绝半成品及伪造来源字段 |

执行证据见 `reports/foundation-validation.txt`（统一命令输出）：76 项测试、9 份 Schema/实例、完整 OpenAPI、格式/lint、文档与接口生成漂移、依赖一致性检查均通过。

已在独立临时虚拟环境中按 requirements-dev.lock 重新安装依赖和项目，并再次通过同一检查，见 `reports/foundation-clean-environment.txt`。这是本机 Linux/Python 3.14 的干净环境复现；不代表远程 CI 或 Windows/macOS 已验证。当前测试不等价于第 12 章完整 EVAL 系统场景通过。

## 下一阶段进入条件

1. 完成各状态机的转移、证据类型、权限、未知结果冻结、终态与恢复出口。
2. 明确 PostgreSQL 表、唯一约束/锁顺序、事务隔离和迁移；避免把概览 DDL 当完整实现。
3. 定义审批撤销、租约过期、旧 epoch、已执行但回执丢失、数据提交中断等可执行故障用例。
4. 再实现持久化、调度和模拟 Gateway，随后接入 API 模型驱动的专用 Agent。

## 已知环境边界

- 当前 `.git` 目录不是有效 Git 工作树，且为受限只读目录；本轮未创建提交。源码和 CI 文件已落盘，远程 CI 需以后在有效仓库运行。
- 未配置或使用真实 LLM API Key；真实服务联调仍待对应阶段。
- 未发现或连接真实仪器；全部例子是模拟契约数据。
