# ALAP 本地模拟容器部署

仅用于单机 **rootless Docker** 模拟环境，不能据此连接真机或宣称生产/现场验收完成。八个服务为 PostgreSQL、NATS JetStream、Gateway、Engine、Agent、outbox、API、Web；初始化是单独的维护任务。管理脚本拒绝 rootful Docker。本 profile 内服务使用 namespace UID 0（宿主机普通用户），配合只读根文件系统、cap_drop、no-new-privileges；生产 UID/Secret 管理不由此配置替代。

## 前置与网络

已验证本机 Docker 29.9.1、Compose 5.6.0、slirp4netns 1.3.6；二进制在忽略目录 `.local-deploy/bin`，不随仓库分发。内核须具备匹配的模块、用户命名空间、subuid/subgid 和 rootless 网络能力。官方镜像 CDN 在本环境仍有 TLS/EOF，按用户授权使用 DaoCloud 路径；`images.env` 固定四个镜像摘要，已与官方 registry 的对应标签摘要核对一致，不使用浮动标签部署。新的机器拉取这些摘要仍需网络可达。

在单独终端以前台方式启动运行时，`ALAP_DOCKER_PROXY` 必须是 rootless 网络命名空间可访问的代理地址：

```bash
ALAP_DOCKER_PROXY=http://10.20.205.15:7897 deploy/simulation/start-runtime.sh
```

此地址是本机实例配置，不适用于其它主机。回环 `127.0.0.1` 在 rootless 网络命名空间中指向其自身；不要直接复用宿主机回环代理。启动脚本将代理显式传给守护进程；`docker info` 可核对生效值。构建依赖下载另用 `BUILD_HTTP_PROXY`，不将其写为应用镜像 ENV。CLI 的 `config.json` proxies 不是本部署的 daemon 配置来源。

## 新部署顺序

从仓库根目录执行，`.venv` 已按锁文件安装依赖。准备的父目录必须已存在；目标目录须不存在。任何阶段失败保留现场，禁止自动删卷/覆盖凭据或把失败初始化当作成功继续。

```bash
.venv/bin/python deploy/simulation/manage.py prepare
BUILD_HTTP_PROXY=http://10.20.205.15:7897 .venv/bin/python deploy/simulation/manage.py build
.venv/bin/python deploy/simulation/manage.py initialize
.venv/bin/python deploy/simulation/manage.py up
.venv/bin/python deploy/simulation/manage.py status
.venv/bin/python deploy/simulation/verify.py
```

默认目录 `.local-deploy/simulation`，可用 `manage.py --directory /absolute/private/path` 改变；直接 Compose 与验证脚本对应设置 `SIM_ROOT`。构建使用静态 Docker 自带的 legacy builder（已实际验证），无需额外安装 buildx；`up --no-build --pull never` 使用本地已构建镜像。

- `prepare`：0700 目录、新随机数据库/消息密码、加密主密钥、签名密钥、区分 server/client 用途的 30 天模拟证书。CA 私钥不保留，过期后需完整更新信任材料；不能当作生产 PKI。PostgreSQL 引导密钥挂载只进入数据库容器，入口复制为数据库用户所有的 0600 文件；宿主机父目录限制为 0700。
- `initialize`：先准备有容量/保留边界的持久事件流，再创建专用数据库、显式迁移、四组件登录、服务主体、三个模拟设备、管理员和一个空实验。无模型凭据、审批或执行 Run。旧共享 runtime 禁用。仅维护任务挂载管理员/迁移凭据目录；其它组件只挂载自己的 DSN 和必要文件。
- 初始化生成 `admin.token`，有效期一小时，只在本地私有文件中保存。Web 在 **http://127.0.0.1:3000**，通过登录界面使用该 token；不要粘贴到日志/URL。过期后执行 `.venv/bin/python deploy/simulation/manage.py token`，通过受信任本地维护入口签发并原子替换私有文件，不在终端打印，不通过重跑 initialize 重置数据库；签发新 token 不撤销尚未过期的旧 token。
- API/Engine/Agent/outbox 的数据库连接均 `sslmode=verify-full`；数据库拒绝非 TLS 网络连接并使用 SCRAM。Gateway 仅接受 mTLS，API 与 Engine 有独立客户端证书，Agent/outbox 不在设备网络且没有签名密钥。
- API/Agent 的 artifacts 卷只读，Engine 可写；Gateway journal 与模拟物理状态、数据库、JetStream、artifacts 各自持久化。内部数据库、消息、设备网络不发布端口；正常 profile 仅 Web 发布宿主机回环端口。API/Agent 的 egress 用于后续显式配置的模型/MCP，当前无外部模型调用。

