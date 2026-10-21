# ALAP 实施状态

更新：2026-10-21。本文件区分“已设计”“已实现”“本地验证”“集成/现场验证”。整体平台尚未完成。

## 分期交接入口

- 分期计划：`docs/20_DELIVERY_PLAN.md` 的 D01–D13；P0–P7 为技术层次，D 编号为分批交付单位。
- 当前：**D12 · 集成、部署与验收，进行中**。D01–D11 基础交付完成；本地实现已推送 GitHub `6702ce9`。D12a Gateway 进程边界已完成本地验收；D12b.1 单实例所有权/启动恢复已完成本地验收；D12b.2 独立常驻执行进程已完成本地验收；D12b.3 Agent/outbox worker 与 D12c.1 数据库初始化/权限分离已完成本地验收。D12 整期未完成。
- 当前交接：**D12d.1 常驻部署浏览器与确定性执行已完成本地验收**。下一工作项 D12d.2 常驻 Agent/API 模型链路，之后为 D12d.3 故障矩阵和 D12d.4 实际 24 小时以上模拟。D13 尚未开始，不自动跨期。
- 当前环境：Linux `/home/endsen/ALAP`，Python 3.14.7；工作目录 Git 元数据不可用，最新实现基线为 6702ce92073b20a2382435a7d5fd228469eff110，上传检出为 `/tmp/alap-upload-20261020`，提交前须重新核对远程。依赖按锁文件同步，无新增依赖。D11 下方 macOS 验收为历史记录；本轮 Linux 同步检查见 `reports/local-sync-20261019.md`。
- D05–D10 实现提交 0015fa6 与交接提交 93ab50f 的远程 CI 均已通过，已于 2026-10-19 核对：https://github.com/endsen/ALAP/actions/runs/39201132173 。此结果不替代 D11 的远程验收。

## GitHub 上传交接（2026-10-21，D12c.3 / D12d.1）

- 实现提交 `6702ce92073b20a2382435a7d5fd228469eff110` 已推送到 `endsen/ALAP` 的 `main`，包含 D12c.3 冷备份/隔离恢复与 D12d.1 实际部署浏览器验收，共 39 个变更文件。
- 推送前核对远程仍为 e59baf5，使用普通 fast-forward push，未覆盖远程变更；已扫描提交内容与本机私有凭据，运行时、备份、密钥、令牌和依赖目录未上传。
- 本地验收结果沿用下方对应报告；本条记录保存时尚未确认本次远程 CI 通过，不以本地测试替代远程结果。下方“未推送”描述是各阶段验收时的历史状态，由本条更新。
- 下一工作项仍为 D12d.2 常驻 Agent/API 模型链路，D12d/D12 整体未完成。本条作为实现提交之后的文档交接另行提交。

## D12d.1 · 常驻部署浏览器验收（2026-10-21，本地验收完成）

