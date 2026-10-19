# D09 · 应用 API 与身份权限开发交接

本期提供可启动的 FastAPI 应用、身份与资源授权、平台管理接口、实验 SSE 和凭据存储；未启动 Web 工期。基于 D05–D08 本地实现，尚未上传 GitHub或执行远程 CI。

## 实现与契约

- `adapters/api/app.py` 从生成的 OpenAPI 注册路由和校验请求，公共错误统一为 `error.code/message/request_id/retryable`。JSON 重复键、非有限数、未知字段、重复查询参数、超限 body 被拒绝；错误不回显输入和数据库/供应商异常。
- `application/api.py` 编排既有用例；`adapters/postgres/api.py` 保存身份、管理状态、审计与 API 请求账本。应用层不导入 FastAPI、数据库驱动或供应商实现。
- `adapters/api/bootstrap.py` 组装可启动服务；执行技能、策略/能力版本、数据根目录、服务身份均来自显式部署设置。不会自动导入模拟样例或执行迁移。
- 契约源是 `contracts/openapi.base.yaml` 与共享 JSON Schema；`scripts/build_openapi.py` 生成 `contracts/openapi.yaml`，禁止手工维护生成结果。

61 个契约操作覆盖实验/样品、计划版本/审批/Run、仪器元数据/数据下载、Agent/Skills 导入发布禁用、Agent Run/轨迹、连接/模型、MCP 发现/人工授权/撤销、知识/记忆导入检索分享禁用、分析、仪表板/用量、凭据与审计。管理配置使用已实现的有限能力，不代表支持任意模型协议或 MCP 模式。

早期占位审批接口已对齐 D03 的真实流程：提交完整 PlanRevision（`POST /experiments/{id}/proposals`）→ `approval-requests` → `approvals` 的人工决定 → 绑定 `approval_id` 创建 Run。直接 HTTP 计划提交的来源统一为 `principal:<authenticated actor>`，客户端不能冒充某次 Agent Run；正式 Agent 原始提案仍保留在独立 PROPOSED ledger，前端转录为人工提交时需要展示这一区别。没有公共 raw SCPI 或物理命令投递接口。

## 身份与授权

本期实现**本地高熵 opaque Bearer token**：可信运维命令签发，数据库只存 SHA-256 摘要，有时效、撤销与主体禁用。请求每次读取当前主体/角色；不信任 body/header 自报的 actor。没有密码登录、匿名注册、OIDC discovery/JWKS 或 refresh-token 流程，不能称为已完成企业 SSO；后续身份供应商可在相同边界接入。

平台角色 admin/researcher/observer 与实验 owner/operator/approver/observer 分离。管理员权限不自动授予实验数据访问；普通成员不能管理模型、凭据、MCP 或全局 Agent/Skills。审批仍要求人类主体。既有实验/仪器/风险 ABAC 在应用层再次执行。

新实验 owner 默认资源范围为空；管理员通过带 `If-Match` 的 `/experiments/{id}/scope` 显式授予已登记仪器与风险范围，再由 owner 在自身范围内分享成员权限。不能依靠创建实验获得全设备权限。主体创建/平台角色初始化属于可信本机运维，尚未开放普通用户自助授权。

完整实验快照/SSE 要求覆盖其中全部计划资源，避免窄范围成员得到其他仪器内容。仪器列表按当前成员范围筛选，仅返回元数据、UNKNOWN 与空 observed_at；未接入新鲜遥测时不伪造 ONLINE。数据下载在文件读取前后检查 COMMITTED、版本、checksum、成员和仪器范围，不暴露本机路径。

## 幂等、并发与事件

有副作用请求必须提供 `Idempotency-Key`；审批/计划/运行创建、成员/范围、凭据更新与 Run 控制使用 quoted revision `If-Match`。控制动作匹配的是 Run `state_version`，其他实验变更匹配实验 `revision`。凭据首次创建使用 `If-Match: "-1"`，轮换/禁用使用元数据 revision。重复键且不同请求返回 409。

通用 API 请求账本先持久化 INFLIGHT，再调用既有用例。完成后缓存脱敏响应；相同请求返回原结果，不重复模型调用或控制动作。调用后、结果入账前宕机保留 INFLIGHT 并返回 EXECUTION_UNKNOWN，必须检查业务记录，不自动重放或换键掩盖不确定性。底层实验事务仍保留 D03 原子幂等；通用管理 API 不声称跨所有子服务恰好一次提交。失败返回固定错误码，未知异常无输入回显。

重放前重新检查当前身份/权限。知识检索和分析虽使用 POST，但不缓存授权结果：每次都复核当前来源/数据权限；确定性分析本身由 D08 唯一键去重。

