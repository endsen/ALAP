# ALAP 项目协作指引

## 当前基线

- 开发以 `docs/01–22` 和生成的 `ALAP_Engineering_Design_v3.1_完整合订本.md` 为准；原始 v3.0 合订本和 ZIP 保留不改。
- 用户明确要求：专用实验 Agent 平台；经 API 接入 LLM，支持主流供应商，首批 OpenAI/DeepSeek；Web 包含独立 Skills、MCP、模型、仪表板、用量、轨迹与知识管理。
- 按专业工程顺序分层实现，不追求快速演示。实施顺序以 `docs/20_DELIVERY_PLAN.md` 为准，实际完成项见 `IMPLEMENTATION_STATUS.md`。
- 额度限制下按 D01–D13 分期交付，区别于技术层 P0–P7。每期可跨会话；每期结束保存完成项、验证、遗留问题和下一动作。先读状态再续做，默认不在当期交接后自行跨期。不要假定能读取用户账户剩余额度。
- 已有 D03–D09 数据库/执行/数据、模型/Agent/Skills/MCP/知识及可启动 HTTP API；本期验收见状态文件，D10 实验工作区与 D11 平台控制台已完成本地验收，D12c.2/3 已完成 rootless 单机模拟部署及加密冷备份/隔离恢复本地验收；D12d.1 常驻浏览器确定性链路与 D12d.2 本地 TLS 模型替身/常驻 Agent 提案审批链均已完成本地验收；D12d.3 已完成 TCP/NATS、HTTPS 模型故障、批准后启动前计划变更、独立进程数据存储故障及部署数据 API/浏览器完整性、独立进程异常读回、写入发布边界进程中断恢复、独立 AgentWorker 知识检索注入/撤权证据与 24 项矩阵盘点，剩余矩阵、长测与现场尚待后续门禁。不能把计划、fixture 或接口定义称为已实现产品能力。
- 用户已授权安装工作所需依赖；优先使用项目 `.venv`，锁定新增依赖。不为普通可逆开发操作重复询问。

## 分层与实现边界

1. 顺序：P0 工程/需求 → P1 契约/领域 → P2 持久化/确定性执行/Simulator → P3 专用 Agent/模型/Skills/MCP → P4 API/身份 → P5 Web → P6 集成部署 → P7 现场。
2. `src/alap/domain` 不依赖 FastAPI、LangGraph、供应商 SDK、数据库或网络。应用用例依赖端口，外部实现放适配器。`contracts/` 为共享 Schema 唯一源。
3. Agent 只读或提交提案；设备写由 Scheduler 和 Gateway 执行。MCP 工具发现与 Skill 导入不授予权限。
4. PostgreSQL 是业务权威，设备读回是物理依据；NATS 是通知。LangGraph checkpoint 与实验执行状态分离。
5. 审批绑定计划版本/hash、设备、参数、策略/能力与有效期；旧审批不能覆盖变化后的计划。
6. 单设备单写者；Gateway 检查 epoch、fencing、租约；UNKNOWN 不盲重试，相关后继冻结后对账。
7. 暂停/取消先表达请求，执行器确认后才能显示完成。目标值、实际值、数据鲜度分别建模。
8. Dataset 完整文件/校验和/元数据提交后才 COMMITTED；Schema 通过不等于完成存储或获授权。
9. 状态与 outbox 同事务，实验 SSE 使用 experiment_seq，快照包含 event_cursor；不要用 aggregate_seq 混合多个对象。
10. 真机操作遵循第 11/12 章现场门禁；模拟参数不构成真机授权。Proposed 或开发基线决策不等于现场批准。

## 环境与命令

