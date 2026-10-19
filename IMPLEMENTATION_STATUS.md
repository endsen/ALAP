# ALAP 实施状态

更新：2026-10-19。本文件区分“已设计”“已实现”“本地验证”“集成/现场验证”。整体平台尚未完成。

## 分期交接入口

- 分期计划：`docs/20_DELIVERY_PLAN.md` 的 D01–D13；P0–P7 为技术层次，D 编号为分批交付单位。
- 当前：**D10 · Web 实验工作区，已完成本地验收**。D05–D10 已推送 GitHub `main`，代码提交 `0015fa6`；远程 CI 结果待核验。
- 下一期：**D11 · Web 平台控制台**。先实现 Agent/模型/Skills/MCP 配置，再推进知识、仪表板、用量、轨迹、审计与设置；尚未启动。
- 当前环境：Linux `/home/endsen/ALAP`，原 `.git` 受限且无效；独立 Git 检出 `/tmp/alap-github-dliggqw9` 已同步并推送本轮代码（`0015fa6`）。本目录仍为开发工作区，后续同步前先核对远端。
- D03/D04 的远程 CI 已通过，最新基线 a0f0880 的 202 项结果已核对；下方 macOS 信息是历史开发记录。

## D10 本地交付（2026-10-19）

- `apps/web` 实现 Next.js/React/TypeScript 工作区：内存令牌登录、实验/样品创建、目标会话、结构化提案、计划依赖/参数/版本差异、人工审批、Run 控制请求、只读设备、IV 曲线与 HDF5 下载。
- 同源 API、SSE 游标重连/快照恢复、未知状态、断线禁写、撤权清屏、版本冲突与幂等未知保护已接入。补充工作区身份/权限、适用 Agent、计划上下文、曲线接口；现有 64 个契约操作，无新数据库迁移。
- 后端统一门禁：430 项测试通过（165.66 秒），Ruff/格式、生成一致性、13 份 Schema/实例、OpenAPI 与 pip check 通过。报告 `reports/d10-validation.txt`。
- Web 统一门禁：生成类型一致性、Prettier、TypeScript、7 项单元测试、生产构建、9 项 Chromium 浏览器用例通过。报告 `reports/d10-web-validation.txt`；浏览器复验见 `reports/d10-browser.txt`，SIGTERM 退出/身份文件/schema 清理验证见 `reports/d10-fixture-cleanup.txt`。已检查桌面/移动端、计划/数据截图 `reports/d10-*.png`。
- 实际模拟链路为浏览器 → 真实 FastAPI/PostgreSQL → 离线 Agent → 人工审批 → 模拟 Gateway/测试执行线程 → HDF5 提交、曲线和下载。3 条命令及 Run 成功结果亦通过 API 核验。断线、冲突和会话撤权浏览器故障注入，后端真实权限/并发验证继续回归。
- 本地浏览器为已有 Chrome for Testing 145.0.7632.6；CI 已配置 Playwright 安装与两套门禁，但远程 CI 和跨浏览器尚未执行。本期未调用付费 LLM 或真实仪器。
- 交接与启动见 `docs/D10_WEB_WORKSPACE_DEVELOPMENT.md`。参数修订通过新提案；暂无任意参数编辑器、逐 token UI、生产 SSO、新鲜设备遥测或常驻部署 worker。Skills/MCP/模型/仪表板等管理页面进入 D11。
- D05–D10 已于 2026-10-19 推送 GitHub `main`（`0015fa6`）；本期临时 PostgreSQL/NATS、Web/API 服务均已关闭，不将测试 fixture 当作常驻产品服务。

## D09 本地交付（2026-10-19）

- FastAPI 契约驱动 HTTP、本地 opaque Bearer token、平台 RBAC/实验资源 ABAC、统一错误/限流已实现。迁移 d09_001 保存 token 摘要、管理配置、加密凭据、请求账本与审计。
- 实验/计划/审批/Run、Agent/Skills/模型/MCP/知识/数据、轨迹与当前主体用量接口已接入；SSE 补发和流中撤权、作用域下载、幂等未知不重放、If-Match 已验证。
- 全套门禁通过：423 项测试（145.89 秒），其中 D09 新增 30 项 API 集成测试；61 个契约操作覆盖无令牌检查。Ruff/格式、生成一致性、13 份 Schema/实例、OpenAPI 与 pip check 全部通过。报告 `reports/d09-validation.txt`。真实 PostgreSQL、回环 HTTP/MCP、HDF5 与离线模型；未调用付费 LLM 或仪器。
- 交接与启动：`docs/D09_API_IDENTITY_DEVELOPMENT.md`。本地令牌不等于企业 OIDC，基本统计不等于完整计费；默认没有 Gateway 网络适配或常驻执行 worker。Web/部署/现场按后续期完成。
- D05–D09 本地变更尚未上传 GitHub，远程 CI 未执行。本期临时 PostgreSQL/NATS 已停止。

## D08 本地交付（2026-10-18）

- MCP 2025-11-25 Streamable HTTP 明确子集、JSON/SSE、固定地址策略、目录发现/人工只读授权/Schema 变化失效、持久调用恢复已实现。
- 版本化知识/记忆、实验/资源/Agent scope 与逐来源 ACL、检索摘录、恢复时撤权复核已实现。
- 已提交 HDF5 的确定性 IV 摘要、Analysis 角色、有证据 Planner 提案、权威数据事件唤醒/冷却/次数预算、跨 Run 相同结构提案去重已实现。
- 迁移 d08_001、knowledge_source/analysis_summary 契约和生成 OpenAPI 已更新。全套门禁通过：393 项测试（112.22 秒），包含新增 45 项专项测试；Ruff/格式、生成一致性、13 份 Schema/实例、OpenAPI 与 pip check 均通过。报告 `reports/d08-validation.txt`。
- 交接：`docs/D08_MCP_KNOWLEDGE_ANALYSIS.md`。使用本地 HTTP MCP 测试服务、真实 PostgreSQL/HDF5 和离线 LLM；不代表公网 MCP、生产身份或真机通过。D05–D08 均未上传 GitHub。本期临时 PostgreSQL/NATS 验收后已停止。

