# 13 · 部署、运维与可观测性

> v3.1 开发基线；原始 v3.0 保存在根目录合订本与 ZIP。新增平台范围见第 17、18 章，契约规则见第 19 章，实施顺序以第 20 章为准。

## 1. 推荐初期环境

开发：Docker Compose 启动 API/PostgreSQL/NATS/模拟 Gateway/数据存储，Web Next.js 本地开发；CI 容器内以模拟设备执行集成测试。阶段环境：`development`（只模拟）→ `staging`（模拟+指定测试 Gateway）→ `production`（经现场批准的真实设备）。

**首期形态**：中央服务器部署 Next.js、FastAPI、Agent Worker、Experiment Engine（可在同一后端仓库）、PostgreSQL、NATS JetStream、Dataset Store；实验室各地点运行独立 Gateway 进程。每个组件独立账户和最小权限。

## 2. 网络分区

```text
Browser  -- HTTPS -->  Reverse Proxy / API
                       |
              +--------+-------------+
              |        |             |
              API    Agent          Experiment Engine
              |        |             |
              +------ Postgres -------+
              +------ NATS -----------+
              +------ Dataset Store --+
                       |
                 mTLS / VPN
                       |
          Gateway Lab A    Gateway Lab B
              |                |
         GPIB / TCP         USB / Bridge
              |                |
         Instruments      Instruments
```

设备专用网段与中央应用网分离；普通 Web 用户不能直连 GPIB/USB 桥接端口。若跨网段，则使用经批准的站点 VPN 或受控主动连接方案。

## 3. 环境与密钥管理

- 数据库账号按读写范围分离：Web 只读聚合层、Engine 命令表写权限、Agent 仅提案写权限。
- 密钥/证书存集中 Secret 管理，不出现在 Git、普通日志、Agent Context 中。
- Gateway 证书与设备 ID 显式绑定；轮换证书需双版本窗口并记录审计。
- 依赖锁版本、镜像记录 SBOM/校验和；禁止无评审的在线远程热更新安全策略。

## 4. 可观测性（三支柱）

**Tracing**：`trace_id` 穿过 Web 请求、Agent Run、Proposal、Plan、Run、Task、Command、Gateway、Dataset，绝不把单个 SSE 事件当成全部追踪依据。

**Metrics**：Agent token/cost/latency、LLM failure rate、task queue depth、gateway connected count、telemetry staleness、device lease wait time、unknown command count、dataset integrity failures、outbox backlog、SSE gap/resync count。

**Logging**：结构化 JSON 日志，带 Actor/Experiment/Task/Instrument/Command IDs；设备机密、个人信息、私有样品数据按策略脱敏；关键审计单独存储。

## 5. 运维告警

| 告警 | 优先级 | 响应 |
|---|---|---|
| 设备危险态或互锁触发 | 最高 | 本地安全规程优先；通知操作员 |
| Command UNKNOWN 持续超过阈值 | 高 | 禁止相关新任务，发起对账 |
| Gateway 心跳陈旧 | 高 | 标记设备不可用，不进行新写操作 |
| 数据集校验失败 | 高 | 拒绝发布，保护已采集原始证据 |
| Outbox 积压 / NATS 不可用 | 中高 | 重试业务通知，确保 DB 状态不丢 |
| LLM 使用成本/迭代异常 | 中 | 停止新规划并通知，执行引擎不受影响 |

## 6. 备份/恢复

PostgreSQL 连续归档/WAL（按组织策略）+ 定期快照；Dataset Store 分层校验与备份；Gateway 本地 journal 定期回传；备份应定期做恢复演练。RPO/RTO 由实验室数据价值、设备运行要求决定，**现阶段待评审**，不可自行假定 0 数据丢失。

D12c.3 的单机模拟实现先提供一致性冷快照：停止全部写入者后一起备份 PostgreSQL、JetStream、Gateway journal/模拟物理状态、HDF5 与私有配置，加密后恢复到无外部出口的新项目。副本强制新 epoch、关闭执行入口，完成数据完整性和设备状态对账后仍不自动启动调度器。入口、密钥保管和失败处置见 `deploy/simulation/README.md`；验收证据见实施状态。这不替代本节生产 WAL、异地备份、PKI/凭据轮换或实验室 RPO/RTO 评审。

恢复必须先恢复状态，再与 Gateway/设备读回对账，才能开放命令写入口。数据库回滚会造成 fencing token 回退风险，需有单调令牌保护策略及网关可见的代际版本。

## 7. CI/CD 发布策略

每次变更分级：UI/只读 API、Agent 配置、Workflow Engine、Gateway/Driver、安全策略。后三级必须增强集成及现场验证；策略与驱动变更需审批记录。支持逐站点 canary，设备 RUNNING 时禁止不安全的中途自动升级。

## 8. 维护与回滚

升级前暂停新的不兼容任务、等待安全点、保存状态、部署服务、进行只读健康检查、核对运行中的 Gateway 状态，再允许新 Run。代码回滚不等于设备回滚；不提供自动“撤销磁场变化”之类物理回退功能。

## 9. v3.1 模型调用观测

区分逻辑请求与供应商尝试，记录实际 provider/model、Token 来源、缺失 usage、首 Token/总延迟、限流与错误；费用保存币种和价格版本。工具/MCP 与设备通信另设轨迹视图，通过 trace 关联。配置版本及凭据引用与密钥存储分离；实现遵循第 18 章。

## 10. D12c 分步落地状态

D12c.1 已实现新建专用数据库、显式迁移及迁移/运行账号分离，服务可通过私有连接文件配置；运行账号不能执行 DDL/TRUNCATE、关闭审计触发器或提升角色。当前仍是共享 runtime 应用信任边界，不能代表第 3 节的组件最小表权限或行级隔离。D12c.2 继续拆分组件权限并实际验证 Compose/镜像/网络/Secrets，D12c.3 实现备份恢复和观测；详细启动、验证及边界见 `D12_INTEGRATION_DEPLOYMENT.md` 和实施状态。
