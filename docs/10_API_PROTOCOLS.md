# 10 · API、事件与机器可读协议

> v3.1 开发基线；原始 v3.0 保存在根目录合订本与 ZIP。新增平台范围见第 17、18 章，契约规则见第 19 章，实施顺序以第 20 章为准。

## 1. 契约作为源代码

后端和前端以 [`../contracts/openapi.yaml`](../contracts/openapi.yaml) 作为核心 REST 接口单一契约来源，`../contracts/*.schema.json` 验证 Agent/设备/事件/命令报文。本文说明一致性与授权语义，不替代具体 schema。

## 2. API 版本、认证与错误

- REST 路由前缀 `/api/v1`；破坏性接口修改升主版本，兼容字段扩展升 schema minor 版本。
- 用户端采用登录令牌（OIDC/OAuth2 等）和资源级授权；Gateway 独立使用服务认证和设备身份。
- 对有副作用的创建接口使用 `Idempotency-Key`；并发修改用 `If-Match` / `revision`；不允许因前端超时自动重发任何直接设备写。
- 通用错误结构：`{error: {code, message, request_id, retryable, details}}`，建议错误码 `VALIDATION_ERROR`, `FORBIDDEN`, `PLAN_STALE`, `RESOURCE_BUSY`, `DEVICE_UNAVAILABLE`, `POLICY_BLOCKED`, `EXECUTION_UNKNOWN`, `RESYNC_REQUIRED`。

## 3. 最重要的 REST 端点

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| POST | `/experiments` | 创建实验 | Researcher |
| GET | `/experiments/{id}` | 获取权威状态快照 | 实验授权成员 |
| POST | `/experiments/{id}/proposals` | 创建版本化计划提案 | Agent service / Researcher |
| POST | `/experiments/{id}/approvals` | 审批指定计划版本 | 指定审批主体 |
| POST | `/experiments/{id}/runs` | 从已批准计划启动 Run | Researcher/Operator |
| POST | `/runs/{run_id}/actions` | pause/cancel/resume 请求 | 适用控制权持有人 |
| GET | `/experiments/{id}/events` | SSE 增量事件 | 实验授权成员 |
| GET | `/instruments` | 查询设备/状态/TTL | Observer+ |
| GET | `/instruments/{id}` | 查询设备能力与当前状态 | Observer+ |
| GET | `/datasets/{id}` | 数据集 manifest，随后获取受权下载地址 | 数据授权成员 |

API 不直接开放 `POST /instruments/{id}/raw-scpi` 之类任意物理命令接口。行政维护命令若必需，放独立受控运维路径，并有现场操作与审计要求。

## 4. 请求与响应示例

```http
POST /api/v1/experiments
Idempotency-Key: 98bfa8d9-5b4a-4c4f-966d-0ca69b3a92f1
Authorization: Bearer <token>
Content-Type: application/json

{"title":"零场整流研究","sample_id":"S-013","objective":"测量磁场历史对零场 IV 的影响"}
```

```json
{"id":"EXP-012","state":"DRAFT","revision":0,"created_at":"2026-10-16T08:00:00Z"}
```

审批请求必须携带 `plan_revision_id`、`plan_hash` 与必需的 `If-Match`；对已变更的计划返回 409，前端显示差异而非静默重试。

## 5. SSE 与前端一致性

```text
id: 43
event: task.started.v1
data: {"event_id":"...","aggregate_id":"EXP-012","aggregate_seq":7,"experiment_seq":43,"event_type":"task.started.v1","schema_version":"2.0","experiment_id":"EXP-012","occurred_at":"2026-10-16T08:00:02Z","producer":"experiment-engine","trace_id":"...","payload":{"task_id":"TASK-3"}}
```

断线使用 `Last-Event-ID: 43`，服务器从实验事件序号 44 补发。对已超出事件保留窗口的 last ID，不得只返回“最新事件”导致静默丢失，应明确要求获取完整快照重同步。心跳可以不带 ID，不改变业务序号。

## 6. 内部事件与命令隔离

事件代表**已发生的业务事实**，命令代表**待授权与执行的意图**，模型的 `Proposal` 又是更前一层的建议。三者采用不同 schema，不允许把 `proposal.created` 事件当成 `execute_command` 触发器。

Gateway CommandEnvelope 提供服务身份、租约、fencing token、截止时间、授权 plan hash 和设备能力/策略版本。业务要求每个状态变更记录来源；网关仍需本地检查，不能只信任中心 Scheduler 的判断。

## 7. API 契约测试

CI 校验 OpenAPI YAML 可解析、所有 JSON Schema 为合法 draft 2020-12；对每个路由测 401、403、422、409、429（适用时）、5xx；校验幂等键与请求 body 不匹配返回冲突；SSE 重连/事件间隙及事件重放；命令 JSON Schema 拒绝负 token、缺少授权字段、错误 instrument_id。

## 8. 版本迁移

v3.1 初次开发契约采用 2.0，尚无已部署旧协议；后续破坏性更改显式升版本。每个 Manifest 带 `schema_version`；版本升级有向后兼容窗口及迁移脚本；已运行 Run 锁定其计划和能力版本。设备 capability 与安全策略更新时，新任务必须按新版本验证；已运行的受控任务依设备规程停止/完成，不能静默换安全阈值。

共享结构由 JSON Schema 生成至 OpenAPI；路由源为 `contracts/openapi.base.yaml`，生成命令及漂移检查见根目录 README。规划中的平台管理路由在 P3/P4 补齐，不代表当前已有服务。