- 已增加独立 Compose 浏览器入口与未审批测试计划种子，实际使用部署 Web/API/Engine/Gateway/数据卷；不复用 D10 的进程内执行 fixture。
- 首先恢复已退出的本地 rootless Docker；PostgreSQL 旧容器运行状态残留，通过保留数据卷重建容器恢复。未删除业务数据，未注册系统服务。
- 实际 Chromium 经部署 Web/API 完成请求审批、批准、启动 Run、曲线查看和 HDF5 下载，签名与 SHA-256 匹配；常驻 Engine/Gateway 执行三个模拟设备任务。观察者 UI 禁止写入且直接合法审批请求返回 403；刷新清除令牌；SSE 中断禁写、重连恢复。**3 项浏览器测试通过（26.5 秒）**，报告 `reports/d12d1-compose-browser.txt`。
- 最终唯一实验核对 1 SUCCEEDED Run、3 SUCCEEDED Task、3 SUCCEEDED Command、1 COMMITTED Dataset，outbox 未发布数 0，实际镜像与记录见 `reports/d12d1-compose-evidence.json`。四次浏览器调试/验收的执行均完成，未遗留运行中的测试 Run；全部测试观察者 token 已撤销，业务审计与数据保留。
- 首轮观察者种子缺少平台角色及计划资源读取范围，产品正确拒绝快照；另修复重复种子复用创建幂等键。只修测试配置，未放宽产品权限规则；失败记录保留。最终浏览器与后端 403 断言复验通过，详见 `reports/d12d1-acceptance.md`。
- 最终统一后端门禁 **565 项通过（409.28 秒）**，真实 PostgreSQL/NATS 集成不跳过，Ruff/格式、契约/OpenAPI、生成文档及依赖检查通过，报告 `reports/d12d1-backend-validation.txt`。Web 类型/格式检查及 **10 项单元测试**通过；未改 Web 产品代码，复用生产镜像，未重跑 D10/D11 全套 fixture 浏览器测试。
- 本轮安装锁定 Playwright 对应 Chromium 至 `.local-deploy/browsers`，未新增应用依赖或升级锁文件。八个模拟服务恢复运行，仅 Web 发布 127.0.0.1:3000；首页 200、匿名 API 401，QA 端口移除，临时测试数据库/角色为 0，见 `reports/d12d1-final-runtime.json`。未注册系统服务，未推送 GitHub。
- 按 `docs/D12D_ACCEPTANCE.md` 后续进入 D12d.2 常驻 Agent 经本地 HTTP 模型替身形成提案的部署验收，再做 D12d.3 故障矩阵与 D12d.4 实际 24 小时负载。本轮没有调用模型或真机，不把预置计划称为 Agent 生成，不把短测当作长测；D12d/D12 整体未完成。

## D12c.3 · 运维与一致性恢复（2026-10-21，本地验收完成）

- 已实现分卷 AES-256-GCM 加密冷快照、HMAC 完成清单、隔离目标恢复与强制新 epoch；提供真实状态计数、outbox 年龄与恢复/数据异常提示。
- 加密/归档专项 15 项通过。已通过现有应用用例在 `EXP-BACKUP-001` 创建模拟专用审批/Run，三个任务完成、生成一份 COMMITTED HDF5，供非空恢复演练；未调用付费模型或真机。这是显式测试数据，不改变 initialize 不预置审批/Run 的行为。
- 最终统一门禁 **565 项通过（428.72 秒）**，实际 PostgreSQL/JetStream TLS/认证连接；Ruff/格式、状态机、契约/OpenAPI、合订本及依赖检查通过，见 `reports/d12c3-backend-validation.txt`。首轮 565 项通过（439.46 秒）保留为 initial 报告；之后修复实际容器审计问题并完整重跑。
- 非空加密冷快照约 373 MiB，最终备份 21.4 秒，隔离导入/冻结 13.918 秒，对账检查 6.099 秒；单次本机计时不作为 SLA。副本强制新 epoch、冻结全部旧 Run、撤销复制的 3 条 token，所有网络 internal、无发布端口、不运行常驻 Engine/Agent/API/Web/outbox。
- 副本 HDF5 缺失返回 ARTIFACT_INVALID，保持 RECOVERING，Gateway 未启动；复原后校验 1 份 COMMITTED 文件及两个 SQLite，恢复为 ACTIVE。命令/模拟动作均保持 3，数据集保持 1，没有重放或自动 resume。错误密钥在创建目标前拒绝，普通 manage up 拒绝恢复目录。
- 第一轮发现只读卷上 SQLite WAL 审计需要共享内存文件，已修复为停稳 Gateway 后检查私有数据库/WAL 副本，再启动只读对账；重新构建、新备份、新隔离目标重复故障与成功路径均通过。新目录维护锁创建也已修复。证据见 `reports/d12c3-recovery-acceptance.md`、`reports/d12c3-restore-evidence.json`。
- 收尾原模拟八服务运行，仅 Web 发布 127.0.0.1:3000；首页 200、匿名 API 401，QA 端口关闭，临时测试库/角色均 0。两个演练副本已停止，卷/备份/密钥仅留在忽略目录 `.local-deploy/`。环境证据见 `reports/d12c3-final-runtime.json`；未注册开机服务。
- 提供按需 JSON 状态/告警代码，不等于自动告警平台；未实现生产 WAL/PITR、异地托管、实验室 RPO/RTO、PKI 轮换或现场接管。无新增依赖/迁移/公共 API，Web 代码未改，浏览器未重跑。操作边界见 `deploy/simulation/README.md`、ADR-053；D12d/D13 未启动。
- GitHub 上 D12a–D12c.2 提交 `e59baf54e461d894e4937e3d13b02af454e242ce` 已确认存在，远程 CI 成功：https://github.com/endsen/ALAP/actions/runs/39421094109 。本轮 D12c.3 尚未提交/推送。

