# D12d.3 第 31 批：可选模拟监护执行链接线

日期：2026-10-26。环境：macOS /Users/endsen/codex/ALAP，Python 3.14.8；Git main 基线 1a3d456，保留第 30 批本地工作，未提交/推送。无真实模型 API、外部设备或多 Agent；无新增依赖。

## 交付范围

FR-009 / FR-011 / EVAL-09；ADR-056。独立 monitor 与 Gateway/Engine 命令路径接线：专用认证心跳、命令/epoch/世代绑定、不可延长命令期限、源表连续扫描中断、持久失败证据、中央任务失败/Run 暂停与禁止重放。已有命令/任务/Run 状态机和签名回执复用，公共业务 Schema 无变更。

## 已执行专项

`reports/d12d3-edge-execution-focused.txt`：36 passed in 21.33s。

- 第 30 批监护基础 25 项回归：策略、事务、真实独立进程失联/停止/重启。
- 新增命令绑定 6 项：command_id/epoch/generation/sequence/有效期拒绝、结束后心跳拒绝、命令 deadline、未对账动作禁止确认。
- 新增三进程集成 5 项：正常持续采集并完整提交；Engine SIGKILL；PostgreSQL 会话所有权失效；错误心跳密钥；Engine/Gateway 同时死亡后显式恢复。实际连续采集跨越 0.8 秒监护期限，0.2 秒逐点采样；使用真实经过时间和真实 SQLite/数据库状态。
- 阻塞 accept 期间专用心跳通道可达，命令密钥访问心跳拒绝；故障后源表为零，部分 artifact 不发布、Dataset 无记录，任务 FAILED、命令 FAILED_CONFIRMED、Run PAUSED。重启后锁存保持、控制门禁 RECOVERING，无自动恢复或重复物理动作。

## 完整门禁

`scripts/check.py` 成功退出：**691 passed in 228.19s**，真实集成无跳过；Ruff、格式、状态机参考/设计合订本/OpenAPI 生成一致性、13 份 Schema/实例和 OpenAPI 验证、pip check 全通过。专用 PostgreSQL 18.6 / 55433、NATS 2.15.1 / 54223 已停止，fixture 子进程清理完成。日志：`reports/d12d3-batch31-backend.txt`。本批新增 11 项，相对第 30 批 680 项；未改 Web，未运行 Web 门禁。

## 明确保留的边界

默认 Compose 未接入本批可选配置。现有未受监护的物理动作库不能直接切换为新输出模型；使用新建独立模拟目录。维护确认的 operator/reason 仍是私有模拟审计字段，没有网络身份授权；没有开放确认端点。真正网络分区、执行中监护/存储异常组合、取消/暂停竞态、C 级部署/mTLS 组合与 G1/G2 现场保护仍待后续验证。源表确认静止不适用于磁体/温控。软件进程或共享存储失效不能保证真实设备停止。

本批不宣称 EVAL-09 / D12 完成，不启动 D12d.4 长测或 D13。下一步先实现受控维护身份/恢复路径并验证锁存解除门禁，再补网络分区及部署组合。
