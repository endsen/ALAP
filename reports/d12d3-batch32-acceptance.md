# D12d.3 第 32 批：维护身份与恢复门禁

日期：2026-10-26。macOS /Users/endsen/codex/ALAP，Python 3.14.8；Git main 基线 1a3d456，保留第 30/31 批本地工作，未提交/推送。无新增依赖、无数据库迁移、未用真机/真实 LLM 服务。

## 实现与契约

FR-009/FR-011、EVAL-09、ADR-057。维护状态 GET 与确认 POST 由现有 Bearer 身份认证，要求启用的人类 admin。`edge_ack.schema.json` 是审查请求唯一源；OpenAPI 已生成。API 与 Gateway 使用独立维护密钥，命令/心跳密钥不具有维护权限。维护凭据不配置给 Engine/Agent。

中央 RECOVERING + 全部命令/停止请求收敛后，保存包含 review_id/身份/事故/读回/原因的审计意图，再向 Gateway 签发最长 10 秒授权。Gateway 检查自己的 epoch/journal、操作互斥；monitor 事务检查活动命令、鲜度、源表零输出、精确读回/策略/世代与期限，然后原子保存确认审计并转 WAITING。旧 Run 不恢复、失败任务不重试、输出不恢复。

## 已执行验证

`reports/d12d3-edge-maintenance-focused.txt`：**53 passed in 51.69s**。其中本批新增 17 项，前两批监护/命令/三进程执行回归 36 项。

- API 认证缺失 401，普通用户/服务主体 403，人类 admin 可查看；禁用主体拒绝。角色撤销后不允许读取成功的幂等确认缓存。
- 命令与心跳密钥无法访问 Gateway 维护通道；旧事故/世代/Gateway epoch/策略/读回拒绝，锁存与审计保持。
- 单调时钟回退、monitor 停止推进、非零源表、授权过期、确认审计写失败均不解除锁存；审计失败事务回滚。
- Engine SIGKILL 后确认失败对账与维护；确认后原 Engine 握手进入 ACTIVE，但旧 Run PAUSED、命令/任务 FAILED、源表为零、无 Dataset 发布且每条动作仍一次。
- 中央未进入恢复/命令未收敛拒绝且不签发意图；Gateway SIGKILL 后本地非终态 journal 单独阻止确认，显式恢复后才允许维护/握手。
- 注入确认后回复丢失：POST 返回 500，相同幂等键返回 EXECUTION_UNKNOWN；GET 的监护确认审计可与中央 review_id 匹配，实际确认一次，不自动重发。中央审计意图失败则不调用确认。

## 完整门禁及环境收尾

`scripts/check.py` 成功退出：**708 passed in 259.13s**，真实 PostgreSQL/NATS 集成无跳过；Ruff/格式、状态机参考/设计合订本/OpenAPI 生成一致性、14 份 Schema/实例与完整 OpenAPI、pip check 全通过。日志 `reports/d12d3-batch32-backend.txt`。专用 PostgreSQL 18.6/55433、NATS 2.15.1/54223 已停止，测试子进程由 fixture 清理。

## 保留边界和下一动作

本批为本机 HTTP/数据库/独立模拟进程验收，不替代 C 级 mTLS/Compose 组合。默认部署未添加 monitor/维护密钥，未实现 Web 维护页面；未运行 Web 门禁。维护授权在签发前及幂等读取前检查权限，已签发短期委托不保证即时撤销。软件进程/共享存储故障不保证真实设备安全。

下一步补真正网络分区、执行中 monitor/存储异常组合、取消/暂停竞态，再评审 C 级部署；EVAL-09/D12 未整项完成，不开展 D12d.4 长测或 D13 现场。