## D12c.2 · 组件权限与实际容器部署（2026-10-20，本地验收完成）

- 四组件独立登录、表/列白名单、旧 runtime 禁用、仅锁定授权复核与受限 MCP 发现已通过真实 PostgreSQL 验证。组件权限专项 23 项通过；早期统一 544 项见 `reports/d12c2-validation.txt`。
- `deploy/simulation/` 已提供可重复的 prepare/build/initialize/up/token/verify/stop 流程；实际构建后端和 Web 生产镜像，并启动 PostgreSQL、JetStream、Gateway、Engine、Agent、outbox、API、Web 八服务。初始化单独执行，仅创建模拟登记与空实验，不创建审批、执行 Run 或模型凭据。
- 实际验证 PostgreSQL TLS/SCRAM、错误密码及明文拒绝、Gateway mTLS/无客户端证书拒绝、组件 SQL 越权拒绝、只读数据卷、outbox 持久 ACK、Web 首页与认证 API 代理。Gateway/Engine 重启后恢复 ACTIVE；全部服务停止并恢复正常配置后再次验收，数据卷哨兵保留并已清理。
- 最终统一后端门禁 **547 项测试通过（447.69 秒）**，使用实际容器 PostgreSQL/JetStream 的 TLS/认证连接；新增部署材料权限/证书/网络隔离检查，Ruff/格式、生成文档、契约/OpenAPI 和依赖检查通过。报告 `reports/d12c2-compose-backend-validation.txt`。本轮 Web 构建通过，HTTP 接线验证通过，未重跑浏览器交互，完整 UI E2E 留给 D12d。
- 内核重启和显式代理已处理；官方 CloudFront CDN 仍失败时采用用户授权的 DaoCloud 镜像路径，四个固定摘要与官方 registry 一致。Docker 29.9.1 / Compose 5.6.0；容器 Python 3.14.8、Node 24.22.0、PostgreSQL 18.6、NATS 2.15.1。无新增应用依赖，锁文件未升级。
- 本地模拟服务保留运行，只有 Web 发布 `127.0.0.1:3000`；QA 数据库/消息端口已移除，随机测试数据库已清理。私有凭据和运行时在 `.local-deploy/`，不提交；管理员 token 一小时有效，可用 `manage.py token` 续签。未注册开机服务，未调用付费模型或真机，未推送 GitHub。
- 这是 rootless 单机模拟验收，非生产/现场批准；空闲运行数小时不等于实际 24 小时负载验收。下一项 D12c.3 一致性备份/恢复、指标与运维；D12d/D13 尚未完成。证据与操作限制见 `reports/d12c2-compose-acceptance.md`、`deploy/simulation/README.md`、ADR-051/052。

## D12c.1 · 初始化与数据库权限分离（2026-10-20，D12 进行中）

