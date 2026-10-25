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

### 常驻 Agent 的离线模型验收（D12d.2）

正常八服务运行且 Chromium 已安装时：

```bash
.venv/bin/python deploy/simulation/check_agent.py
```

该入口在专用 internal 网络中启动本地 TLS/SSE 替身与限定实验的 worker，通过真实模型适配器验证 OpenAI/DeepSeek 请求格式和提案到人工审批执行的浏览器链。不会调用官方模型；不要提供真实 API key。私有测试 CA、令牌及临时 Compose 文件仅存 `.local-deploy/`，finally 回收容器和访问权限，保留业务记录。详见 `docs/D12D_ACCEPTANCE.md`。

全套 Web 回归可在 `validation.yaml` 的隔离 QA 端口启用后运行：

```bash
PLAYWRIGHT_BROWSERS_PATH="$PWD/.local-deploy/browsers" \
  .venv/bin/python deploy/simulation/check_backend.py --web --report reports/d12d2-web-validation.txt
```

该命令使用随机临时测试数据库，结束后删除；不使用部署业务库。完成后恢复正常 Compose 配置，关闭 QA 端口。

### 消息服务中断演练（D12d.3）

确认八服务运行、无活动 Run/outbox 积压后执行：

```bash
.venv/bin/python deploy/simulation/check_messaging_fault.py
```

这会短暂停止本地 NATS，在唯一测试实验保存未审批计划，核对数据库待发布事件与 API 快照，再恢复 NATS 并重启 outbox 核对无重复消息；不会创建执行 Run。finally 恢复服务、撤销令牌，业务审计保留。强制结束宿主进程不保证 finally，续接必须检查 NATS/outbox 状态。报告及剩余边界见 `docs/D12D_FAULT_MATRIX.md`。

独立 Engine/Gateway 的 TCP 故障专项需要开启 `validation.yaml` QA 端口，可运行：

```bash
.venv/bin/python deploy/simulation/check_backend.py \
  --pytest tests/integration/test_wire_faults.py --report reports/d12d3-wire-faults.txt
```

专项用随机隔离测试库、独立子进程及 loopback HTTP proxy，不对正常部署 Gateway 注入故障。完整验收后仍须运行统一门禁并恢复正常 Compose 配置。

### 模型故障与运行期 Skill 撤销（D12d.3）

八服务运行时执行：

```bash
.venv/bin/python deploy/simulation/check_model_faults.py
```

该入口持有维护锁，使用本地隔离 TLS 供应商和真实常驻 Agent，分别对 OpenAI/DeepSeek 格式注入越权工具、截断流、429、缺失 usage、禁用凭据及响应期间撤销 Skill，共 12 项。无需 Chromium，不调用官方 API，不需要真实 key；官方 HTTPS 白名单不变，测试 CA 只进入隔离 worker。该入口不请求审批、不创建执行 Run。

成功证据保存至 `reports/d12d3-model-faults.json`。finally 停服务、经应用取消未终结的测试 AgentRun、禁用专属测试配置和 Skill、撤销令牌，保留审计；强制终止宿主进程仍须人工检查清理。具体边界和剩余故障项见 `docs/D12D_FAULT_MATRIX.md`，不等同完整 D12d.3/长测通过。

### 批准后计划变更（D12d.3）

八服务运行且无活动执行 Run/outbox 积压时：

```bash
.venv/bin/python deploy/simulation/check_plan_fault.py
```

该入口经真实 API 批准模拟计划，再修改温度目标与读回条件，验证旧审批失效、旧快照和旧审批启动请求分别被拒绝。常驻 Engine 保持运行；不创建执行 Run，检查设备命令增量为零。维护锁防止与其他演练并发，finally 撤销短期令牌，保留审计。报告为 `reports/d12d3-plan-evidence.json`。这是本地模拟验收，不代表运行中计划变更或现场审批验收。

### 独立进程数据存储故障（D12d.3）

开启隔离 QA 端口后运行：

```bash
.venv/bin/python deploy/simulation/check_backend.py \
  --pytest tests/integration/test_data_process_faults.py --report reports/d12d3-data-process.txt
```

专项使用随机数据库和临时文件，在独立 Engine/Gateway 采集期间制造真实存储路径错误，验证恢复提交及重启无重复采集，并检查已提交文件缺失/损坏时的读取拒绝。不会修改部署业务文件；读取断言是服务集成层，非部署浏览器。完整门禁后恢复正常 Compose 配置、关闭 QA 端口；边界见 `docs/D12D_FAULT_MATRIX.md`。

