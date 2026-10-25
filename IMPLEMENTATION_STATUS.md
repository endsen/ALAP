# ALAP 实施状态

更新：2026-10-25。本文件区分“已设计”“已实现”“本地验证”“集成/现场验证”。整体平台尚未完成。

## 分期交接入口

- 分期计划：`docs/20_DELIVERY_PLAN.md` 的 D01–D13；P0–P7 为技术层次，D 编号为分批交付单位。
- 当前：**D12 · 集成、部署与验收，进行中**。D01–D11 基础交付完成；已推送实现基线为 GitHub `6702ce9`，本轮 D12d.2/3 尚未推送。D12a Gateway 进程边界已完成本地验收；D12b.1 单实例所有权/启动恢复已完成本地验收；D12b.2 独立常驻执行进程已完成本地验收；D12b.3 Agent/outbox worker 与 D12c.1 数据库初始化/权限分离已完成本地验收。D12 整期未完成。
- 当前交接：**D12d.3 故障矩阵进行中**；D12d.2 已完成本地验收。已完成 TCP/NATS、模型 HTTPS 故障、批准后计划变更、独立进程数据故障、部署数据 API/浏览器及独立进程异常读回、写入中断恢复及知识检索/撤权验证；知识撤权终态收尾、受限 API/页面及预置上下文的部署路径已通过；常驻 Agent 实际检索与本地 HTTPS 响应期间的部署知识撤权也已取得证据，完整门禁见下文。D12d.4 实际 24 小时以上模拟未开始。D13 尚未开始，不自动跨期。
- 当前环境：Linux `/home/endsen/ALAP`，Python 3.14.7；工作目录 Git 元数据不可用，最新实现基线为 6702ce92073b20a2382435a7d5fd228469eff110，上传检出为 `/tmp/alap-upload-20261020`，提交前须重新核对远程。依赖按锁文件同步，无新增依赖。D11 下方 macOS 验收为历史记录；本轮 Linux 同步检查见 `reports/local-sync-20261019.md`。
- D05–D10 实现提交 0015fa6 与交接提交 93ab50f 的远程 CI 均已通过，已于 2026-10-19 核对：https://github.com/endsen/ALAP/actions/runs/39201132173 。此结果不替代 D11 的远程验收。

## GitHub 上传交接（2026-10-21，D12c.3 / D12d.1）

- 实现提交 `6702ce92073b20a2382435a7d5fd228469eff110` 已推送到 `endsen/ALAP` 的 `main`，包含 D12c.3 冷备份/隔离恢复与 D12d.1 实际部署浏览器验收，共 39 个变更文件。
- 推送前核对远程仍为 e59baf5，使用普通 fast-forward push，未覆盖远程变更；已扫描提交内容与本机私有凭据，运行时、备份、密钥、令牌和依赖目录未上传。
- 本地验收结果沿用下方对应报告；本条记录保存时尚未确认本次远程 CI 通过，不以本地测试替代远程结果。下方“未推送”描述是各阶段验收时的历史状态，由本条更新。
- 下一工作项仍为 D12d.2 常驻 Agent/API 模型链路，D12d/D12 整体未完成。本条作为实现提交之后的文档交接另行提交。

## D12d.3 · 故障矩阵（2026-10-22，进行中）

- 第二十四批（2026-10-25，本地部署验收完成）：加密冷备份后部署后端 a7a87199（Web fd41b31a 保持），d12_002 无迁移、原有命令 45/数据 15 保持。非管理员 operator 的两供应商调用前成员撤权/真实 HTTPS 响应期间成员撤权或范围缩减共 **6 项部署案例通过**；FAILED/ACCESS_REVOKED、请求数 0/1/1，未提交工具/提案/执行写入 0，重授权并重启无重放。完整后端 **638 项通过（652.42 秒）**，真实 PostgreSQL/NATS 及格式/契约/生成/依赖检查通过。收尾八服务 ACTIVE、新镜像一致、测试库/角色/token/启用测试配置及身份/成员权限/活动运行/待确认取消/待发布事件均为 0，命令保持 45、15 份文件校验通过，QA 端口和隔离模型网络移除。见 `reports/d12d3-access-deploy-backend-validation.txt`、`reports/d12d3-access-deploy-final-runtime.json` 和 `reports/d12d3-access-deploy-acceptance.md`。