- 新增显式 `python -m alap.adapters.postgres.deployment init|migrate`；仅创建新数据库和独立迁移/runtime 角色，拒绝接管已有库/角色或覆盖已有凭据目录。迁移身份、数据库、schema 与 manifest 校验一致后升级并刷新运行授权；无服务启动隐式迁移。
- 迁移角色拥有 schema；runtime 具备业务 DML/序列/函数权限，没有 DDL、TRUNCATE、TEMP、角色管理、复制模式更改或关闭触发器权限，不能 SET ROLE migrator，alembic_version 只读。应用授权与不可变审计仍生效。
- 生成 0700 目录/0600 连接文件，随机独立密码保存为 SCRAM；拒绝继承管理员 service/options/passfile/客户端证书身份，CLI 不打印 DSN/异常 SQL。API/Agent/Engine/outbox/身份初始化脚本及 Alembic 支持互斥的 ALAP_DATABASE_URL_FILE/ALAP_DATABASE_URL。
- 初始化部分失败不销毁未知资源或覆盖凭据，不完整标记禁止 migrate；管理员需检查恢复。当前 runtime 仍是共享应用数据库信任角色，尚未实现各组件最小表权限或行级隔离，不声称已经完成第 13 章部署权限目标。
- 最终专项 24 项真实 PostgreSQL/配置测试通过，覆盖受限 runtime 下 API/Agent、三设备执行/HDF5/outbox 数据库路径、权限拒绝、管理员身份参数拒绝、迁移连接身份绑定和新函数授权；统一后端门禁 **521 项测试通过（208.54 秒）**，Ruff/格式、135 条状态转换、13 份 Schema/实例、OpenAPI、合订本及 pip check 全部通过。报告 `reports/d12c1-validation.txt`。
- 无新增依赖、业务迁移或公共 HTTP 契约；Web 未改。未安装/启动容器、未调用付费模型或真机、未注册系统服务、未推送 GitHub。本机测试 socket 仍为 trust，只验证角色权限及 SCRAM 保存格式；网络密码认证/TLS 与容器 Secret 由 D12c.2 验证。
- 已确认本轮随机创建的测试数据库与角色全部删除，临时 PostgreSQL/JetStream 已停止；没有部署持久应用数据库或注册生产角色。
- 启动流程、失败处置、D12c 分项顺序和边界见 `docs/D12_INTEGRATION_DEPLOYMENT.md`。D12c.2/3 与 D12d 尚未完成，不跨入 D13。

## D12b.3 · Agent/outbox 常驻 worker（2026-10-19–20，D12 进行中）

- 新增独立 Agent/outbox CLI；Agent 明确实验白名单、专用服务身份、原提交者权限、固定版本与预算，每 Run 每轮一个逻辑步骤，分页绕过繁忙/不可访问记录。API 和后台共享 Agent 装配，worker 没有 Gateway 端口。
- 手动 API、LangGraph、后台推进及取消统一每 Run 会话锁；checkpoint/轨迹/提案通过持锁连接提交，连接丢失不可重新连接提交。模型占位先于调用，遗留 inflight 只标记 MODEL_INTERRUPTED，不自动重发。SIGTERM/SIGINT 停止新受理并收尾当前步骤；模型取消不代表撤回供应商请求。
- outbox 使用现有数据库 claim、稳定 event_id 与持久 ACK，连接故障退避；未确认 claim 过期重领，重复通知由 broker 去重窗口及 inbox 处理。逐次复核服务主体，数据库仍为权威，默认脱敏日志与心跳。
- 专项 Agent/事件/API 回归 83 项通过；新增 11 项 worker 集成测试覆盖真实数据库、离线模型和 JetStream、两个独立 CLI 的恢复/发布/重启/退出。统一后端门禁 **497 项测试通过（204.94 秒）**；Ruff/格式、135 条状态转换、13 份 Schema/实例、OpenAPI、合订本生成一致性及 pip check 全部通过，报告 `reports/d12b3-validation.txt`。
- 首次全量检查 495 通过、2 失败：Gateway 子进程在 10 秒启动等待内未监听；两个用例单独复验通过。测试就绪等待改为有界 30 秒并补充超时日志，设备操作的超时/重试策略未改；原失败报告保留于 `reports/d12b3-validation-initial.txt`，统一门禁重跑已全部通过。
- 无新增依赖、迁移或公共 HTTP 契约；Web 未改，浏览器未重跑。未调用真实付费模型或仪器，未注册系统服务，未推送 GitHub。启动设置、授权/退出语义及限制见 `docs/D12_INTEGRATION_DEPLOYMENT.md`。
- 2026-10-20 已关闭本轮临时 PostgreSQL/JetStream，确认没有遗留 Agent/outbox/引擎/Gateway 测试进程。
- 本工作项不等于完整常驻平台验收；Compose/运维/备份恢复、全链路 E2E 和真实经过 24 小时以上长测尚未完成。下一项 D12c，不跨入 D13。

## D12b.2 · 独立常驻执行进程（2026-10-19，D12 进行中）

