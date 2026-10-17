# ALAP 实施状态

更新：2026-10-17。本文件区分“已设计”“已实现”“本地验证”“集成/现场验证”。整体平台尚未完成。

## 分期交接入口

- 分期计划：`docs/20_DELIVERY_PLAN.md` 的 D01–D13；P0–P7 为技术层次，D 编号为额度分批交付单位。
- 当前：**D02 已完成本地交付**（完整状态与事务设计）。D01 初始代码提交 db2c4c4 已通过 GitHub Actions；本轮 D02 尚未上传或运行远程 CI。
- 下一期：**D03 · 数据库与审批**，尚未启动。
- 下一项具体动作：先读第 21、22 章，选定并锁定 PostgreSQL 驱动/迁移工具，建立真实数据库测试环境；依次实现 D03-001～003 迁移、Repository、实验/不可变计划/审批用例、幂等和事务并发测试。数据库测试不能用内存替身代替。
- 当前无需要续接的运行服务，无真实凭据依赖；未新增开发依赖。D02 无未完成阻塞项，实际数据库与执行集成属于后续期。

## 本轮交付

| 工作项 | 状态 | 证据与范围 |
|---|---|---|
| BLD-001 企划维护 | 完成 | 22 章模块文档、v3.1 合订本与可重复生成命令；保留 v3.0 |
| BLD-002 工程检查 | 本地及初始提交远程 CI 通过 | pyproject、开发依赖锁、统一检查脚本、GitHub Actions 配置 |
| BLD-003 核心契约 | 第一批完成 | 10 个 Schema，计划/条件/数据/事件/命令；共享结构生成 OpenAPI |
| BLD-004 领域规则 | 第一批完成 | DAG、资源覆盖、Skill 参数与成功判据、快照版本、不可变字节/hash、来源和时间范围 |
| BLD-005 完整状态/事务设计 | D02 本地完成 | 六类状态机、135 条转换、证据守卫与失败语义；第 22 章表/事务/迁移方案 |
| BLD-006/007 持久化与 Simulator | 未开始 | 需 BLD-005 冻结后编码，不使用内存假数据库代替集成验收 |

P0 基线和 P1 第一批已经建立；P1 的领域内核已在 BLD-005 补齐本期状态模型。尚未宣称所有 P1 业务对象已穷尽。平台新增功能全部纳入 P3–P5，当前没有其 UI 或运行服务。

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

已在独立临时虚拟环境中按 requirements-dev.lock 重新安装依赖和项目，并再次通过同一检查，见 `reports/foundation-clean-environment.txt`。这是本机 Linux/Python 3.14 的干净环境复现；Windows/macOS 尚未验证；初始提交的 GitHub Linux CI 已通过。当前测试不等价于第 12 章完整 EVAL 系统场景通过。

## D02 验证与下一期门禁

- 新代码：`src/alap/domain/lifecycle.py`；六类状态、135 条转换、版本冲突、主体权限、证据范围/期限、冻结/隔离/停止等 effects。
- 新设计：`docs/21_STATE_MACHINES.md`、`docs/22_PERSISTENCE_TRANSACTIONS.md`；完整转换参考由代码生成并检查漂移。
- 实际命令：`.venv/bin/python scripts/check.py`，本轮输出见 `reports/d02-validation.txt`：**123 项测试、10 份 Schema/实例、完整 OpenAPI、Ruff、生成一致性、依赖检查通过**。上文 76 项为 D01 历史记录。
- 已设计但未实现：真实证据认证、状态/effects/outbox 原子提交、PostgreSQL 迁移、资源互斥及设备恢复。纯函数不能证明这些外部行为。
- D03 验收：真实数据库迁移/回滚、计划不可变、重复/冲突请求、审批失效与并发测试；按第 22 章批次及 DB 场景落实。D04/D05 再验证设备与数据故障。

## 已知环境边界

- 当前 `.git` 目录不是有效 Git 工作树，且为受限只读目录；上传使用独立工作树；初始提交已推送到私有仓库 endsen/ALAP，未更改本目录受限 .git。
- 未配置或使用真实 LLM API Key；真实服务联调仍待对应阶段。
- 未发现或连接真实仪器；全部例子是模拟契约数据。

## GitHub 上传交接（2026-10-17）

- 私有仓库：https://github.com/endsen/ALAP ，默认分支 main。
- 初始源码提交：db2c4c47b2895979c4952d3492e4c01996391541；全部 69 个项目文件（含 CI）已上传，虚拟环境、缓存与本机配置未上传。
- 初始提交 CI 已通过：https://github.com/endsen/ALAP/actions/runs/39026171006 。
- GitHub workflow 授权已完成；不在项目保存凭据或授权码。
- 上传工作树：`/tmp/alap-github-dliggqw9`；本项目目录 `.git` 仍受限，不是有效工作树。临时目录丢失时从远程重新 clone 到允许位置，再同步本目录明确变更；先检查远端，不覆盖他人提交。
- 本次后续提交只更新上传/CI 交接文档，未改变业务代码。此为 D02 开发前的上传记录；当前开发进度以上方交接为准。