- 第二十三批（2026-10-25，本地源码/集成验收完成）：修复提交人主体禁用/成员撤权/设备范围缩减后的 READY/RUNNING 滞留；持原执行所有权、当前权限复核后受限 FAILED/ACCESS_REVOKED 收尾，保留历史/预算，拒绝访问且不发布未提交结果。首轮 10 失败/2 通过复现缺口；修复后关联专项 **68 项通过（95.89 秒）**。追加提案提交竞态、审计回滚、连接丢失及撤权后恢复测试后，完整后端 **638 项通过（609.75 秒）**，含新增 19 项；真实 PostgreSQL/NATS、格式/契约/生成/依赖检查通过。收尾八服务 ACTIVE、测试库/角色/token/活动运行/待确认取消/待发布事件及测试身份权限均为 0，命令保持 45、15 份文件校验通过，QA 端口和隔离模型网络移除；见 `reports/d12d3-access-revocation-backend-validation.txt`、`reports/d12d3-access-revocation-final-runtime.json`。见 `reports/d12d3-access-revocation-acceptance.md`。尚未更新部署镜像。

- 第二十二批（2026-10-25，本地部署验收完成）：两供应商各 49 项，共 **98 项部署 HTTP 权限断言通过**。同实验非提交人的运行详情/轨迹/提案及取消/推进拒绝；列表和用量只含自身运行；实验外/匿名拒绝；通过 API 撤销成员权限后列表/用量/仪表板立即拒绝。提交人状态/轨迹/提案保持，执行写入 0；完整后端 **619 项通过（568.63 秒）**，真实 PostgreSQL/NATS 集成及格式/契约/生成/依赖检查通过。收尾八服务 ACTIVE、测试库/角色/token/活动运行/待发布事件/启用测试身份和成员权限均为 0，命令保持 45、15 份文件校验通过，QA 端口与隔离模型网络移除；见 `reports/d12d3-permissions-backend-validation.txt`、`reports/d12d3-permissions-final-runtime.json` 和 `reports/d12d3-permissions-acceptance.md`。不含运行中提交人撤权、MCP 或完整角色/字段矩阵。

- 第二十一批（2026-10-25，本地部署验收完成）：两供应商模型工具请求已提交/只读工具结果已提交两个位置 SIGKILL 后恢复共 **4 项部署案例通过**。每项仅两次 HTTPS、一次 read_snapshot/一次未审批提案，第二次重启状态/轨迹/ledger/提案不变，计划/审批/设备执行写入 0。完整后端 **619 项通过（568.43 秒）**，真实 PostgreSQL/NATS 集成及格式/契约/生成/依赖检查通过。收尾八服务 ACTIVE、d12_002/镜像一致；测试库/角色/token/启用测试配置/活动运行/待确认取消/待发布事件均为 0，命令保持 45、15 份文件校验通过，QA 端口及隔离模型网络移除。见 `reports/d12d3-tool-recovery-backend-validation.txt`、`reports/d12d3-tool-recovery-final-runtime.json` 与 `reports/d12d3-tool-recovery-acceptance.md`；不包含 MCP 外部调用恢复。

- 第二十批（2026-10-25，本地部署验收完成）：两供应商模型能力新版本/旧模型禁用/Skill 新版本共 **6 项部署验证通过**。同版覆盖拒绝，新版不支持工具则新 Agent 发布拒绝；旧运行保持 bundle/hash，Skill 实际上下文仍为旧标记；禁用旧模型后不自动切换可用新版、请求 0。工具/执行写入 0。模型专项 **85 项通过**；完整后端 **619 项通过（579.45 秒）**，真实 PostgreSQL/NATS 集成及格式/契约/生成/依赖检查通过。最终八服务 ACTIVE、d12_002/镜像一致，测试库/角色/token/启用测试配置（含 v2）/活动运行/待确认取消/待发布事件均为 0，命令保持 45、15 份文件校验通过，QA 端口移除。见 `reports/d12d3-version-binding-backend-validation.txt`、`reports/d12d3-version-binding-final-runtime.json`；见 `reports/d12d3-version-binding-acceptance.md`。

