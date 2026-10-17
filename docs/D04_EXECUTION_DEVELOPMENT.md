# D04 执行引擎与模拟网关

日期：2026-10-18。范围对应第 20 章 D04；这是内部应用用例与离线模拟适配器，没有部署为 Gateway/worker 服务，也不构成真机授权。

## 实现与运行

`ExecutionService` 使用 PostgreSQL 事务端口，物化批准计划的固定 Task 身份及依赖，整组领取资源后按依赖准备与发放命令。温控、磁场、SMU 三种模拟设备使用既有 Skill 参数契约。稳定条件核验原始采样时间、质量、单位、容差、斜率、持续窗口和鲜度。

中央权威状态保存在 PostgreSQL：`d04_001` 增加网关、仪器、控制代际、资源控制、租约、资源 claim、任务、命令、投递及回执表。每个 Task 仅产生一个命令；不可变命令字节/hash、租约绑定和版本由数据库约束保护。状态、证据、隔离、审计和 outbox 在同一事务提交。

网关 journal 和模拟物理设备动作记录使用两个独立 SQLite 文件；这是近端持久化，不替代中央数据库。journal 使用 WAL/FULL、进程文件锁及线程锁。网关接收前检查认证、epoch、最大 fencing token、相同 token 的 holder 绑定、deadline、策略/能力、参数和新鲜前置条件；重复 ID 只查询，相同 ID 不同内容拒绝。

按 [D03 开发说明](D03_DATABASE_DEVELOPMENT.md) 启动隔离 PostgreSQL，安装锁定依赖后运行：

```bash
ALAP_TEST_DATABASE_URL=postgresql://endsen@127.0.0.1:55432/alap_test .venv/bin/python scripts/check.py
```

测试使用随机数据库 schema 与临时 journal 文件，并自动清理；默认 WallClock 使用真实时钟，SimulationClock 仅用于显式测试。稳定窗口在集成 fixture 中缩短，不代表生产设备配置。

## 故障和对账语义

- 中央在发送前提交 DISPATCHED 与 ATTEMPTED。此后宕机或 ACK 丢失均进入 UNKNOWN，冻结发放并隔离所有关联资源，不重新发送原命令。
- 网关依次持久保存 ACCEPTED、RUNNING、实际结果。重启加载非终态记录不会调用设备执行。显式恢复仅在模拟器独立持久动作记录证明没有执行时确认 REJECTED_BEFORE_EXECUTE；已执行时核对持久结果及当前读回。真实仪器不能直接套用该证明方式。
- 多个未知命令可逐一对账，最后一个确认前 Run 保持 NEEDS_RECONCILIATION。迟到 ACK 不回退状态；矛盾终态回执留下事故审计并冻结/隔离。
- 租约过期保留 claim 和隔离。确认所有原命令结果及当前代际网关静止报告后才释放。D05 接入停止队列时必须同时核验停止请求全部确认。
- 恢复控制代际先设 RECOVERING，使用一次性 nonce 的认证握手绑定新 epoch。所有网关确认且旧命令终结后才启用；任一网关离线或结果不确定就继续阻断。旧 epoch 永久拒绝，不承诺每种不确定状态都能自动恢复。

## 验证与边界

`tests/integration/test_execution.py` 覆盖多资源及跨实验竞争、重复命令、旧 token/epoch、审批撤销、租约到期、ACK 丢失、发送前宕机、网关落盘边界、实际子进程退出后恢复、乱序/矛盾回执和事务回滚。`tests/test_stability.py` 验证稳定窗口拒绝条件。完整输出见 `reports/d04-validation.txt`。

模拟传输使用临时 HMAC 身份认证，不是生产 mTLS 或网络部署。进程锁依赖 POSIX `fcntl`；本期仅本地 macOS 验证，Windows 未验证，远程 CI 尚未运行。未连接真实仪器或 LLM。

IV 模拟结果只在本地保存，命令停留 VERIFYING，不伪造 COMMITTED Dataset。Dataset/血缘、持久事件发布/NATS、完整暂停/取消/停止协议属于 D05；HTTP 身份/API 与 Web 属于后续期。stop_requests 目前只有表结构，没有可用停止协议。当前应用也没有常驻调度 worker，调用方显式推进用例。
