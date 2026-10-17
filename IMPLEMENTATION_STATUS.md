# ALAP 实施状态

更新：2026-10-18。本文件区分“已设计”“已实现”“本地验证”“集成/现场验证”。整体平台尚未完成。

## 分期交接入口

- 分期计划：`docs/20_DELIVERY_PLAN.md` 的 D01–D13；P0–P7 为技术层次，D 编号为分批交付单位。
- 当前：**D04 已完成本地交付与真实 PostgreSQL / 离线模拟网关验收**。D03/D04 已以 `d3f064b` 推送至 origin/main；远程 CI 结果见下方最新上传交接。
- 下一期：**D05 · 数据与事件恢复，尚未开始**。按第 20–22 章补齐 Dataset/血缘、outbox 发布/NATS、暂停取消及停止确认；重点在资源释放和代际恢复时核验停止请求，不将本地 IV 文件视为正式 Dataset。
- 环境：当前 macOS 工作树 `/Users/endsen/codex/ALAP`，origin 为 endsen/ALAP，main；旧 Linux 上传临时目录仅保留历史记录。
- D01/D02 的历史提交与远程 CI 已通过，详见下方历史交接；D03/D04 实现提交为 d3f064b，已推送。

## D04 本地交付（2026-10-18）

| 工作项 | 状态 | 实现与验证 |
|---|---|---|
| D04-001 数据与执行 | 完成 | 固定 DAG 任务、资源整组领取、租约续期、fencing/epoch、不可变命令与单次投递 |
| 三设备模拟网关 | 完成 | 温控/磁场/SMU、稳定窗口检查、独立持久 journal、进程独占与重复命令拒绝 |
| 故障与对账 | 本地通过 | ACK 丢失、发送前宕机、实际子进程退出、重启显式对账、乱序/矛盾回执、隔离及恢复代际 |
| 项目统一检查 | 本地通过 | **202 项测试**、10 份 Schema/实例、OpenAPI、Ruff、生成漂移、pip check |

证据：`reports/d04-validation.txt`；详细实现、命令与限制见 `docs/D04_EXECUTION_DEVELOPMENT.md`。新增 28 项执行集成测试和 16 项稳定窗口测试，连同原 158 项全部通过。环境为 macOS / Python 3.14.8 / PostgreSQL 18.6；本地验收时远程 CI 尚未运行；后续结果见最新上传交接。Windows 未验证。

中央 PostgreSQL 与近端 journal 分离；离线 HMAC 不代表生产 mTLS。没有常驻 worker/API/Gateway 服务，没有真机或 LLM 操作。IV 本地结果保持 VERIFYING，Dataset 提交、消息发布、完整暂停取消协议待 D05。停止请求目前仅预留表结构。验收后停止本机临时 PostgreSQL，不注册常驻服务。

## D03 本地交付（2026-10-17）

| 工作项 | 状态 | 实现与验证 |
|---|---|---|
| D03-001 基础迁移 | 完成 | principals/samples/experiments/memberships；空库 up/down/up、约束和隔离身份 |
| D03-002 计划与审批 | 完成 | 不可变 canonical_bytes/hash、完整审批包络、精确版本、资源/风险权限、READY Run、幂等与并发 |
| D03-003 事务证据与事件 | 完成 | evidence/audit/outbox、实验 cursor；审批失效及 Run effects 同事务；注入故障全回滚 |
| 真实数据库集成 | 本地通过 | 35 项测试，独立 PostgreSQL 18.6、多连接竞争、实际数据库时钟到期、快照一致性 |
| 项目统一检查 | 本地通过 | **158 项测试**、10 份 Schema/实例、OpenAPI、Ruff、生成漂移、pip check 全部通过 |
| CI 配置 | 已更新，远程未运行 | GitHub Actions 加 PostgreSQL 18 service；后续推送后观察真实 CI |

主要新增文件：`src/alap/application/experiments.py` / `ports.py`、`src/alap/adapters/postgres/repository.py`、`migrations/versions/d03_001～003`、`tests/integration/`、`docs/D03_DATABASE_DEVELOPMENT.md`。共享契约未另起副本，outbox 在写入前校验现有 event Schema。