- 第十九批（2026-10-24 验证，2026-10-25 续接收尾完成）：两供应商首次 429 后成功/累计预留不足停止重试/调用前预算不足共 **6 项实际部署案例通过**。请求数分别 2/1/0，成功用量只计一份、重复读取和 worker 重启不重复统计/调用，工具/执行写入 0。模型专项 **83 项通过**；完整后端 **617 项通过（573.84 秒）**，真实 PostgreSQL/NATS 集成及格式/契约/生成/依赖检查通过。最终八服务 ACTIVE、d12_002/镜像一致，测试库/角色/token/启用测试配置/活动运行/待确认取消/待发布事件均为 0，命令保持 45、15 份文件校验通过，QA 端口移除。见 `reports/d12d3-retry-budget-backend-validation.txt`、`reports/d12d3-retry-budget-final-runtime.json`。见 `reports/d12d3-retry-budget-acceptance.md`；预留与替身 usage 不等同供应商账单。

- 第十八批（2026-10-24，本地部署验收完成）：两供应商取消请求后/无取消对照的 HTTPS 调用期间 SIGKILL + 重启共 **4 项部署案例通过**；退出码 137/非 OOM，停机时仍 RUNNING，重启分别 CANCELLED/FAILED(MODEL_INTERRUPTED)，每项 HTTPS 请求 1、预算保留、工具/执行写入 0。再次重启状态/轨迹不变，见 `reports/d12d3-agent-crash-evidence.json`。完整后端 **615 项通过（579.66 秒）**，真实 PostgreSQL/NATS 集成及格式/契约/生成/依赖检查通过。最终八服务 ACTIVE、d12_002/镜像一致，测试库/角色/token/启用测试配置/活动运行/待确认取消/待发布事件均为 0，命令保持 45、15 份文件校验通过，QA 端口移除。见 `reports/d12d3-agent-crash-backend-validation.txt`、`reports/d12d3-agent-crash-final-runtime.json`，完整范围见 `reports/d12d3-agent-crash-acceptance.md`。

- 第十七批（2026-10-24，本地部署验收完成）：加密冷备份后构建并启动新镜像，显式迁移 d12_001→d12_002，原有命令 45/数据文件 15 保持。两供应商调用前/API 运行中/真实浏览器运行中取消共 **6 项部署验收通过**；待确认 RUNNING、确认后 CANCELLED、无工具/提案/执行写入，两个 Chromium 用例通过（6.1 秒/5.5 秒）。模型专项 81 项通过；完整后端 **615 项通过（566.16 秒）**，真实 PostgreSQL/NATS、格式/契约/生成/依赖检查通过。最终八服务 ACTIVE、d12_002/新镜像一致，测试库/角色/token/启用测试配置/活动运行/待确认取消/待发布事件均为 0，命令保持 45、15 份文件校验通过，QA 端口移除。见 `reports/d12d3-cancel-deploy-backend-validation.txt`、`reports/d12d3-cancel-deploy-final-runtime.json`。见 `reports/d12d3-cancel-deploy-acceptance.md`；此前“未部署”为历史状态，本批新能力已部署，整期 D12 未完成。

- 第十六批（2026-10-24，本地源码/集成验收完成）：已编码 d12_002 取消意图迁移、运行中请求持久化、worker/提交边界确认、API cancel_requested 及 Web 待确认显示。真实数据库/API 专项 **12 项通过（15.54 秒）**，见 `reports/d12d3-cancel-intent-targeted-rerun.txt`；首次触发器约束冲突失败记录保留。完整后端 **615 项通过（570.42 秒）**，真实 PostgreSQL/NATS 未跳过，迁移往返/权限/格式/契约/生成/依赖检查通过；Web **10 项单元、20 项 fixture 浏览器（1.3 分钟）**及类型/构建通过。收尾八服务 ACTIVE、首页 200/匿名 API 401，测试库/角色/token/活动运行/待发布事件均为 0，命令保持 45、15 份文件校验通过，QA 端口移除。报告 `reports/d12d3-cancel-intent-backend-rerun.txt`、`reports/d12d3-cancel-intent-web-validation.txt`、`reports/d12d3-cancel-intent-final-runtime.json`。常规 Compose 仍为旧镜像/旧数据库版本，尚未部署该能力。完整范围见 `reports/d12d3-cancel-intent-acceptance.md`。

- 第十五批（2026-10-24）：两供应商调用前取消/调用中取消边界共 **4 项部署验证通过**。调用前 CANCELLED、请求 0、重启不重放；调用中返回 409 RUN_BUSY、状态仍 RUNNING，随后模型超时 FAILED，请求 1。终态再次取消不改状态/轨迹，执行写入为 0。**未实现运行中取消请求机制**；完整后端 **604 项通过（549.73 秒）**，真实 PostgreSQL/NATS 集成及格式/契约/生成/依赖检查通过；收尾八服务 ACTIVE、首页 200/匿名 API 401，测试库/角色/token/启用测试配置/活动运行/待发布事件为 0，命令保持 45、15 份文件校验通过，QA 端口和隔离模型网络移除。门禁与收尾见 `reports/d12d3-cancellation-api-backend-validation.txt`、`reports/d12d3-cancellation-api-final-runtime.json`，详见 `reports/d12d3-cancellation-api-acceptance.md`。

