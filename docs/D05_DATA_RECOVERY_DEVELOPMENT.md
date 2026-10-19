# D05 数据与事件恢复

日期：2026-10-18。范围为内部应用用例、真实 PostgreSQL、HDF5、JetStream 和离线模拟网关；没有 HTTP/SSE 服务、Web、LLM 或真实仪器。D05 分三个顺序迁移：d05_001 数据、d05_002 事件、d05_003 停止确认。统一检查报告见 `reports/d05-validation.txt`。

## 数据提交与来源

`DatasetService.stage` 只接受已落库并重新验证签名的采集回执，绑定 Command/Task/Run/Experiment、原始采集时间、技能参数、策略/能力版本。缺少原始采集时间的旧回执会拒绝正式发布，不推算时间或自动重新采集。当前支持 `iv_measurement@1` 的 HDF5 格式；验证点数、有限数值、扫描序列和 compliance。HDF5 是实际二进制文件，不是改扩展名的 JSON。Zarr 和其他采集类型留待各技能适配。

`device_snapshots` 保存原命令发放事件及其实际前置读回证据；`device_snapshot_version` 为该实验中原发放事件序号，通过复合外键绑定命令。它不是计划快照版本，也不声称覆盖采集期间每个时间点；完整原始时间窗与 Gateway 回执单独留存。