- 新增 `python -m alap.adapters.engine.server --config <engine.json>`：专用数据库 owner、网络 Gateway、恢复闸门、确定性串行调度及 HDF5/控制用例装配；仅允许显式 simulation 模式，不创建主体/设备/审批/Run，不调用 LLM。
- 每 Run 每轮最多派发一个依赖满足的任务；复核原有授权/版本/读回与租约，按审批有效期续期，过期隔离；暂停等待用户显式 resume，结束后经 Gateway 核对释放资源。
- 采集写入失败只补交数据，不重采；已有 stop 请求使用原有 ID 确认。SIGTERM/SIGINT 停止新任务并完成已受理操作记录；所有权丢失退出、不重连；强杀重启经过恢复，旧 Run 不自动继续。
- 13 项专项测试通过：真实 PostgreSQL/HDF5、两个独立服务进程经 HTTP 闭环、资源争用、撤权/暂停、续期/过期、数据恢复、取消、正常/强杀退出与所有权丢失。统一后端门禁 **486 项测试通过（225.63 秒）**；Ruff/格式、135 条状态转换、13 份 Schema/实例、OpenAPI、合订本生成一致性及 pip check 全部通过。报告 `reports/d12b2-validation.txt`。
- 没有新增依赖、迁移或公共 API；Web 未改，浏览器门禁未重跑。本轮 PostgreSQL/JetStream 已关闭，测试引擎/Gateway 子进程已清理；没有注册开机服务或推送 GitHub。串行执行暂无专用续租线程，长操作可能导致其它租约过期并拒绝派发；未宣称吞吐或长测通过。
- 启动配置、行为边界及需求证据见 `docs/D12_INTEGRATION_DEPLOYMENT.md`。下一项 D12b.3；Compose/备份恢复/24 小时长测和真机仍未完成。

## D12b.1 · 引擎所有权及恢复政策（2026-10-19，D12 进行中）

- 新增 PostgreSQL 专用会话单实例锁，业务事务使用同一连接；失去连接或锁后永久停用，不自动重连。Gateway 八个操作均在发送前检查所有权；网络期间的竞态仍依赖 epoch/fencing 及恢复屏障。
- 新增启动恢复编排：标记在途未知、查询持久回执、汇总阻塞原因，全部已核对后才绑定新 epoch/开闸；缺 journal、未提交数据、未确认停止不猜测成功，不自动派发、停止或 resume。
- `startup_cancel_unsent_v1` 仅在 RECOVERING 且事务证据证明未发送、其它子项已静止时取消 Run 剩余任务，历史成功项保留，状态/证据/事件同事务；不自动生成新命令尝试。当前仍为服务组件，尚无常驻进程 CLI/调度循环。
- 18 项真实 PostgreSQL 专项测试通过，包含第二进程争锁、连接终止后的八种出站调用拒绝、矛盾证据、并行 UNKNOWN 和数据待提交阻塞。统一后端门禁 **473 项测试通过（207.54 秒）**；Ruff/格式、135 条状态转换、13 份 Schema/实例、OpenAPI、合订本生成一致性与 pip check 全部通过。报告 `reports/d12b1-validation.txt`。
- 无新依赖/迁移/公共 API；Web 未改，浏览器门禁未重跑。本轮 PostgreSQL/JetStream 测试进程已关闭，Gateway 子进程由测试清理；没有注册常驻服务。变更未推送 GitHub。下一步及边界见 `docs/D12_INTEGRATION_DEPLOYMENT.md` 的 D12b.1；不跨入 D13。

## D12a · Gateway 进程边界（2026-10-19，D12 进行中）