当前基础层 Python 3.14，版本以 pyproject.toml 和 requirements-dev.lock 为准。后续框架/驱动接入时验证兼容性。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-build-isolation --no-deps -e .
# 先按 docs/D03_DATABASE_DEVELOPMENT.md 启动隔离 PostgreSQL
# 按 docs/D05_DATA_RECOVERY_DEVELOPMENT.md 启动 JetStream
# 设置 ALAP_TEST_DATABASE_URL、ALAP_TEST_NATS_URL；全套检查不允许静默跳过集成测试
.venv/bin/python scripts/check.py
```

编辑源文档或契约后生成：

```bash
.venv/bin/python scripts/build_lifecycle_reference.py
.venv/bin/python scripts/build_design.py
.venv/bin/python scripts/build_openapi.py
```

不得直接维护生成文件。按改动运行适当测试；收尾执行统一检查。范围覆盖、异常路径及尚未验证的层次应明确记录。依赖升级后同步锁文件；不要把本机 editable 路径写进锁文件。

## 协作与记录

- 默认中文；明确区分已设计、已编码、已本地验证、已集成验证和已现场验收。
- 变更关联 FR/NFR、契约、测试和文档；阶段进度及时写入 IMPLEMENTATION_STATUS.md。
- 当前会话为 Linux `/home/endsen/ALAP`，已推送 D12c.3/D12d.1 实现基线 6702ce9；此目录 Git 元数据不可用，当前上传检出为 `/tmp/alap-upload-20261020`，origin 为 endsen/ALAP；后续推送前重新核对远程与检出路径。当前 D12 进行中，D12d.2/3 本地实现尚未推送，续接先读 D12d.3 交接与 docs/D12D_FAULT_MATRIX.md，TCP/NATS、HTTPS 模型故障、批准后启动前计划变更、独立进程数据故障、部署数据 API/浏览器故障恢复、异常读回和写入中断恢复及知识检索/撤权证据已保存；知识撤权后的受限终态收尾已通过本地集成验证，本批完整验收结果见状态；受限 API/页面和新镜像预置上下文撤权路径也已验收，常驻 Agent 实际检索后 HTTPS 响应期间知识撤权/文献注入也已取得本地替身部署证据，非法用量及部分 SSE 后实际超时的八项部署案例和 604 项完整后端门禁已通过，三次尝试上限下的连续 429/部分 SSE 超时四项部署重试边界及 604 项完整门禁也已通过，调用前取消/调用中 RUN_BUSY 四项部署边界及 604 项完整门禁也已通过，第十六批已实现 d12_002 持久化取消意图、安全边界确认、提交竞态保护、API cancel_requested 与 Web 待确认语义，615 项完整后端及 Web 10 单元/20 fixture 浏览器通过。第十七批已加密冷备份并显式迁移常规 Compose 至 d12_002，后端镜像 89d67e17、Web fd41b31a 已部署；两供应商六项真实 HTTPS/API/Chromium 取消案例及 615 项完整后端通过，八服务与 15 份数据校验收尾通过。旧 RUN_BUSY 证据保留为历史；第十八批两供应商取消后/无取消对照的实际 HTTPS 期间 SIGKILL/重启四项部署案例通过，取消意图保留、无模型重放、再次重启状态/轨迹不变；615 项完整后端与八服务/15 份文件收尾通过。第十九批重试成功/累计预留不足阻止重试/调用前预算不足的六项部署案例、重复读取及重启用量稳定性已通过，617 项完整后端通过；2026-10-25 收尾八服务/15 份文件校验通过。第二十批模型能力新版本/旧模型禁用/Skill 新版本六项部署验证已通过，同版覆盖拒绝、旧绑定不替换、模型禁用不自动回退；619 项完整后端及 v1/v2 配置清理、八服务/15 份文件收尾通过。第二十一批已提交工具请求/只读工具结果两个位置的两供应商 SIGKILL 恢复四项部署案例通过，调用/提案不重复、第二次重启状态与轨迹不变；619 项完整后端（568.43 秒）及八服务/15 份文件收尾通过。第二十二批两供应商共 98 项部署 HTTP 权限断言通过，非提交人读取/控制拒绝、自身列表/用量隔离、API 成员撤权后立即拒绝；619 项完整后端（568.63 秒）与八服务/15 份文件收尾通过，测试身份/令牌/成员权限已清理，详见 reports/d12d3-permissions-acceptance.md。后续补非管理员提交人/受限字段/运行中提交人撤权及 MCP 运行期授权故障，不重复内置工具已提交边界恢复，勿重复已完成中断、预算和版本绑定验证，勿重复已完成验证或提前进入长测；实际环境及路径每次重新核对，勿沿用历史 macOS 路径。
- 使用多 Agent、外部服务或真机不是本文件隐含授权；普通测试使用离线模型替身与模拟仪器。