验证命令：设置本机隔离数据库的 `ALAP_TEST_DATABASE_URL` 后运行 `.venv/bin/python scripts/check.py`。输出见 `reports/d03-validation.txt`。当前为 **macOS / Python 3.14.8 / PostgreSQL 18.6**；Windows 与本期远程 Linux CI 尚未验证。

依赖：Psycopg binary 3.3.6、Alembic 1.20.0、SQLAlchemy 2.1.5 及传递依赖已加入锁文件；在项目 `.venv` 安装。Homebrew 安装 Python 3.14 与 PostgreSQL 18，未注册数据库开机服务。

测试集群位于 `/private/tmp/alap-d03-postgres`，数据库名 `alap_test`，仅本机 55432 端口；测试按随机 schema 隔离并自动清理。验收结束停止集群，未保留运行服务；该临时数据目录丢失时可按开发说明重建，不包含必须续接的业务数据。Homebrew 默认初始化的集群未用于本次测试。

### D03 边界与后续事项

- 已集成验证的范围是数据库及内部应用用例。没有 Web/HTTP API/Agent Runtime/NATS/Gateway/设备服务；没有模型凭据或真机操作。
- actor ID 来自未来认证入口；当前测试显式配置身份/权限。真实登录和 HTTP 状态码映射属于 D09，不把内部参数当作已完成认证。
- 新建实验不会授予设备权限：owner 的资源/风险 scope 默认为空，由身份管理方显式配置；没有匿名管理员。
- Skill/策略/能力版本来自受信任配置；真实注册表在后续期。审批使用精确计划/hash/scope/期限，期限在取得锁后用数据库当前时钟核验。
- Run 只创建 READY，保存任务 ID/attempt_no=1，dispatch_blocked=true；D04 才创建 tasks、租约、命令及执行。审批失效时仅对未发放 Run 推导 children_quiescent，其他执行态不能凭空确认。
- 本期只写持久 outbox；NATS 发布/消费、SSE 重连、设备故障与现场门禁仍按 D04/D05/D09/D13 验证。
- Git 环境过期记录已修正；当前工作树有效，但 Git 元数据写入仍服从会话权限。本期未提交/推送，不复用旧环境临时目录。

## 本轮交付

| 工作项 | 状态 | 证据与范围 |
|---|---|---|
| BLD-001 企划维护 | 完成 | 22 章模块文档、v3.1 合订本与可重复生成命令；保留 v3.0 |
| BLD-002 工程检查 | 本地及初始提交远程 CI 通过 | pyproject、开发依赖锁、统一检查脚本、GitHub Actions 配置 |
| BLD-003 核心契约 | 第一批完成 | 10 个 Schema，计划/条件/数据/事件/命令；共享结构生成 OpenAPI |
| BLD-004 领域规则 | 第一批完成 | DAG、资源覆盖、Skill 参数与成功判据、快照版本、不可变字节/hash、来源和时间范围 |
| BLD-005 完整状态/事务设计 | D02 本地完成 | 六类状态机、135 条转换、证据守卫与失败语义；第 22 章表/事务/迁移方案 |
| BLD-006 持久化/审批/outbox 写入 | D03 本地完成 | 三批 PostgreSQL 迁移及真实事务测试；消息发布在 D05 |
| BLD-007 Simulator/执行层 | D04 本地完成 | DAG、三模拟设备、租约/epoch/fencing、journal 与显式故障对账 |

P0/P1 基础和 P2 的 D03 数据库/审批、D04 模拟执行部分已建立。P2 数据与事件恢复仍待 D05；平台新增功能纳入 P3–P5，当前没有其 UI 或运行服务。

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

已在独立临时虚拟环境中按 requirements-dev.lock 重新安装依赖和项目，并再次通过同一检查，见 `reports/foundation-clean-environment.txt`。这是本机 Linux/Python 3.14 的干净环境复现；Windows/macOS 尚未验证；首期与 D02 提交的 GitHub Linux CI 均已通过。当前测试不等价于第 12 章完整 EVAL 系统场景通过。