- 新增固定 RPC 网络 GatewayPort、独立模拟服务入口及 API 显式网络配置。命令/回执原有签名、审批/租约/epoch/fencing/幂等检查保留；网络层单次发送，不跟随重定向，不自动重试。
- HTTP 限回环地址；非回环监听要求 mTLS。真实 TLS 测试覆盖无客户端证书拒绝和有效证书通过；配置统一采样/请求大小/入站读取时限与并发受理限制。
- 两项真实 PostgreSQL + 独立 Gateway 子进程集成测试已通过：三设备采集与 HDF5 提交、重启后核对；丢响应进入 UNKNOWN，再重启对账到 PAUSED，动作不重复。
- 后端统一门禁通过：**455 项测试（168.54 秒）**，比 D11 新增 16 项；Ruff/格式、135 条状态转换、13 份 Schema/实例、OpenAPI、合订本生成一致性及 pip check 全部通过，报告 `reports/d12a-validation.txt`。本轮未修改 Web、公共 API Schema、数据库迁移或依赖版本；未重跑浏览器门禁，D11 Linux 浏览器证据仍见同步报告。
- 仍缺常驻执行/Agent/outbox 进程、Compose、完整平台可观测性、备份恢复、24 小时以上实际长测；未启动长测，不将短测当整期验收。当前无容器运行时；生产 PKI、Windows 与真机不在本工作项验收范围。
- 当前变更未推送 GitHub。详细启动、需求映射、边界及下一工作项见 `docs/D12_INTEGRATION_DEPLOYMENT.md`；下一步是 D12b 引擎单实例所有权及恢复政策，保持本期进行中。

## D11 本地交付（2026-10-19）

- 平台控制台已接入 Agent、模型、Skills、MCP、知识、仪表板、用量、轨迹、审计与设置页面。版本草稿/校验/发布/禁用/差异、角色及凭据管理、授权/撤销、实验范围统计和原始 Run 下钻可实际操作。
- Agent 受控测试仅产生提案，执行技能仍走审批与确定性引擎。模型合成连接测试由管理员显式确认，固定文本、最多 32 输出 Token/一次尝试/15 秒；开发验收没有真实供应商调用。
- 后端新增 9 个契约操作（共 73 个），版本详情、共享发布校验、工具目录、角色比较变更、系统配置和模型合成测试；无新数据库迁移。用量分组关联原始 Agent Run，未知 Token/费用不补零。
- 后端统一门禁：**439 项测试通过**（新增 9 项管理验收）；Ruff/格式、135 条状态转换参考、13 份 Schema/实例、OpenAPI、文档生成一致性与 pip check 通过。报告 `reports/d11-validation.txt`。
- Web 门禁：类型生成/TypeScript/Prettier、**10 项单元测试、18 项 Chromium 浏览器测试**、生产构建通过。报告 `reports/d11-web-validation.txt`。移动导航修正后重新构建并专项复验通过，见 `reports/d11-mobile-validation.txt`。
- 已查看桌面模型与移动设置截图；Skill/审计和旧工作区回归截图为 `reports/d11-*.png`。D10 历史截图保留不覆盖。测试使用独立控制台实验，保留版本绑定/跨 Run 提案去重，不通过放松安全规则使测试通过。
- 本机：Python 3.14.8、PostgreSQL 18.6、NATS 2.15.1、Node 24.22.0、锁定 Playwright Chromium。按既有锁文件安装依赖，没有新增依赖版本；安装的 Node 24 通过 PATH 显式使用，未切换系统默认 Node。
- 本地集成/浏览器验收已完成；远程 CI 单独记录，不代表跨浏览器、生产部署或真机验收。临时 PostgreSQL/JetStream 与浏览器测试服务验收后停止；没有注册开机服务。
- 详细路由、启动、验证和边界见 `docs/D11_PLATFORM_CONSOLE_DEVELOPMENT.md`。固定指令策略、文本检索、HTTP MCP 子集、当前用户/实验统计等边界如实保留；完整计费、自动保留清理、企业 SSO、常驻部署和现场仍待对应后续工程。

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

P0–P5 的 D01–D11 基础交付已建立，含模型/Agent/管理 API、实验工作区与平台控制台。完整常驻部署、系统级长时间故障验收和现场仍待 D12/D13。

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

## D11 GitHub 交付（2026-10-19）

- 实现提交：`483f23d`（`feat: deliver D11 platform console`），已推送到 `origin/main`。
- GitHub Actions：https://github.com/endsen/ALAP/actions/runs/39265691351 。该实现提交的后端与 Web 门禁均已通过。本记录为随后追加的文档交接，不能将实现提交的 CI 结果等同于交接提交的 CI 结果。
- 本次仅交付 D11；D12 尚未启动。