## D07 本地交付（2026-10-18）

- 已实现内部 Planner/Instrument LangGraph 循环、固定配置 bundle、Skill 导入/发布/禁用、上下文预算与多轮工具消息。
- PostgreSQL d07_001 保存注册表、Agent Run/checkpoint、trace、工具 ledger 与 PROPOSED 提案；工具结果/提案与检查点同事务。模型调用前预留，崩溃后不盲重试；不创建硬件命令或审批。
- LangGraph 1.2.16 与完整传递依赖已锁定；shared skill_manifest 契约及生成 OpenAPI 已更新。
- 全套门禁通过：348 项测试（81.32 秒），Ruff/格式、生成一致性、11 份 Schema/实例、OpenAPI、pip check 均通过。比 D06 新增 45 项：38 项真实 PostgreSQL/LangGraph、5 项多轮协议、2 项上下文。报告 `reports/d07-validation.txt`。本期未调用真实 LLM，D06 实联结果不代表本期规划准确率。
- 完整交接和边界：`docs/D07_AGENT_SKILLS_DEVELOPMENT.md`。D05/D06/D07 均未上传 GitHub；本期临时 PostgreSQL/NATS 验收后已停止。

## D06 本地交付（2026-10-18）

- ModelClient/SecretStore、版本绑定连接/模型值对象、能力状态、预算、取消、统一流事件已实现。
- OpenAI/DeepSeek Chat Completions 适配；工具提案仅在完整流与 Schema 校验后交付，不执行工具。JSON 模式采用本地 Schema 验证。
- 离线协议测试 60 项通过；DeepSeek `deepseek-flash` 文本/JSON/工具三个真实合成测试通过，总报告 531 tokens；OpenAI 真实联调未执行。
- 全套门禁通过：303 项测试（60.33 秒），Ruff/格式、135 项转换参考、生成一致性、10 份 Schema/实例、OpenAPI 与 pip check 全部通过。报告 `reports/d06-validation.txt`；真实联调元数据 `reports/d06-deepseek-smoke.json`。本期无新依赖。
- 开发交接：`docs/D06_MODEL_DEVELOPMENT.md`。当前仅官方 HTTPS 端点、内部配置和单轮文本/工具提案；多轮工具结果历史在 D07，配置管理/API 在后续服务期。无 Responses、自定义端点、视觉、生产 Secret Store、货币计费或 Web。
- 用户提供密钥仅用于无回显内存联调，未存入项目文件。D05/D06 均未上传 GitHub。

## D05 本地交付（2026-10-18）

| 工作项 | 状态 | 实现与验证 |
|---|---|---|
| D05-001 正式数据 | 已实现 | HDF5 持久文件、原发放读回快照、Manifest/血缘/审计/outbox 原子提交，幂等与损坏撤回 |
| D05-002 事件恢复 | 已实现 | JetStream ACK、发布 claim/inbox/投影、重复/乱序处理、实验持久游标和完整快照 |
| D05-003 暂停取消 | 已实现 | 有限任务边界暂停、恢复门禁、持久停止确认、未知隔离、迟到命令拦截和完成竞争 |
| 质量门禁 | 本地通过 | reports/d05-validation.txt：243 项测试、10 份 Schema/实例、完整 OpenAPI、Ruff、生成一致性、pip check 全部通过 |

详情：`docs/D05_DATA_RECOVERY_DEVELOPMENT.md`。Linux/Python 3.14.7/PostgreSQL 18.6/NATS 2.15.1；依赖锁新增 h5py 3.16.0、NumPy 2.5.4、nats-py 2.16.0。使用真实数据库、HDF5、JetStream 和独立模拟 journal，不使用内存数据库替代。

相较 D04 的 202 项测试，本期新增 41 项（34 项 PostgreSQL/JetStream/控制/数据集成、6 项存储、1 项事件时间规范化）；以测试报告总数为准。

本期范围：内部应用用例，单机模拟器、IV/HDF5 采集及通知读模型；没有 Web/HTTP/SSE/Agent Runtime、真实 LLM 调用或真机。模拟停止在有限动作边界确认，不代表硬件实时急停。NATS 集群故障切换、长期容量及生产 TLS、Windows、真机门禁仍留给相应后续期。

临时 PostgreSQL：`/tmp/alap-pg18`、`/tmp/alap-d05-postgres`，socket `/tmp/alap-pg18`、55432；NATS：`/tmp/alap-nats15`，127.0.0.1:54222。验收后已停止，不注册系统服务；重建/启动命令见开发说明。

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

P0/P1 基础和 P2 的 D03 数据库/审批、D04 模拟执行部分已建立。P2 数据与事件恢复已在 D05 实现；平台新增功能纳入 P3–P5，当前没有其 UI 或运行服务。

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

- 历史 D03/D04 macOS 路径 `/Users/endsen/codex/ALAP` 为有效 Git 工作树；当前 Linux 环境以顶部交接为准。
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
- 本条为 D03/D04 上传时的历史保存点；当前期见顶部。Windows 与真机验收未完成。