文件写入使用临时文件 → 关闭 HDF5 → fsync 文件 → 不覆盖的硬链接发布 → fsync 目录 → 重读数据/元数据及 SHA-256。失败不发布 Manifest；文件操作不占数据库事务锁。[h5py 文件接口](https://docs.h5py.org/en/stable/high/file.html)

数据库先保存 STAGING，文件通过后转 VALIDATING；完整 Manifest、采集血缘、COMMITTED、审计、证据和 `dataset.committed.v1` 同事务提交。失败保留可恢复状态和原文件，重试不得重新采集。一个命令只绑定一个数据集；重复/并发提交返回同一 Manifest。已提交文件缺失或损坏不能静默重建；完整性检查转 CORRUPT 并撤销读取，保留原 Manifest、checksum、来源与历史。未提交/损坏对象的快照不暴露正式 Manifest。

`read` 前后检查当前实验读取权限与状态，返回已校验字节，不把本地路径当公网下载地址。存储根由服务独占，键由 ID 哈希生成，拒绝路径穿越、符号链接和特殊文件；本期对象规模为有限 IV 数组，未实现大文件流式 HTTP 下载或自动垃圾回收。孤儿文件保留，不会默认删除实验数据。

`finalize` 在数据库提交之后，独立向 Gateway 发送绑定采集 hash 的发布确认；Gateway 才把 VERIFYING 转为 SUCCEEDED。确认丢失可重复查询/确认，不调用设备执行；中央再次校验 COMMITTED 数据及原始采集内容后汇总 Task/Run。UNKNOWN 先显式对账；不会为了补数据重发物理命令。

## 事件发布、消费与快照

`EventService.publish_once` 使用独立 claim 表及随机 token 领取待发事件，领取与确认均为短事务；外部 publish 在事务外等待 JetStream ACK，随后写 published_at。claim 30 秒到期可重新领取；旧 token 不能确认新领取。服务器未运行/ACK 丢失不把事件标记已发布。批次重投可能乱序，不能作为设备发放依据。

JetStream 使用文件存储及 `Nats-Msg-Id=event_id`；去重窗口之外仍依赖数据库永久 inbox。消费者先核验事件与权威 outbox 一致，同一事务写 inbox 与最新对象投影；旧 aggregate_seq 不覆盖新投影，重复无副作用，同 ID 异载荷拒绝。只有数据库提交后才 broker ACK；错误不 ACK。当前投影是通知读模型，不执行分析、计费或设备动作。[NATS JetStream](https://docs.nats.io/concepts/jetstream)、[Python 客户端](https://github.com/nats-io/nats.py)

实验快照在同一 REPEATABLE READ 中包含任务、命令、数据集状态与 event_cursor。`after` 按 experiment_seq 分页，逐次检查权限；未来游标或历史缺口返回 RESYNC_REQUIRED。当前保留全部不可变事件，不做自动清理。HTTP SSE 连接/断线 UI 在 D09/D10 实现。正式成功通知统一为 `task.succeeded.v1`；审计仍记录原转换事件，不重写既有历史 outbox。

## 暂停、取消与恢复

`ControlService` 校验操作员对实验/资源/风险的权限；engine_actor 必须是已显式配置的执行服务。暂停关闭发放门，有限 Task 结束后才确认 PAUSED；未发送命令保留身份。resume 重核审批、租约、原始读回和子项静止。租约已释放时可先为 PAUSED Run 重新整组领取；过期/隔离仍须完成原有释放对账，不自动抢占。

取消将 Run/Task/Command 意图和 stop_requests 同事务保存。没有发送过的命令可直接 CANCELLED；已发送的必须走独立停止协议。Gateway 停止请求绑定原命令字节、epoch、ID，并在 journal 中持久保存请求 hash 和确认。停止先于命令到达时保存 CANCELLED 记录，迟到的原包只返回原结果，重启后仍不执行。

模拟网关在有限动作边界处理停止：执行过程中持有独占锁，停止等待该有限操作结束；若动作已经完成则正常结果胜出，数据型动作继续等待正式 Dataset，不能以取消抹去已采集结果。这不是实时抢占式急停；真实仪器的硬联锁、厂商停止指令和响应时间仍属 D13。

停止超时/错误确认进入 UNKNOWN 并隔离资源；可以重投同一停止请求以取得持久确认，但不得重投普通命令。只有与原命令匹配的签名确认才能更新结果。资源释放、Gateway 换 epoch 和完成代际恢复都核验停止请求已确认。部分任务成功、其他任务取消时 Run 为 CANCELLED；全部成功时允许完成竞争胜出。UNKNOWN 状态没有通用 cancel 快捷出口，应先对账或恢复已有停止请求。

## 运行环境与验证

本次 Linux 使用 Python 3.14.7、PostgreSQL 18.6、NATS Server 2.15.1；HDF5/nats-py 及传递依赖锁在 requirements-dev.lock。PostgreSQL 从 Arch 软件包解压到 `/tmp/alap-pg18`，数据在 `/tmp/alap-d05-postgres`，仅 Unix socket，不安装系统服务。NATS 程序在 `/tmp/alap-nats15`，只监听 127.0.0.1:54222。验收后停止两者，临时目录不是业务数据或必须续接的服务。

已保留临时程序时可重新启动：

```bash
LD_LIBRARY_PATH=/tmp/alap-pg18/usr/lib /tmp/alap-pg18/usr/bin/pg_ctl \
  -D /tmp/alap-d05-postgres -l /tmp/alap-d05-postgres.log \
  -o '-k /tmp/alap-pg18 -p 55432 -h ""' start
/tmp/alap-nats15/nats-server-v2.15.1-linux-amd64/nats-server \
  -js -a 127.0.0.1 -p 54222 -sd /tmp/alap-nats15/data
```

另一个终端执行：

```bash
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-build-isolation --no-deps -e .
ALAP_TEST_DATABASE_URL='postgresql://endsen@/alap_test_d05?host=/tmp/alap-pg18&port=55432' \
ALAP_TEST_NATS_URL='nats://127.0.0.1:54222' .venv/bin/python scripts/check.py
```

目录丢失时需重建隔离数据库（名称以 alap_test 开头）并启用 JetStream。每项数据库测试使用随机 schema 并清理；NATS 测试使用唯一 stream 并清理。缺少数据库或 NATS 时测试明确失败，不静默跳过。CI 已增加固定版本 NATS 容器，但本轮远程 CI 尚未执行。

覆盖：迁移 up/down/up；半上传/文件持久后事务失败；幂等并发提交；损坏撤回；读权限；发放快照与血缘；数据确认 ACK 丢失；真实 JetStream 发布/ACK 丢失/NAK 重投；inbox 和投影原子回滚；乱序不回退；游标及权限撤销；暂停/恢复；取消竞争；停止 ACK 丢失/错误绑定；迟到原包与 Gateway 重启；停止与代际恢复屏障。

未宣称验证：真实 NATS 集群故障切换/服务器崩溃恢复、生产 TLS/凭据配置、长期容量、跨平台 Windows、真实仪器急停和现场验收。这些保留在部署/现场阶段；离线 HMAC 不代表生产认证。

## 下一期

D06：ModelClient 端口、多供应商连接/能力配置、OpenAI/DeepSeek API 适配、流式输出/工具调用/错误与用量；先做离线协议和异常测试。不得跳过它直接构造 Agent 或 Web 演示，不依赖本期临时服务持续运行。