### 部署数据接口完整性（D12d.3）

八服务运行、无活动执行 Run 时：

```bash
.venv/bin/python deploy/simulation/check_data_fault.py
```

入口会经真实 API 批准并执行一个新模拟实验（三条命令），仅对其新生成文件注入缺失/损坏，核对清单、下载和曲线接口拒绝，再恢复精确字节并复验。持有维护锁，finally 恢复文件和撤销测试令牌，业务审计保留；不需要 LLM 或真实设备。报告 `reports/d12d3-data-api-evidence.json`。强制终止可能留下对应 HDF5 的 `.fault-backup`，须先按本次 dataset 的 checksum 校验恢复，不能重跑采集代替恢复。范围与未覆盖项见故障矩阵。

### 部署数据浏览器错误及恢复（D12d.3）

安装已有锁定 Chromium，八服务运行且无活动执行 Run 时运行：

```bash
.venv/bin/python deploy/simulation/check_data_browser.py
```

它复用数据 API 演练生成新模拟数据，在缺失/损坏文件期间运行真实 Chromium，验证错误提示、下载禁用、无曲线；通过私有文件屏障协调文件恢复，再在同页重试并下载核对 SHA-256。无需真实 LLM/设备。报告使用独立 `d12d3-data-browser-*` 文件，不覆盖 API 历史报告。强制中断后的文件恢复要求与数据 API 演练相同，正常 finally 回收文件备份、浏览器状态和令牌。

### 独立进程异常读回（D12d.3）

开启隔离 QA 端口后：

```bash
.venv/bin/python deploy/simulation/check_backend.py \
  --pytest tests/integration/test_telemetry_process_faults.py --report reports/d12d3-telemetry-process.txt
```

隔离测试代理注入过期窗口、斜率超限和零磁场目标的错误读回，验证后继零派发，恢复后动作不重复。使用测试签名密钥与 loopback HTTP，不修改系统时钟或正常部署。测试覆盖来源合法的异常读回，不替代认证攻击/mTLS/真机验证。完整门禁后恢复正常部署并关闭 QA 端口。

### 活动写入进程中断（D12d.3）

启用上述 QA 网络后可执行：

```bash
.venv/bin/python deploy/simulation/check_backend.py \
  --pytest tests/integration/test_upload_process_faults.py --report reports/d12d3-upload-process.txt
```

使用测试专用启动器定位两个 fsync 边界并 SIGKILL 独立 Engine；重启后验证同一 Dataset 提交与零重复采集。只作用于随机测试库/临时文件和模拟 Gateway，不修改产品启动器。该测试不证明断电耐久性；强杀遗留的临时文件自动回收仍是缺口。完整记录见 `reports/d12d3-upload-acceptance.md`，测试后恢复正常 Compose 网络。

### 知识检索/撤权进程验证（D12d.3）

启用 QA 网络后执行：

```bash
.venv/bin/python deploy/simulation/check_backend.py \
  --pytest tests/integration/test_knowledge_process_faults.py --report reports/d12d3-knowledge-process.txt
```

真实 PostgreSQL、独立 fork AgentWorker，模型在子进程内使用离线替身，父进程受控驱动 tick；不是 Compose Agent/HTTPS 模型验收。验证检索注入、两种撤权时机与正常对照，并显式记录撤权后 RUNNING 未收尾缺口。运行结束后恢复正常 Compose 网络，详见 `reports/d12d3-knowledge-acceptance.md`。

### 知识撤权终态收尾回归（D12d.3）

启用 QA 网络后执行：

```bash
.venv/bin/python deploy/simulation/check_backend.py \
  --pytest tests/integration/test_knowledge_process_faults.py tests/integration/test_revoked_source_closure.py tests/integration/test_resources.py \
  --report reports/d12d3-revocation-closure-targeted.txt
```

本批修改运行时与 PostgreSQL 适配器，修复知识撤权后的 RUNNING 滞留；仍禁止读取撤权历史。测试包含真实审计 INSERT 失败回滚、所有权连接终止及并发取消，不使用线上模型。源码验证不自动更新部署镜像；应在后续部署知识链路验收时构建新镜像并补 API/页面证据。运行后恢复常规 Compose 网络，详见 `reports/d12d3-revocation-closure-acceptance.md`。

### 撤权状态视图部署验证（D12d.3）

完整后端/Web 门禁通过并构建、启动新镜像后执行：