`initialize` 中断后不能盲目重试；检查 `/private/deployment` 完成标记与角色/数据库归属，按 D12c.1/2 故障说明人工处理。`up` 不执行迁移。已有部署更新须先停止业务服务，备份并用维护身份显式 migrate，再构建/启动；一致性冷备份与隔离恢复步骤见下方 D12c.3。

## 验证与停止

`verify.py` 只读检查 Web/认证代理、数据库 TLS/错误密码/明文拒绝、Gateway 缺少客户端证书拒绝、组件越权拒绝、API 数据卷只读与 JetStream 有持久事件。它要求初始化 token 未过期、空模拟环境没有执行命令；不把这项短测当作业务完整 E2E 或 24 小时长测。

全后端集成门禁可使用临时 QA 覆盖文件；它为 PostgreSQL/NATS 增加测试网络及**仅回环**端口 55432/54222。下面命令假设已导出 `SIM_ROOT`、`DOCKER_HOST`，且 `.local-deploy/bin` 在 PATH 中；Compose 使用 `--env-file deploy/simulation/images.env` 提供摘要。

```bash
docker-compose --env-file deploy/simulation/images.env -f deploy/simulation/compose.yaml -f deploy/simulation/validation.yaml up -d --wait postgres nats
.venv/bin/python deploy/simulation/check_backend.py
# 测试完成后恢复正常网络，移除 QA 端口；保留数据库/消息卷。
.venv/bin/python deploy/simulation/manage.py up
.venv/bin/python deploy/simulation/verify.py
.venv/bin/python deploy/simulation/manage.py stop
```

测试脚本只删除自己新建的随机 `alap_test_compose_*` 数据库；报告移除已知部署密码。不要在测试期间重建/重启 PostgreSQL/NATS。停止不删卷，不撤销已创建角色；运行时终端可在服务停止后退出。`docker compose down -v` 会丢失数据，不属于日常停止步骤。

当前验收范围和准确结果以 `IMPLEMENTATION_STATUS.md`、`reports/d12c2-compose-acceptance.md` 及 `reports/d12c3-recovery-acceptance.md` 为准。D12c.3 冷备份恢复已通过本地验收；D12d 完整平台 E2E/故障矩阵/实际长测，以及 D13 现场门禁仍须分别实施。

## D12c.3 一致性冷备份与隔离恢复

`operations.py` 仅适用于本地 simulation。备份按 Web/API/Agent → Engine/outbox → Gateway/NATS → PostgreSQL 顺序停止，确认没有运行中的卷使用者、没有强杀退出，且 PostgreSQL 控制文件为 clean shutdown 后，导出数据库、JetStream、Gateway 两个 SQLite 文件、HDF5 与私有配置。此时禁止绕过维护锁手动启动 Docker 服务。备份成功或失败均保持源服务停止，由操作员检查后显式 `manage.py up`。

以下路径均应是新路径；密钥不能位于备份目录或源凭据目录内。备份含加密后的全部凭据，独立随机 256 位密钥须另行妥善保存，丢失不可恢复。当前只生成本机文件；异地保管/密钥托管由操作员执行。