## D02 验证与历史 D03 门禁

- 新代码：`src/alap/domain/lifecycle.py`；六类状态、135 条转换、版本冲突、主体权限、证据范围/期限、冻结/隔离/停止等 effects。
- 新设计：`docs/21_STATE_MACHINES.md`、`docs/22_PERSISTENCE_TRANSACTIONS.md`；完整转换参考由代码生成并检查漂移。
- 实际命令：`.venv/bin/python scripts/check.py`，本轮输出见 `reports/d02-validation.txt`：**123 项测试、10 份 Schema/实例、完整 OpenAPI、Ruff、生成一致性、依赖检查通过**。上文 76 项为 D01 历史记录。
- D02 当时未实现：真实证据认证、状态/effects/outbox 原子提交、PostgreSQL 迁移、资源互斥及设备恢复。D03 已补齐数据库及审批范围；设备部分仍待 D04/D05。
- D03 验收：真实数据库迁移/回滚、计划不可变、重复/冲突请求、审批失效与并发测试；按第 22 章批次及 DB 场景落实。D04/D05 再验证设备与数据故障。

## D02 GitHub 上传交接（2026-10-17 19:30 local）

- 提交 `3551e1b`（D02：状态机与事务设计）已推送到私有仓库 endsen/ALAP 的 `main`，26 个文件变更、+2697/−259。
- 该提交的远程 CI（Foundation checks，run 39028777991）已通过。
- 上传使用上传工作树 `/tmp/alap-github-dliggqw9`；内容已与该目录做全量比对（排除 `.git/.venv/缓存`）后同步，未覆盖他人提交。
- 历史环境记录：D02 上传时原目录无有效 Git 工作树，曾使用上述临时目录；当前已重新克隆，此限制描述不再适用。
- 上传前已扫描暂存差异，未发现密钥类字符串。

## 已知环境边界

- 当前 macOS 路径 `/Users/endsen/codex/ALAP` 为有效 Git 工作树，origin 指向 endsen/ALAP；不依赖旧 Linux 临时目录。写入 Git 元数据仍遵循会话权限。
- 未配置或使用真实 LLM API Key；真实服务联调仍待对应阶段。
- 未发现或连接真实仪器；全部例子是模拟契约数据。

## GitHub 上传交接（2026-10-17）

- 私有仓库：https://github.com/endsen/ALAP ，默认分支 main。
- 初始源码提交：db2c4c47b2895979c4952d3492e4c01996391541；全部 69 个项目文件（含 CI）已上传，虚拟环境、缓存与本机配置未上传。
- 初始提交 CI 已通过：https://github.com/endsen/ALAP/actions/runs/39026171006 。
- GitHub workflow 授权已完成；不在项目保存凭据或授权码。
- 历史上传工作树：`/tmp/alap-github-dliggqw9`，仅记录 D01 旧环境。当前使用已克隆的 macOS 工作树；提交前检查本地与远程状态，不覆盖他人提交。
- 本次后续提交只更新上传/CI 交接文档，未改变业务代码。此为 D02 开发前的上传记录；当前开发进度以上方交接为准。

## D03/D04 GitHub 上传交接（2026-10-18）

- 实现提交 `d3f064b19f7e9b51e573e5014477de05b46beccf` 已推送至 endsen/ALAP 的 main，包含 38 个文件变更及 D03/D04 验收报告。
- 该实现提交的远程 Foundation checks 已通过：https://github.com/endsen/ALAP/actions/runs/39052377810 。Linux CI 使用真实 PostgreSQL 18 执行统一检查。
- 本次交接文档另作后续提交；上面的 CI 结果明确对应实现提交，不冒充后续提交结果。
- 推送前检查远程无分叉、暂存差异格式及常见凭据模式；未纳入虚拟环境、缓存、临时数据库或 journal 文件。
- 下一期仍为 D05，尚未开始；Windows 与真机验收未完成。