```bash
PLAYWRIGHT_BROWSERS_PATH="$PWD/.local-deploy/browsers" \
  .venv/bin/python deploy/simulation/check_revocation_view.py
```

创建独立实验及 fixture 来源绑定的 READY AgentRun，通过 API 撤销来源，再用独立数据库网络容器内的 AgentWorker 单次 tick 收尾。真实 Chromium 验证等待提示到 FAILED，API 验证最小字段、轨迹/提案拒绝；模型调用与设备写入均为零。并未运行模型检索或响应中撤权。临时状态保存在私有目录，结束时撤销令牌、禁用测试配置；业务审计保留。完整记录见 `reports/d12d3-revocation-view-acceptance.md`。

### 实际检索与 HTTPS 知识撤权（D12d.3）

常规模拟部署启动后执行：

```bash
.venv/bin/python deploy/simulation/check_knowledge_faults.py
```

OpenAI/DeepSeek 两格式各三个案例，通过真实 API 导入来源、创建 AgentRun；专用常驻 worker 真实检索，再经隔离 HTTPS/SSE 替身返回总结或越权工具。撤权屏障位于第二轮响应发送前，API 撤权完成后才释放。校验来源 hash、两轮请求、终态收尾/不重放与零提案/设备写入。不调用线上 API、不提供浏览器证据；结束后删除专用容器/网络并禁用配置、撤销令牌，审计保留。报告 `reports/d12d3-knowledge-https-acceptance.md`。完整门禁应与部署演练串行运行，避免同机资源争用。

### 非法用量与实际 HTTPS 流停滞（D12d.3）

```bash
.venv/bin/python deploy/simulation/check_streaming_faults.py
```

OpenAI/DeepSeek 各覆盖负数、布尔值、总量不一致 usage，以及发送第一个不完整工具分片后保持连接六秒。专用 profile 为 timeout_seconds=2、max_attempts=1；验证真实常驻 Agent FAILED/MODEL_FAILURE、预算预留保留、无成功模型事件/工具提交/设备写入，每项只有一次 HTTPS 请求。不是在线 API、取消或多次重试验收。入口自动清理专用容器、配置和令牌，审计保留；完整后端门禁须串行运行。证据见 `reports/d12d3-streaming-https-evidence.json`。

### HTTPS 重试上限与部分输出后禁止重试（D12d.3）

```bash
.venv/bin/python deploy/simulation/check_retry_faults.py
```

两供应商各运行连续 429、部分 SSE 后超时，专用 profile 为 timeout_seconds=2、max_attempts=3。真实 HTTPS 请求数分别应为 3、1；全部 FAILED/MODEL_FAILURE，预算预留保留，工具/提案/执行写入为 0。与单次超时专项共享断言，但报告独立保存为 `reports/d12d3-retry-https-evidence.json`。不覆盖取消、重试后成功或预算耗尽。完整门禁与演练串行执行，随后恢复常规 Compose 网络并核对清理。

### Agent 取消 API 与实际部署页面（D12d.3）

```bash
PLAYWRIGHT_BROWSERS_PATH="$PWD/.local-deploy/browsers" .venv/bin/python deploy/simulation/check_cancellation_faults.py
```

需要包含 d12_002 的新后端/Web 镜像和已显式升级的数据库。两供应商各覆盖调用前取消、部分 SSE 后 API 取消、部分 SSE 后 Chromium 页面取消，共六项。专用 profile timeout_seconds=90/max_attempts=1，替身在第一片后等待本机 release 文件；只有 API/浏览器确认 RUNNING + cancel_requested 后才释放剩余合法响应。最终 CANCELLED，未提交模型结果/工具/提案；调用前请求 0、运行中请求 1。页面等待确认时禁用重复操作，实际 worker 确认后才显示 CANCELLED，无网络 mock/手动 advance。

当前入口写入 `reports/d12d3-cancel-deploy-evidence.json` 和两份供应商浏览器日志。第十五批 `d12d3-cancellation-api-*` 是旧版 RUN_BUSY 的历史证据，不能覆盖或作为新版验收。专用 worker/网络、配置和令牌自动清理，历史取消请求与审计保留。该证据不是即时 socket 中断、真实线上模型、MCP 远端副作用回滚或现场设备停止。

### Agent HTTPS 调用期间强制中断/重启（D12d.3）

```bash
.venv/bin/python deploy/simulation/check_agent_crash.py
```