- 第十四批（2026-10-24）：两供应商 max_attempts=3 下连续 429/部分 SSE 后超时，**4 项实际 HTTPS 部署验证通过**，请求次数分别为 3/1，FAILED/MODEL_FAILURE、无工具/设备写入。专项 **81 项通过**；完整后端 **604 项通过（545.98 秒）**，真实 PostgreSQL/NATS 集成及格式/契约/生成/依赖检查通过。收尾八服务 ACTIVE、首页 200/匿名 API 401；测试库/角色/token/启用测试配置/活动运行/待发布事件为 0，命令保持 45、15 份文件校验通过，QA 端口和隔离模型网络移除。见 `reports/d12d3-retry-https-backend-validation.txt`、`reports/d12d3-retry-https-final-runtime.json`。见 `reports/d12d3-retry-https-acceptance.md`，取消 API 的独占锁语义仍需单独验证，不把客户端 Event 取消测试算作部署证据。

- 第十三批（2026-10-24）：两供应商各三种非法 usage 与部分 SSE 后真实读超时，**8 项隔离 HTTPS 部署案例通过**，FAILED/MODEL_FAILURE、预算预留保留、每项一次 HTTPS 请求、无工具/提案/设备写入。替身及模型专项 **81 项通过**；完整后端 **604 项通过（541.73 秒）**，真实 PostgreSQL/NATS 集成及格式/契约/生成/依赖检查通过；最终八服务 ACTIVE、首页 200/匿名 API 401，测试库/角色/token/启用测试配置/活动运行/待发布事件均为 0，命令保持 45、15 份文件校验通过，QA 端口与隔离模型网络移除。完整门禁及收尾见 `reports/d12d3-streaming-https-backend-validation.txt`、`reports/d12d3-streaming-https-final-runtime.json`。入口 `deploy/simulation/check_streaming_faults.py`，证据 `reports/d12d3-streaming-https-evidence.json`，范围见 `reports/d12d3-streaming-https-acceptance.md`；超时 profile=2s/max_attempts=1，取消与其他重试/权限矩阵仍待补。