```bash
.venv/bin/python deploy/simulation/operations.py status
.venv/bin/python deploy/simulation/operations.py backup \
  --output /absolute/private/snapshot-001 \
  --key-file /absolute/private/keys/snapshot-001.key
.venv/bin/python deploy/simulation/manage.py up
.venv/bin/python deploy/simulation/operations.py restore \
  --bundle /absolute/private/snapshot-001 \
  --key-file /absolute/private/keys/snapshot-001.key \
  --directory /absolute/private/restore-001 \
  --project alap-restore-drill001
.venv/bin/python deploy/simulation/operations.py status --directory /absolute/private/restore-001
.venv/bin/python deploy/simulation/operations.py recover --directory /absolute/private/restore-001
.venv/bin/python deploy/simulation/operations.py stop-restore --directory /absolute/private/restore-001
```

AES-256-GCM 分卷流式加密，HMAC 认证清单最后写入作为完成标记；缺卷/损坏/错误密钥拒绝恢复。所有卷认证解密完成后才创建目标资源；归档仅接受普通文件/目录，拒绝路径逃逸、重复成员及链接。还原要求新目录、新 Compose 项目和本机仍保留的原始精确镜像 ID；没有镜像则先恢复可信镜像，不能静默换版本。未实现跨 PostgreSQL 大版本迁移。

还原只启动数据库，撤销复制的浏览器 token，并强制创建新 epoch、冻结旧 Run。隔离副本无宿主端口、无外部网络；不启动常驻 Engine/Agent/API/Web/outbox。`recover` 先停稳副本 Gateway，校验 COMMITTED 文件的校验和/来源，并在私有临时副本中检查 SQLite 数据库/WAL 完整性；随后只启动模拟 Gateway/NATS，再执行一次恢复对账；不会运行调度循环或自动 resume。Gateway 尚未就绪可在检查错误后再次执行 `recover`；UNKNOWN、未确认停止或文件损坏会保持恢复闸门关闭，不能通过重发设备动作来消除未知状态。检查成功后再次执行 `recover` 会拒绝重复开闸；副本仍无调度器。

`status` 输出真实服务运行/健康信息和 PostgreSQL 的 Run、Task、命令、数据集、Agent 状态计数、待确认停止、outbox 积压及最老事件年龄。数据库未运行返回 null，读取失败返回不可达；这些都不能视为健康。恢复关闭、未知命令、损坏数据和超过 60 秒的 outbox 会产生告警代码；年龄阈值是本地运维提示，不是已验证 SLA。它是按需 JSON 观测入口，未部署 Prometheus、告警推送或全天候监控。

失败时保留副本和卷供检查；不要对原部署执行 `down -v`。不完整恢复不能使用普通 `manage.py up`，须检查后换全新目标重新恢复。原始备份、失败副本与密钥由操作员按保留策略清理，程序不自动删证据。副本只验证模拟环境恢复；真实设备还须隔离旧控制端、重新 fencing、现场读回及授权后才能接管。本功能不是生产热备/WAL/PITR，也不能承诺零 RPO；可恢复点是最后一份成功冷快照，RTO 取决于数据规模与手工检查。

## D12d.1 实际部署浏览器验收

`check_browser.py` 对已启动的八服务运行真实 Chromium 验收，与 D10/D11 的独立 fixture 浏览器套件分开。它创建唯一未审批模拟计划，页面完成请求审批、批准、创建 Run、曲线查看和下载校验；额外验证观察者限制及 SSE 断开/重连。不会调用 LLM，也不预置执行 Run。测试令牌使用私有临时文件并在结束时撤销，业务审计和数据保留。

```bash
.venv/bin/python deploy/simulation/manage.py up
.venv/bin/python deploy/simulation/check_browser.py
```

Node/Playwright 浏览器安装、验收范围及后续 Agent/故障/24 小时长测顺序见 `docs/D12D_ACCEPTANCE.md`。成功报告为 `reports/d12d1-compose-browser.txt` 和 `reports/d12d1-compose-evidence.json`；失败退出非零，不自动重试设备任务。此入口只用于本地模拟开发部署，不是生产平台上创建审批和测量任务的运维入口。
