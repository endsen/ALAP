# D03 数据库开发与验证

本说明是开发操作手册；设计基线仍为第 21/22 章。迁移、用例和测试不启动 Web、设备或模型服务。

## 环境

- Python 3.14；当前 macOS 验证使用 3.14.8。
- PostgreSQL 18；当前本机 18.6，CI 配置 PostgreSQL 18 service。
- Psycopg binary 3.3.6；Alembic 1.20.0 / SQLAlchemy 2.1.5；完整依赖见 requirements-dev.lock。
- SQLAlchemy 仅用于迁移环境，Repository 使用 Psycopg 参数化 SQL，领域层无数据库依赖。

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-build-isolation --no-deps -e .
```

## 本机隔离 PostgreSQL

macOS Homebrew 已安装 python@3.14 与 postgresql@18。使用自己的临时集群，不使用已有业务数据库；不注册开机服务。以下目录如已存在，不重复 initdb。

```bash
/opt/homebrew/opt/postgresql@18/bin/initdb -D /private/tmp/alap-d03-postgres -A trust -E UTF8
/opt/homebrew/opt/postgresql@18/bin/pg_ctl -D /private/tmp/alap-d03-postgres \
  -l /private/tmp/alap-d03-postgres.log \
  -o '-h 127.0.0.1 -p 55432 -k /private/tmp' start
/opt/homebrew/opt/postgresql@18/bin/createdb -h 127.0.0.1 -p 55432 alap_test
export ALAP_TEST_DATABASE_URL="postgresql://$(id -un)@127.0.0.1:55432/alap_test"
.venv/bin/python scripts/check.py
/opt/homebrew/opt/postgresql@18/bin/pg_ctl -D /private/tmp/alap-d03-postgres stop -m fast
```

trust 仅用于当前本机隔离测试实例，不作为部署认证配置。CI 使用独立容器的测试账号。连接串不写入源码或检查报告。测试数据库名必须以 `alap_test` 开头；每个测试新建随机 schema，完成后仅删除自己创建的 schema。没有连接串时数据库测试明确失败，不静默跳过，不使用 SQLite/内存替身。

只验证纯基础层时可显式使用 `.venv/bin/python -m pytest -m 'not postgres'`，该命令不构成 D03 验收。

## 显式迁移

设置 `ALAP_DATABASE_URL`，协议使用 `postgresql+psycopg://`；迁移工具不从日志打印凭据。

```bash
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m alembic current
```

D03-001：身份/样品/实验/成员；D03-002：不可变计划/审批/Run/幂等；D03-003：证据/审计/outbox。

仅数据库名以 `alap_test` 开头时允许 `alembic downgrade base`。测试执行空库 up/down/up。业务库采用前向修复与审阅过的数据迁移；没有启动时清空/重建数据库的行为。

## 应用边界与权限

入口为 `ExperimentService`，传入 `PostgresUnitOfWork`、契约目录与受信任的固定 Skill/策略/能力版本。支持创建实验、保存计划、申请审批、批准/拒绝/撤销、到期处理、创建 READY Run、读取一致性快照。

- actor ID 必须由调用端认证后传入；这些是内部 Python 用例，尚无 HTTP 身份认证。测试身份显式写入隔离数据库；不存在默认匿名管理员。
- 创建实验仅允许样品所有者。创建者获得实验 owner 成员关系，但资源/风险范围为空；身份管理方必须显式配置 scope，创建实验不自动授予设备权限。
- membership 的 scope 为 `resources` 与 `risk_levels` 两个显式列表，必须覆盖计划资源和风险；service 主体不能批准，timer 需要显式 `alap-timer` issuer。
- 写事务在业务锁之前对 principal 取共享锁，实验锁后对 membership 取共享锁。身份管理事务应遵循 principal → experiment → membership 顺序，不能反向获取；撤销、禁用将与在途操作串行化。样品创建分支在幂等记录后锁 sample，不再锁既有实验。
- 每个计划变更创建新记录；数据库禁止修改/删除历史计划。审批绑定完整计划 hash（间接包含动作/参数/技能/策略/能力）及固定资源、风险、期限。读取时重新核对包络 hash。
- 当前策略/能力来自受信任进程配置；真实设备注册表在 D04、平台版本管理在 D06 以后接入。配置不能从模型或请求字段取得。
- 幂等键按 actor/operation/scope 隔离；相同载荷返回历史响应，不代表批准仍有效。每次重放先核对当前身份/实验权限。不同载荷冲突；expires_at 仅标记保留资格，本期不清理记录或允许旧键重复执行。
- 创建 Run 不调度设备，dispatch_blocked=true；固定 task_identities 保存每个任务的 ID/plan_task_id/attempt_no=1。D04 再物化任务表并取得实际资源许可，不自动重开失败任务。
- 撤销、过期、计划替代会在同一事务更新审批、关联未执行 Run 的 PAUSED/发放门、证据、审计、实验 revision/cursor 和 outbox。D03 只为从未发放的 READY/PAUSED Run 建立 children_quiescent；遇到执行态拒绝猜测，D04 扩展真实证据。
- 证据由锁定行、权限范围、明确期限与当前版本推导，保存具体核验依据；不根据状态机新增事实自动生成“已满足”证据。
- outbox 保存符合共享 event Schema 的包络；payload/身份/游标不可修改，仅发布确认时间可更新。NATS 发布、消费去重与 SSE 服务在 D05/D09。
- 短写事务显式 READ COMMITTED；快照 REPEATABLE READ READ ONLY，同时读取实验、计划、审批、Run、事件及 cursor。所有 SQL 参数化，事务中不调用外部服务。

## 验收与阶段范围

`tests/integration/test_persistence.py` 覆盖真实迁移回退、数据库约束、不可变计划/审批/证据/审计、跨实验关联、幂等并发与冲突、权限/范围、审批撤销与启动竞争、实际时钟过期、计划替代、状态/effects/outbox 故障回滚，以及快照一致性。

完整统一检查输出保存在 `reports/d03-validation.txt`。本地通过不等于 GitHub CI 已运行；上传/远端结果在 IMPLEMENTATION_STATUS.md 单独记录。没有执行设备、NATS、LLM、Web、现场验收。