- 已建立 `docs/D12D_FAULT_MATRIX.md`，逐项映射 EVAL-01–24 的 U/I/P/C/F 证据层级、已有测试、未覆盖场景与恢复边界；引用路径/函数及 24 项完整性已核对。没有把 fixture 提升为部署/现场证据。
- 新增独立 Engine/Gateway + loopback HTTP proxy 的真实 TCP 故障专项：转发前切断时动作 0、UNKNOWN 冻结，重启保持 RECOVERING；执行后丢弃响应时动作 1、UNKNOWN 冻结，同 payload 重送无重复动作，重启对账后 PAUSED，无自动 resume。**2 项通过（18.70 秒）**，见 `reports/d12d3-wire-faults.txt`。这是 P 级证据，不是 Compose mTLS/真机 ACK 故障。
- 实际 Compose NATS 停服/恢复演练通过：停服后两条 outbox 事件保持待发布，API snapshot 游标 2、无审批/Run；恢复后待发布 0，JetStream 564→566；重启 outbox 后无重复消息，设备命令保持 30，增量 0。测试令牌已撤销，业务记录保留，见 `reports/d12d3-messaging-evidence.json`。
- 统一后端门禁 **574 项通过（437.62 秒）**，真实 PostgreSQL/NATS 集成未跳过，Ruff/格式、契约/OpenAPI、合订本及依赖检查通过，报告 `reports/d12d3-backend-validation.txt`。本轮无产品业务代码、Web、依赖/迁移/公共 API 变更，不重复 Web 浏览器门禁，沿用 D12d.2 的 18 项 fixture 与部署结果。
- 收尾八服务恢复运行、控制模式 ACTIVE；仅 Web 发布 127.0.0.1:3000，首页 200、匿名 API 401。测试数据库/角色、有效 token、活动 Run、outbox 待发布均为 0，部署命令总数保持 30，QA 端口已移除；见 `reports/d12d3-final-runtime.json`。未注册系统服务，完整首批报告见 `reports/d12d3-acceptance.md`。
- 实现审查确认 EVAL-09 边缘失联监护尚无独立实现；EVAL-14 尚缺同 CA 错误身份与资源映射验证，现有签名 gateway_id 及 mTLS 链验证不能冒充该项完成。其余运行期负路径缺口见矩阵。**D12d.3 尚未完成，不进入 D12d.4 或 D13。**
- 第二批实际 HTTPS 模型故障已通过：OpenAI/DeepSeek 各六种模式，共 **12 项**，包括越权工具、截断 SSE、429、缺失 usage、禁用凭据、第二次模型响应期间禁用 Skill。除缺失 usage 外均 FAILED；未知 usage 保留 null/API 未知次数 2，只产生未审批提案；撤权轨迹 SKILL_DISABLED。12 个实验的计划、审批、执行 Run、Task、Command、Dataset 写入均为 0。证据 `reports/d12d3-model-faults.json`。目标指令/模型越权响应不等同检索文献注入，官方线上 API 未调用。
- 共享入口正常浏览器回归 **2 项通过（54.2 秒）**，人工审批后三任务执行及 HDF5 校验成功；见 `reports/d12d3-model-normal-agent.txt` 与 `reports/d12d3-model-normal-evidence.json`。新增故障入口及清理逻辑；首次测试给无 body 的禁用接口传 `{}` 导致 422，修正测试后全部重跑通过，未放宽业务契约。
- 第二批统一后端门禁 **574 项通过（429.64 秒）**，真实 PostgreSQL/NATS 集成未跳过，其余格式/契约/生成/依赖检查通过；见 `reports/d12d3-model-backend-validation.txt`。最终八服务 ACTIVE、首页 200/匿名 API 401，仅 Web 发布端口，测试库/角色、有效 token、启用测试配置、活动 AgentRun/Run、待发布事件均为 0；命令总数 36（正常回归新增 6），QA 端口/隔离模型网络已移除。收尾报告 `reports/d12d3-model-final-runtime.json`；完整过程与启动瞬态记录见 `reports/d12d3-model-acceptance.md`。
- 第三批“批准后、启动前改计划”的部署 API 验证已通过：温度目标/读回条件 295→296 K，新 hash 与旧版不同，旧审批 SUPERSEDED；旧快照启动为 409 STATE_CONFLICT，最新快照复用旧审批为 409 PLAN_STALE。常驻 Engine 保持运行，Run/Task/Command/Dataset 新增均为 0，全局命令保持 36；证据 `reports/d12d3-plan-evidence.json`，入口 `deploy/simulation/check_plan_fault.py`。已有 Run 冻结与策略变化仍只有 I 级证据，不能提升为部署验收。
- 第三批统一门禁 **574 项通过（435.08 秒）**，真实 PostgreSQL/NATS 集成与格式/契约/生成/依赖检查通过，报告 `reports/d12d3-plan-backend-validation.txt`。最终八服务 ACTIVE、首页 200/匿名 API 401；测试库/角色、有效 token、活动运行及待发布事件为 0，命令仍为 36，QA 端口已关闭；见 `reports/d12d3-plan-final-runtime.json`、`reports/d12d3-plan-acceptance.md`。
- 第四批独立进程数据故障专项 **2 项通过（29.28 秒）**，真实存储路径错误导致 STAGING/VERIFYING、无 manifest/provenance，读取拒绝；恢复后常驻 Engine 提交唯一 HDF5/来源/事件，每条命令模拟动作一次。已提交文件缺失/损坏时读取拒绝，恢复原始字节并重启 Engine 后无重复采集。见 `tests/integration/test_data_process_faults.py`、`reports/d12d3-data-process.txt`。P 级执行/存储与 I 级读取证据分开，不称为 Compose 页面禁用验收；原始字节恢复仅用于测试清理。
- 第四批完整后端门禁 **576 项通过（448.39 秒）**，真实 PostgreSQL/NATS 集成未跳过，格式/契约/生成/依赖检查通过，见 `reports/d12d3-data-backend-validation.txt`。最终八服务 ACTIVE，首页 200/匿名 API 401；测试库/角色、有效 token、活动运行及待发布事件为 0，设备命令仍为 36，QA 端口关闭；见 `reports/d12d3-data-final-runtime.json` 与 `reports/d12d3-data-acceptance.md`。
- 第五批部署数据 API 验证通过：新实验经正式 API 审批、三任务采集后，对其唯一文件注入缺失/损坏；清单、下载、曲线三个接口均返回 422 ARTIFACT_INVALID，共六次拒绝断言。恢复后的 SHA-256/清单/曲线与正常结果一致，数据库 manifest 不改；故障命令增量 0，全局命令 36→39 仅来自正常采集。见 `reports/d12d3-data-api-evidence.json`、`deploy/simulation/check_data_fault.py`。读取时拒绝已取得 C 级证据，后台自动检测、CORRUPT 转换和浏览器异常状态仍待验证。
- 第五批完整门禁 **576 项通过（445.92 秒）**，真实 PostgreSQL/NATS 集成及格式/契约/生成/依赖检查通过，见 `reports/d12d3-data-api-backend-validation.txt`。最终八服务 ACTIVE、首页 200/匿名 API 401；测试库/角色、有效 token、活动运行及待发布事件为 0，命令总数 39，文件校验和恢复且临时备份已删除，QA 端口关闭。见 `reports/d12d3-data-api-final-runtime.json`、`reports/d12d3-data-api-acceptance.md`。
- 第六批实际 Chromium 数据故障/恢复 **2 项通过（4.0 秒 / 3.8 秒）**：缺失/损坏文件时首次加载页面，明确完整性错误、下载禁用、无曲线；恢复文件后在同页重试，曲线/下载恢复且 SHA-256 一致。修正 ARTIFACT_INVALID 误导性的通用输入校验提示；已构建更新 Web 镜像。入口 `check_data_browser.py`，证据 `reports/d12d3-data-browser-evidence.json` 及两份浏览器报告。首轮测试定位误匹配 Next.js 隐藏 alert，修正定位后通过；两次正常采集合计六条命令（39→45），故障增量 0。未覆盖已打开页面后台损坏后的即时缓存失效。
- 第六批完整后端 **576 项通过（465.37 秒）**，Web 类型/格式/契约类型/生产构建、**10 项单元和 18 项 fixture 浏览器测试（1.1 分钟）**通过；见 `reports/d12d3-data-browser-backend-validation.txt`、`reports/d12d3-data-browser-web-validation.txt`。收尾八服务 ACTIVE、首页 200/匿名 API 401、测试库/角色/token/活动运行/待发布事件均为 0，命令 45；全部 15 份 COMMITTED 文件校验通过、无临时备份、QA 端口关闭。QA 切换曾出现 PostgreSQL 端口映射为空，保留卷重建后恢复；完整过程见 `reports/d12d3-data-browser-acceptance.md` 与 final-runtime 报告。
- 第七批独立进程读回故障专项 **3 项通过（34.58 秒）**：过期、不稳定、零磁场目标错误读回分别返回 READBACK_STALE/UNSTABLE/INVALID，至少三次异常响应期间后继不派发；恢复正常观测后完成三个任务，每条动作一次、一份 COMMITTED Dataset、资源释放。见 `tests/integration/test_telemetry_process_faults.py`、`reports/d12d3-telemetry-process.txt`。HTTP 代理使用隔离测试密钥重签观测，属于 P 级来源合法的传感读回故障，不是认证攻击/Compose mTLS/现场证据。
- 第七批完整后端门禁 **579 项通过（503.63 秒）**，真实 PostgreSQL/NATS 集成未跳过，Ruff/格式、契约/OpenAPI、生成文档与依赖检查通过；见 `reports/d12d3-telemetry-backend-validation.txt`。收尾八服务恢复、控制模式 ACTIVE、首页 200/匿名 API 401；测试库/角色/token/活动运行/待发布事件均为 0，命令保持 45，15 份 COMMITTED 文件校验通过，QA 端口及隔离模型网络已移除。完整记录见 `reports/d12d3-telemetry-acceptance.md`、`reports/d12d3-telemetry-final-runtime.json`。
- 第八批活动写入发布边界进程中断专项初验 **2 项通过（24.67 秒）**：临时文件 fsync 前、最终链接后目录 fsync 前由测试钩子定位并 SIGKILL，STAGING 不可读；正常重启后提交同一 Dataset、来源/事件各一、三条命令动作各一次、资源释放。见 `tests/integration/test_upload_process_faults.py` 与 `reports/d12d3-upload-acceptance.md`。P 级证据，非断电/字节写入中途/Compose 证据；孤儿临时文件自动回收尚未实现。完整后端 **581 项通过（524.74 秒）**，真实 PostgreSQL/NATS 集成及格式/契约/生成/依赖检查通过，包含追加的既有文件 inode 不变断言；见 `reports/d12d3-upload-backend-validation.txt`。收尾八服务 ACTIVE、首页 200/匿名 API 401，测试库/角色/token/活动运行/待发布事件为 0，命令保持 45，15 份文件校验通过，QA 端口已移除；见 `reports/d12d3-upload-final-runtime.json`。
- 第九批知识检索/撤权专项 **4 项通过（9.53 秒）**：独立 fork AgentWorker + 真实 PostgreSQL + 子进程离线模型，检索内容保持 tool/不可信标签；越权调用 TOOL_FORBIDDEN，调用前及响应期间撤权 SOURCE_REVOKED，零提案/设备执行写入、后续无模型重放。不是 HTTPS/Compose 证据。发现撤权后运行保持 RUNNING、无终态收尾；详见 `reports/d12d3-knowledge-acceptance.md`。完整后端 **585 项通过（536.46 秒）**，真实 PostgreSQL/NATS 集成及格式/契约/生成/依赖检查通过，见 `reports/d12d3-knowledge-backend-validation.txt`。2026-10-22 恢复部署被自动审批服务额度中断，2026-10-23 正常重试完成；最终八服务 ACTIVE、首页 200/匿名 API 401，测试库/角色/token/活动运行/待发布事件均为 0，命令保持 45，15 份文件校验通过，QA 端口移除，见 `reports/d12d3-knowledge-final-runtime.json`。这不代表测试中发现的撤权 RUNNING 缺口已修复。
- 第十批已实现知识来源撤权的受限 FAILED 收尾：持有原所有权会话、复核提交人/范围/bundle/来源撤权，CAS 更新与 blocked 审计同事务；来源引用、历史、预留保留，读取仍拒绝，不重放模型。首轮专项与资源权限回归 **41 项通过（79.59 秒）**；追加提交人撤权和重新授权不重放断言后，完整后端 **593 项通过（560.30 秒）**，真实 PostgreSQL/NATS 集成和格式/契约/生成/依赖检查通过，见 `reports/d12d3-revocation-closure-backend-validation.txt`。最终八服务 ACTIVE、首页 200/匿名 API 401；测试库/角色/token/活动运行/待发布事件均为 0，部署命令保持 45，15 份 COMMITTED 文件校验通过，QA 端口和隔离模型网络已移除。见 `reports/d12d3-revocation-closure-final-runtime.json`；此为既有镜像环境核对，不代表修复已部署。见 `reports/d12d3-revocation-closure-acceptance.md`。尚未更新部署镜像或实现撤权后的 API/页面最小状态呈现，不把旧镜像健康检查称为新代码部署验收。
- 第十一批已编码撤权状态投影及 Web 隐藏缓存/禁用动作；详情/列表仅向仍有实验权限的原提交人返回最小状态，真实状态不被读取操作篡改，历史/提案保持拒绝。HTTP 专项 **2 项通过（6.11 秒）**；完整后端 **595 项通过（549.94 秒）**；完整 Web 类型/格式/契约类型/构建、**10 项单元及 19 项浏览器测试（1.2 分钟）**通过。此前并行构建/门禁导致数据库超时，改为串行重跑通过；状态徽标定位已修正为现有 title，未放宽权限检查。新后端/Web 镜像部署后实际 Chromium **1 项通过（5.4 秒）**，预置来源上下文的 READY → 独立 worker 单次 tick → FAILED，零模型/提案/设备写入；非真实检索/响应期间撤权。见 `reports/d12d3-revocation-view-acceptance.md` 及 evidence/browser 报告。最终八服务 ACTIVE，首页 200/匿名 API 401；测试库/角色/token/启用测试配置/活动运行/待发布事件均为 0，部署命令保持 45，15 份 COMMITTED 文件校验通过。QA 端口及隔离模型网络已移除，测试令牌已撤销；见 `reports/d12d3-revocation-view-final-runtime.json`。
- 第十二批实际检索/HTTPS 知识故障 **6 项部署场景通过**：OpenAI/DeepSeek 各正常对照、文献诱导越权、第二轮响应期间撤权。常驻 Agent 真实 search_knowledge 后将文献送入 HTTPS 上下文，每项两次请求，来源/hash 对账一致；对照 COMPLETED，越权在模型适配器被拒（MODEL_FAILURE），撤权收尾 FAILED/SOURCE_REVOKED，无模型重放，零提案/审批/设备执行写入。协议替身 **13 项单元通过**；完整后端 **601 项通过（556.80 秒）**，真实 PostgreSQL/NATS 集成未跳过，Ruff/格式、生命周期参考、合订本、OpenAPI/契约与依赖检查通过；见 `reports/d12d3-knowledge-https-backend-validation.txt`。最终八服务运行、控制模式 ACTIVE；首页 200/匿名 API 401。测试库/角色/token/启用测试配置/活动运行/待发布事件均为 0，部署命令保持 45，15 份 COMMITTED 文件校验通过；QA 端口与隔离模型网络已移除。见 `reports/d12d3-knowledge-https-final-runtime.json`。见 `reports/d12d3-knowledge-https-acceptance.md` 及 evidence/run 报告。仅本地 TLS 替身，不代表线上模型抗注入质量；无产品/契约/Web/依赖变化。
- 后续补剩余模型异常组合及运行期权限矩阵，并处理边缘失联监护及证书身份映射缺口。D12d.2/3 新增本地内容均未推送 GitHub。