SSE `id=experiment_seq`，支持 Last-Event-ID 和 after，冲突/非法游标拒绝；预检发现历史间隙或游标超前返回 409 RESYNC_REQUIRED。流每轮重新检查 token、成员和资源权限，事件页在自身 REPEATABLE READ 事务中校验计划资源与成员范围；响应开始后撤权/失效使用无业务 ID 的 `stream.error` 并关闭。心跳不带 ID；每连接默认最多 15 秒，客户端重连续传。NATS 不作为授权事实来源。

基础限流为单进程内按主体每分钟 120 次，超限返回 429/Retry-After；不是集群限流、持久配额或费用计费。生产 TLS、网关限流及连接容量验证属于 D12。

## 凭据、模型与统计

`EncryptedSecrets` 使用 Fernet 认证加密，密文绑定凭据引用；主密钥由进程外文件提供，不进仓库/数据库。HTTP 只接受写入或返回配置状态/掩码，不能读回明文。幂等内容指纹使用主密钥派生的 HMAC，审计不保存请求体。凭据轮换/禁用使用 revision；主密钥轮换、备份恢复和外部 KMS 适配尚未实现。

连接/模型配置版本不可覆盖，保留公开能力声明；HTTP 不允许把自报能力标为 tested。运行时按固定版本重新解析当前模型/连接及凭据，已禁用配置不能新发模型调用。MCP HTTP 管理不开放回环测试豁免或任意 shell，仍采用 D08 的固定地址、TLS 和只读人工审核策略。已批准工具定义可从数据库重建，重启不自动授予新权限。

用量范围为当前主体在指定实验的 Agent Runs；来自持久 trace，按已记录模型完成/attempt 去重统计。仪表板组合实验状态、审批/Run/数据状态计数与未知设备元数据。用量可按供应商、固定模型版本、Agent 版本与 UTC 日期分组，返回逻辑请求、已记录 attempts、未决请求、已知 token 小计和未知 usage 数；费用/延迟缺少依据时为 null。该指标不等于供应商账单、全平台成本看板或完整网关网络流量。原始模型 token delta 不充当持久业务事件。

## 启动与运维入口

先安装 `requirements-dev.lock` 并执行 editable install，按 D03/D05 文档配置隔离数据库及迁移到 d09_001。不要将测试数据库当作生产数据库。

部署设置 JSON 必须包含 `execution_skills`、`policy_versions`、`capability_versions`、`artifact_root`、`engine_actor`；内容由受信任部署方提供，不能直接把模拟配置视为真机配置。工厂默认没有 Gateway 网络适配，需读回的 resume 会返回 SERVICE_UNAVAILABLE；pause/cancel 仅记请求/确定性状态，实际停止仍由执行 worker 处理。常驻调度、事件发布及设备服务由 D12 装配。

```bash
# 值由本机运维提供；不要将真实 DSN、主密钥或 token 提交仓库。
export ALAP_DATABASE_URL='<PostgreSQL DSN>'
export ALAP_API_SETTINGS='<部署设置 JSON 的绝对路径>'
export ALAP_MASTER_KEY_FILE='<仅服务用户可读的 Fernet 主密钥文件>'
.venv/bin/python scripts/provision_api.py --actor admin --role admin --token-file /tmp/alap-admin-token
.venv/bin/uvicorn alap.adapters.api.bootstrap:factory --factory --host 127.0.0.1 --port 8000 --no-access-log
```

令牌文件使用独占创建及 0600 权限，一小时有效；命令不打印 token。环境中的 DSN 要使用 Psycopg 可接受形式，Alembic 使用对应 SQLAlchemy 驱动 URL。不要把 token 放在 URL。默认没有 CORS 放行或 cookie 认证，浏览器接入时优先同源部署。

## 验收与下一期

测试使用真实 PostgreSQL、回环 Uvicorn/MCP、真实 HDF5、模拟 Gateway 和离线模型；没有使用真实 LLM 密钥、付费模型、公网 MCP 或仪器。覆盖每个契约路由无令牌 401、角色/实验/资源隔离、422/409/429/500、审批链、并发请求、未知不重放、SSE 续传/撤权、凭据脱敏、知识撤权、模型配置、Agent/Skill/MCP 管理、数据下载及服务组装。最终全套门禁通过：423 项测试（145.89 秒），包含本期新增 30 项 API 集成测试；Ruff/格式、生成一致性、13 份 Schema/实例、OpenAPI 与依赖检查全部通过。结果见 `reports/d09-validation.txt` 和 `IMPLEMENTATION_STATUS.md`。2026-10-19 完成交接，下一期尚未启动。

下一期 D10 是 Web 实验工作区：导航、会话、计划审批、实验/设备/数据和实时状态；D11 再完成平台管理控制台。D09 不代表平台 UI、企业身份集成或现场验收已完成。

实现参考：[FastAPI 权限依赖](https://fastapi.tiangolo.com/advanced/security/oauth2-scopes/)、[Starlette 请求与断线](https://starlette.dev/requests/)、[响应流](https://starlette.dev/responses/)。本期使用依赖包实际安装版本并完成离线/本地集成测试，不按文档示例声称所有生产场景已覆盖。