仅对临时 agent-drill 容器发送 SIGKILL；常规服务不作为故障目标。两供应商各覆盖保存取消意图后中断、未取消直接中断。等待实际 HTTPS 首片与 model_reserved 后，验证退出码 137/非 OOM、停机期间仍为 RUNNING，重启后分别 CANCELLED 或 FAILED/MODEL_INTERRUPTED。再次重启并等待新进程空 tick，状态/轨迹不变，每项 HTTPS 请求保持 1、工具/提案/执行写入 0。报告 `reports/d12d3-agent-crash-evidence.json`；不声称操作系统自动重启、物理断电或已提交工具恢复验收。

### 重试成功、累计预算及用量读取（D12d.3）

```bash
.venv/bin/python deploy/simulation/check_retry_budget.py
```

两供应商各覆盖首次 429 后只读总结成功、48,000 预算下禁止继续重试、4,096 预算下调用前拒绝。预算场景在合法目标中加入 15,000 字节内容，替身只记录按客户端规则计算的每次预留数，不记录完整 payload；逐项校验累计预留边界与实际请求数。成功响应只有一次 usage，完成统计含两个唯一尝试 ID；三次重复 GET 及 worker 重启后用量/轨迹不变。报告 `reports/d12d3-retry-budget-evidence.json`。这些数字是保护性预留和替身报告用量，不是供应商实际账单。

### 模型能力/Skill 版本绑定（D12d.3）

```bash
.venv/bin/python deploy/simulation/check_version_faults.py
```

两供应商各验证模型新版本、旧模型禁用、Skill 新版本。创建 READY 运行后暂缓专用 worker，通过正式 API 操作新版本及覆盖负路径，再启动真实 worker。新版模型声明不支持工具时新 Agent 发布被拒；旧模型禁用后即使有可用新版也不自动切换；新 Skill 不替换旧运行绑定。TLS 替身核对真实消息包含旧 instruction 标记且没有新标记。全部版本/令牌均清理，保持历史审计。报告 `reports/d12d3-version-binding-evidence.json`；不等于线上供应商能力探测。

### 已提交工具边界的恢复（D12d.3）

```bash
.venv/bin/python deploy/simulation/check_tool_recovery.py
```

专用 worker poll_s=5，等待真实 checkpoint 进入 tools/iterations=1（模型已提交工具请求）或 model/iterations=1（read_snapshot 结果已提交），然后只对 agent-drill 发送 SIGKILL。停止后再次比对数据库边界，若下一 tick 已抢先推进则失败。新进程恢复后应完成两次 HTTPS、一次 read_snapshot 和一次 PROPOSED 提案，计划/审批/执行写入 0；第二次重启检查状态、轨迹、ledger、提案完全不变。入口不调用手工 advance、不注入 checkpoint。证据 `reports/d12d3-tool-recovery-evidence.json`。不覆盖 MCP 外部调用、提交事务内部中断或自动重启策略。

### Agent 部署权限矩阵

运行 `.venv/bin/python deploy/simulation/check_permissions.py`：为两种供应商格式分别创建真实 HTTPS/常驻 worker 产生的完成运行和未审批提案，再使用独立 observer/operator/approver/outsider 身份及匿名请求检查 HTTP 权限。每供应商 49 项断言，包含非提交人的详情/轨迹/提案/取消/推进拒绝、列表与用量隔离、实验外/匿名拒绝，以及 API 成员撤权后即时拒绝。提交人状态/轨迹/提案保持不变，零设备执行写入。测试身份、令牌和成员权限在 finally 中禁用/撤销；仅操作随机命名的隔离实验。不代表运行中提交人撤权、MCP 撤权或浏览器权限矩阵已完成。

### 提交人权限失效的部署收尾

在包含 `fail_revoked_access` 的新后端镜像上运行 `.venv/bin/python deploy/simulation/check_access_revocation.py`。两供应商格式各三项：非管理员实验 operator 调用前成员撤权、真实 HTTPS 首片后成员撤权、首片后设备范围缩减。使用真实成员 API 提交变化，先确认读取/取消 403，再释放本地 TLS 模型流；只读数据库核对受限 FAILED/ACCESS_REVOKED 和无工具/提案/设备执行写入。重授权后读取终态、重启 worker 等待空 tick，确认状态/轨迹/请求数不变。调用前请求 0，流中各 1。维护锁及 finally 清理专用容器、网络、身份、令牌、成员权限和测试配置；异常遗留运行按受限收尾路径处理。不覆盖主体禁用、MCP 特定授权撤销、所有角色/字段/页面或真实在线模型。