## D12d.2 · 常驻 Agent/API 模型链路（2026-10-21，本地验收完成）

- 已实现隔离 TLS/SSE 本地供应商替身和独立 Agent worker 验收入口；使用真实 ChatModelClient/HTTPSChatTransport，保留官方 HTTPS 白名单与正常 worker 的实验范围。测试 worker 无 egress，只有两个 internal 网络，使用固定无效测试凭据，无付费模型/真机调用。
- 两种供应商格式均通过实际部署浏览器链：页面提交目标、后台 worker 两轮模型/工具往返生成提案、人工审批、常驻 Engine/Gateway 三任务执行、HDF5 下载校验。最终 **2 项通过（55.3 秒）**；无 `/advance` 调用，越出 Agent 实验范围请求返回 403。两个实验各 1 提案/1 成功 Run/3 成功 Command/1 COMMITTED Dataset，outbox 待发布 0；审批/执行审计在提案完成前为 0。见 `reports/d12d2-compose-evidence.json`。
- Web 新增运行中 Agent 状态轮询、终态读取提案/轨迹，解决常驻 worker 已完成而当前页面不更新的问题；手动推进期间暂停轮询，错误停轮询、卸载清定时器。原确定性部署/观察者/SSE 回归 **3 项通过（24.6 秒）**，见 `reports/d12d2-compose-browser-regression.txt`。
- 协议替身专项 **7 项通过**；统一后端门禁 **572 项通过（430.63 秒）**，真实 PostgreSQL/NATS 集成不跳过，Ruff/格式、生成文档、契约/OpenAPI、依赖检查通过。完整 Web 门禁通过类型/格式/契约类型/生产构建、**10 项单元测试、18 项浏览器测试（1.2 分钟）**。报告 `reports/d12d2-backend-validation.txt`、`reports/d12d2-web-validation.txt`；后者使用隔离数据库和进程内模拟 fixture，与前述真实 Compose 验收分开记录。
- 已重建 Web 镜像；无新增依赖、迁移、公共 API 或后端业务代码变更。最终恢复八服务运行、控制模式 ACTIVE，仅 Web 发布 127.0.0.1:3000，首页 200、匿名 API 401；QA 端口已关闭，测试数据库/角色、有效测试凭据/配置/Agent、有效 token、未完成测试 AgentRun 均为 0，测试网络已删除。见 `reports/d12d2-final-runtime.json`。未注册系统服务。
- 下一动作：按 `docs/D12D_ACCEPTANCE.md` 开始 D12d.3，先逐项建立 EVAL-02–24 证据层级与缺口，再补实际跨进程故障注入；不将当前短测计作 D12d.4 的 24 小时负载。续接先重新检查本机 Docker/Compose 运行状态。
- 本地新增实现尚未推送。上个实现 `6702ce9` 与交接 `6f7f5d0` 的 GitHub CI 已确认成功：[实现 CI](https://github.com/endsen/ALAP/actions/runs/39552320479) / [交接 CI](https://github.com/endsen/ALAP/actions/runs/39552387294)；不能替代本轮新代码 CI。
- 后续仍为 D12d.3 故障矩阵、D12d.4 实际 24 小时以上模拟；D12d/D12 整体与 D13 现场未完成。具体范围、调试记录及模型替身局限见 `reports/d12d2-acceptance.md`、`docs/D12D_ACCEPTANCE.md`。

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
