# D12c.3 冷备份与隔离恢复验收（2026-10-21）

实际 Compose 恢复演练与最终统一门禁通过：**565 项测试，428.72 秒**，格式/lint、契约、生成一致性及依赖检查全部通过；见 `d12c3-backend-validation.txt`。本期仅是本机 rootless 模拟环境的冷快照恢复，不代表生产热备、完整 E2E、全天候告警或现场验收。

## 样本与一致性边界

通过现有 ExperimentService 的创建实验、保存计划、请求审批、审批和启动 Run 用例，在 `EXP-BACKUP-001` 生成专用模拟测试数据。审批身份 `backup-reviewer` 仅授予该实验的三个模拟资源及 operator_review 范围；它是测试 fixture，不代表现场批准。常驻 Engine 经网络 Gateway 完成温度、磁场及 IV 三个任务，得到 3 条 SUCCEEDED 命令、1 条 SUCCEEDED Run 和 1 份 COMMITTED HDF5；未调用外部模型或真实仪器。

停机冷备份按接入、执行、Gateway/消息、数据库顺序停稳；确认 PostgreSQL clean shutdown 和无活动卷使用者后，导出四卷及私有配置。最终备份约 373 MiB，AES-256-GCM 密文与 HMAC 完成清单保存于 `.local-deploy/backups/d12c3-002`；密钥单独保存在 `.local-deploy/backup-keys/`。备份、密钥、DSN 与 token 均未纳入报告或 Git。

## 实测结果

| 检查 | 结果 |
|---|---|
| 非空冷备份 | 成功，约 21.4 秒；源服务保持停止，未自动重启 |
| 隔离导入与冻结 | 新项目 `alap-restore-d12c3drill002`、新卷与新私有目录，约 13.918 秒；使用快照记录的精确本地镜像 ID |
| 新 epoch | 源与副本 epoch 不同；副本 RECOVERING，所有旧 Run 保持 dispatch_blocked |
| 会话隔离 | 原库 3 条未撤销 token，副本全部撤销；未改源 token |
| 文件缺失故障 | 只在副本暂时移走唯一 HDF5；审计返回 ARTIFACT_INVALID，退出 1，保持 RECOVERING；Gateway、常驻 Engine/Agent/API/Web/outbox 未运行 |
| 修复后对账 | 复原同一文件后，COMMITTED 校验 1 份，journal.sqlite/physical.sqlite quick_check 均 ok；恢复为 ACTIVE，commands/stops/problems 均为空；约 6.099 秒 |
| 不重放 | 对账前后命令均 3 条，模拟物理动作均 3 次，数据集均 1 份；旧 Run 未解除冻结 |
| 网络与进程 | 所有副本网络均 internal、全部容器无宿主发布端口；成功后只运行 PostgreSQL/NATS/Gateway，无常驻调度或 Agent；验证后全部停止 |
| 错误密钥 | 实际 CLI 拒绝，退出 1，未创建目标目录或进入 Docker 资源创建 |
| 普通启动拒绝 | `manage.py up --directory <restore>` 明确拒绝，不能通过正常部署入口启动克隆执行器 |
| 归档拒绝路径 | 15 项专项覆盖错误密钥、清单/载荷篡改、缺卷、链接、路径越界、重复成员、失败解密清理和维护互斥 |
| 真实数据库专项 | 强制新 epoch、COMMITTED 数据校验及损坏拒绝、真实状态/outbox/恢复告警，纳入统一门禁 |

结构化前后证据、精确镜像、epoch、运行状态、网络、耗时见 `d12c3-restore-evidence.json`。计时来自本机单次操作，13.918 + 6.099 秒不包含人工故障检查/修复间隔，也不是承诺的生产 RTO。RPO 为最后一次成功冷快照之后未备份的变化；未实现 WAL/PITR 或异地保管，不能宣称零数据丢失。

## 发现并修复的问题

第一轮恢复的文件缺失阻断正确，但文件复原后 SQLite WAL 模式在只读卷上无法创建所需共享内存文件，审计拒绝开闸。修复为先停稳副本 Gateway，在私有临时目录复制数据库与 WAL 并执行完整性检查，原 journal 仍只读挂载；检查通过后才启动 Gateway 对账。重新构建镜像、生成全新快照并导入第二个隔离目标，故障和成功路径均重新执行通过。第一轮副本和快照保留且已停止，不作为最终通过证据。

另修复首次部署的维护锁目录尚不存在时无法执行 prepare 的问题；锁目录可私有创建，互斥/新目录测试已通过。没有新增应用依赖、数据库迁移或公共 HTTP 契约。

## 运维与交接

按需 `operations.py status` 读取服务状态及 PostgreSQL 权威计数、恢复状态、待确认停止和 outbox 积压年龄。数据库未运行返回 null，查询失败显示不可达，不把缺失信息当健康；它不负责自动告警。恢复副本因无 outbox worker，可保留恢复事件积压，不能误认为已完成发布。

最终保留原模拟部署；两个演练副本均停止，卷、备份与密钥留在忽略目录供复核，不自动删除。最终八服务恢复运行，首页 HTTP 200、匿名 API 401；QA 端口已移除，临时测试数据库/角色均为 0，见 `d12c3-final-runtime.json`。`verify.py` 的 D12c.2 空库断言不再适用当前已有模拟执行记录，不能用它替代本期的非空数据恢复验证。

下一工作项是 D12d：完整业务/浏览器 E2E、故障矩阵及实际 24 小时以上负载模拟。本轮不启动 D12d/D13、不推送 GitHub、不访问真机或付费模型。
