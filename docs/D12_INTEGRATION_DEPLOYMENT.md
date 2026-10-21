# D12 · 集成、部署与验收（进行中）

2026-10-19 从 GitHub D11 基线 `836ec53` 继续。D12a 的 Gateway 进程边界已验收，D12b 三个常驻服务工作项现已实现，验收结果见实施状态；下一项 D12c 部署运维；D12 整期尚未验收，不开启 D13。

## 实施顺序和当前边界

1. **D12a Gateway 通信与独立模拟进程**：网络 GatewayPort、签名绑定、单次发送、mTLS、持久 journal、进程重启对账、API 显式装配。本工作项实现，实际门禁见实施状态。
2. **D12b 常驻服务装配**：执行引擎单实例所有权、租约续期、启动恢复屏障；Agent 调用占位与检查点恢复；outbox 发布进程及可靠关闭。恢复过程中遇到 NOT_DISPATCHED 账本必须有明确的取消/对账政策，不能自动补发；UNKNOWN 不能盲重试。
3. **D12c 部署与运维**：Compose、受限数据库角色、初始化/迁移、Secret 文件、版本锁定和镜像清单、真实指标、备份与恢复演练。当前环境无 Docker/Podman，容器验证尚未进行；后续按需安装。
4. **D12d 集成验收**：常驻完整链路 E2E、故障矩阵、备份恢复与 24 小时以上实际运行模拟；记录 wall-clock 起止、负载、失败数、数据/命令一致性，不以逻辑时钟或短测代替。未通过项不得算完成。

## D12a 实现

- `adapters/gateway/transport.py`：固定 `POST /rpc`，仅允许 GatewayPort 的八个方法；外层 HMAC 绑定 gateway_id、operation、request_id、body，响应绑定同一请求。原有命令签名、审批/版本/租约/epoch/fencing/命令幂等规则不变。
- 只尝试一次；不跟随重定向、不使用环境代理、不自动重连重发。不可验证的结果/网络错误交给现有执行用例进入 UNKNOWN；恢复只调用 query/recover_command，不重发 accept。
- 请求最大 1 MiB、响应客户端最大 32 MiB；入站 body 10 秒截止；每个 Gateway 同时受理一个请求，忙时 503。稳定窗最长 30 秒、总采样预算 10000、最多 32 条条件，在读取/执行前检查；不修改已批准计划来满足限制。采样与动作在线程执行，HTTP 事件循环可拒绝并发请求。
- HTTP 只允许字面量回环地址。远端必须 HTTPS：校验 CA 和主机名；服务端非回环监听必须配置服务证书、私钥、客户端 CA。API 配置 HTTPS 时必须加载客户端证书。
- `adapters/gateway/server.py` 是独立模拟进程入口，只接受 `mode=simulation`；不含真实仪器驱动，不连接 PostgreSQL。journal 和物理模拟状态为两个 SQLite 文件，保留已有进程独占锁。进程启动不自动执行任何命令；SIGTERM 等待正在执行的操作后关闭。
- `adapters/gateway/config.py` 为 API/后续引擎创建端口；API settings 的 `gateway_transport` 可选，不配置时保留 D11 行为。配置端口不会注册设备、授予权限或自动创建 Run。

当前是一个模拟信任域、共享签名密钥；mTLS 已有本地证书验证，不代表完成多站点证书主体与设备身份注册、轮换/撤销或生产 PKI 验收。Gateway journal 仍使用 POSIX flock，本次仅 Linux 验证，未宣称 Windows 支持。

## 本地启动

从项目根目录生成开发配置（只生成随机 Gateway 签名密钥，与 LLM 凭据无关；重启复用同一个目录/密钥，不覆盖已有文件）：

```bash
.venv/bin/python - <<'PY'
import json, os, secrets
from pathlib import Path
root = Path('/tmp/alap-d12-simulation')
root.mkdir(mode=0o700, exist_ok=True)
key = root / 'gateway.key'
if not key.exists():
    fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(secrets.token_bytes(32))
revision = json.loads(Path('contracts/examples/plan_revision.json').read_text())
config = {
    'mode': 'simulation', 'gateway_id': 'gw', 'signing_key_file': str(key),
    'journal_path': str(root / 'journal.sqlite'),
    'physical_path': str(root / 'physical.sqlite'),
    'execution_skills': json.loads(Path('contracts/examples/simulator_skills.json').read_text()),
    'policy_versions': revision['policy_versions'],
    'capability_versions': revision['capability_versions'],
}
(root / 'gateway.json').write_text(json.dumps(config, indent=2))
PY
.venv/bin/python -m alap.adapters.gateway.server \
  --config /tmp/alap-d12-simulation/gateway.json --host 127.0.0.1 --port 8091
```

API 原有 settings 增加下列字段（运行账号必须能读取密钥；密钥原始字节不做 strip）：

```json
{
  "gateway_transport": {
    "signing_key_file": "/tmp/alap-d12-simulation/gateway.key",
    "endpoints": {
      "gw": {"url": "http://127.0.0.1:8091", "timeout_s": 60}
    }
  }
}
```

HTTPS endpoint 还需 `ca_file`、`client_cert_file`、`client_key_file`；服务端使用 `--cert`、`--key`、`--client-ca`。不得将文件内容放入源码、模型上下文或日志。远端部署及运维初始化属于 D12c。

以上 D12a 步骤仅启动网关并装配 API 端口。常驻引擎入口见 D12b.2；数据库主体/设备/审批仍需预先配置，不能据此宣称完整部署。

## 验证和下一动作

- `tests/test_gateway_transport.py`：真实回环 HTTP/TLS、签名/响应绑定、地址限制、客户端证书要求、超时/错误不重试、遥测预算、非法 RPC 方法。
- `tests/integration/test_gateway_process.py`：真实 PostgreSQL + 独立 Gateway 子进程 + 持久模拟状态，温度/磁场/IV → HDF5 提交 → 重启后核对；响应丢失 → UNKNOWN → 重启 → PAUSED，物理动作始终一次。
- `tests/integration/test_api.py`：已有实际 HTTP 工厂验收增加网络 Gateway 配置装配；API 公共契约、Web 及数据库迁移未改变。
- 后端统一门禁结果保存 `reports/d12a-validation.txt`；准确数量和最终结果见 `IMPLEMENTATION_STATUS.md`。

D12b.1 所有权/启动恢复、D12b.2 常驻执行进程及 D12b.3 Agent/outbox worker 见后续小节。D12 继续进行中。

## D12b.1 · 单实例所有权与启动恢复（2026-10-19）

新增 `PostgresEngineOwner`：持有专用连接和会话级 advisory lock，锁作用域按数据库/schema 区分；引擎事务须使用 `owner.transaction`。同一 schema 第二个进程不能成为 owner。事务失败会回滚；连接被终止或锁丢失时实例永久失效，禁止重新进入/重连，新实例必须重新恢复。不要通过 PgBouncer transaction pooling 等复用该会话。

`OwnedGateway` 在八个 GatewayPort 操作前检查 owner。检查后网络调用期间仍可能发生所有权变化，因此必须保留近端 epoch/fencing 和中央恢复屏障。本地测试验证的是数据库连接终止，不宣称已经覆盖所有网络黑洞/延迟场景。

`EngineRecovery.begin()` 建立全局 RECOVERING 并标记在途未知；`advance()` 做一轮持久回执查询和证据核对。缺 journal 不会触发 accept；UNKNOWN、待提交数据、未确认停止、缺配置或握手失败均返回阻塞信息。全部满足后才绑定新 epoch 并 finish_recovery。返回 ACTIVE 表示恢复闸门通过，不表示进程调度循环已启动，更不自动 resume PAUSED Run。

准备而未派发的 Run 按 `startup_cancel_unsent_v1` 处置：仅凭 NOT_DISPATCHED 不够，必须核对 delivery=PENDING 且没有 attempt ID；同 Run 的其它命令和停止均须已完成，任务无未决物理/数据工作。满足时取消剩余任务和整个 Run，保留已完成任务、不可变命令、原因、证据和 outbox 审计。用户后续可走正常授权流程创建新 Run；不自动制造一个新尝试重放旧命令。只允许已配置的引擎服务主体调用此恢复用例。

D12b.1 交付时是常驻引擎的前置组件与真实数据库验收；CLI 和调度循环在下方 D12b.2 实现。接线顺序为：进入 `PostgresEngineOwner` → 用 `owner.transaction` 构造 ExperimentService/ExecutionService → 将网络端口包为 OwnedGateway → EngineRecovery.begin/advance → 恢复成功后才允许后续调度；任何所有权丢失退出实例。不能将测试 fixture 内直接调用当作运行服务。

专项测试包括：真实第二进程锁冲突/释放、事务回滚、终止连接后八种 Gateway 操作均不触达远端、准备命令取消且动作 0 次、尝试派发无 journal 不重放、并行未知阻止取消、丢 ACK 对账后仍 PAUSED、矛盾 delivery 证据、未提交 IV 数据、缺 Gateway 配置、非法主体。

本工作项交付时的下一项为 D12b.2：将上述组件装配到常驻执行进程，加入受控调度、租约续期、停止/数据恢复处理和进程退出机制，再接 Agent/outbox worker；D12c/d 部署与长测门禁不变。实际统一门禁见 `reports/d12b1-validation.txt` 与实施状态。

## D12b.2 · 独立常驻执行进程（2026-10-19）

已增加 `python -m alap.adapters.engine.server --config <engine.json>`，它只装配确定性执行/控制/数据服务和网络 Gateway，不启动 LLM。已配置模拟模式、已迁移数据库、服务主体、Gateway/设备注册、已有用户批准并创建的 Run 是前置条件；启动不会自动授予权限或创建审批。

进程先取得单实例所有权，再执行全局恢复。未决回执通过查询核对；待确认 stop 使用原有授权记录和固定 stop_id；待提交采集按已有签名回执写入 HDF5、验证、提交并确认。数据写入失败保留原始命令，不重新采集；找不到 Gateway journal 时保持阻塞，不补发命令。新物理任务仅在下一轮且恢复闸门为 ACTIVE 时开始。

串行调度每 Run 每轮最多推进一个依赖满足的任务；每一步调用既有用例重新复核审批、范围、版本、读回和租约。默认租约 300 秒、轮询 0.5 秒；剩余时间低于租约一半时按原审批有效期续期。暂停不会自动 resume，合法租约可保留或重获；过期/失权不会自动恢复派发，需要按已有控制/恢复流程处理。已终结 Run 仅在 Gateway 当前 epoch 的新鲜静止报告核对后释放资源。

SIGTERM/SIGINT 设置停止标记，不再领取下个任务；已受理调用完成记录后退出。准备命令之后收到信号会留下 NOT_DISPATCHED，由下一实例按已定义的启动取消政策处置。退出不会向设备凭空发 stop，也不代表物理设备停止。独占锁冲突/数据库所有权丢失会以非零状态退出，不自动重连。默认日志只有状态、对象 ID 和错误码，不打印 DSN、密钥、设备参数或异常原文；相同状态去重，30 秒输出一次心跳。

### 启动配置

在 D12a 本地 Gateway 配置基础上生成中央引擎配置；API 和引擎必须使用同一个数据文件目录：

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
root = Path('/tmp/alap-d12-simulation')
gateway = json.loads((root / 'gateway.json').read_text())
engine = {key: gateway[key] for key in (
    'mode', 'execution_skills', 'policy_versions', 'capability_versions'
)}
engine.update({
    'engine_actor': 'engine', 'lease_s': 300, 'poll_s': 0.5,
    'artifact_root': str(root / 'objects'),
    'gateway_transport': {
        'signing_key_file': gateway['signing_key_file'],
        'endpoints': {'gw': {'url': 'http://127.0.0.1:8091', 'timeout_s': 60}},
    },
})
(root / 'engine.json').write_text(json.dumps(engine, indent=2))
PY
# 先通过已有配置设置 ALAP_DATABASE_URL，不要把真实凭据提交到仓库。
.venv/bin/python -m alap.adapters.engine.server \
  --config /tmp/alap-d12-simulation/engine.json
```

`ALAP_DATABASE_URL` 必须直连或使用 session pooling，不能使用 transaction pooling。上述目录是本地模拟示例，正式持久卷/数据库角色/迁移与初始化流程属于 D12c。CLI 只允许 `mode=simulation`，并不构成真实仪器写入授权。HTTP 仅回环；跨主机复用 D12a 的 mTLS 配置。

### 本轮验证和边界

`test_engine_worker.py` 验证完整 DAG/HDF5/资源释放、显式暂停恢复、租约过期隔离及续期、磁盘失败后只补交数据、prepare/dispatch 之间退出、启动数据恢复、已有取消确认、撤销审批后的静止确认、多 Run 串行竞争。`test_engine_process.py` 使用真正的引擎子进程和 Gateway 子进程，经 HTTP 完成三设备实验；验证正常退出、第二实例拒绝、已完成动作后强杀/重启保持 PAUSED，以及终止数据库 owner 连接后进程退出。

本阶段没有并行设备调度线程或租约续期专用线程；同步操作或队列过长可能导致其它租约过期，此时拒绝后续派发，不声称满足吞吐 SLA。设备调用超时仍可能产生 UNKNOWN，必须依靠回执对账。完整网络断连矩阵、常驻浏览器全链路、容器部署、备份恢复及 24 小时长测仍待 D12c/d。

本工作项交付时的下一项 D12b.3 为 Agent/outbox 常驻 worker（现见下节）；保留模型调用占位、不盲重试与数据库/outbox 权威语义。D12 整期继续进行中，D13 不启动。

## D12b.3：Agent 与 outbox 常驻 worker

本工作项提供两个独立进程，复用 D07–D09 的持久化、授权和模型配置，不创建 Agent Run、审批或设备命令：

- `python -m alap.adapters.agents.server --config <agent.json>`：轮询显式实验白名单内已有 READY/RUNNING Agent Run，每轮每 Run 最多推进一个逻辑步骤。按 ID 游标分页，跳过繁忙或已撤权 Run 后继续处理后面的 Run；终态不重新执行。原始提交者的成员关系、资源范围、不可变版本和预算继续复核，worker 主体不能代替提交者授权。
- `python -m alap.adapters.messaging.server --config <outbox.json>`：领取 PostgreSQL outbox claim，使用稳定 event_id 发布 JetStream，收到持久化 ACK 后才提交 published_at。默认每批一条，支持 1–100；断连指数退避，最长 30 秒。未确认 claim 在数据库中 30 秒后可重领，重复消息由 JetStream 去重窗口及消费者持久 inbox 共同处理，不承诺跨网络 exactly-once。顺序仍以数据库 experiment_seq 为准。

### Agent 并发及恢复语义

HTTP 手动推进、LangGraph 节点和后台 worker 统一通过 `AgentRuntime.step` 取得每 Run 的非阻塞 session advisory lock，手动取消使用相同锁。模型运行期间取消接口返回 RUN_BUSY；后台进程收到退出信号则通过本地取消标记终止当前模型流并保存 CANCELLED。已经受理的工具步骤完成记录后退出，不领取下一 Run。取消不等于供应商退款，也不代表已经发出的网络请求从未执行。

模型预算占位先持久化，再发起调用。锁会话同时承担 checkpoint/轨迹/提案提交事务，网络调用期间不持有数据库事务；锁连接死亡后不能换连接提交旧结果，进程非零退出。新进程遇到遗留 inflight 记录为 MODEL_INTERRUPTED，不重新调用供应商，需要用户创建新 Run。普通工具仍遵循既有只读/提案语义；外部 MCP 的既有调用账本及未知处理不变。没有全图独占锁，LangGraph 每节点和 worker 每步都复核状态，连续图可与其它合法推进交替。

worker 每批和每个 Run 前检查专用服务主体；主体撤销阻止下一次受理，已受理操作仍受原提交者权限校验。撤销成员关系导致 Run 无法写入时保留原记录并输出 FORBIDDEN，不用后台身份越权写成完成。CLI 不提供 Gateway 端口，不具有物理派发路径。

### 配置与启动

前置条件：数据库已迁移，使用直连或 session pooling；部署管理员显式配置 `issuer=alap-agents` 的 service 主体（示例 ID `agent-worker`）及 `issuer=alap-events` 的 service 主体（示例 ID `events-worker`）。不自动创建主体或授权。Agent 与 API 共享模型/连接配置、加密凭据主密钥及 artifact_root；流和 subject 须在 JetStream 预先建立。

以下由已有 engine.json 生成配置，实验 ID 和主体 ID 必须替换为实际启用值。启动 Agent worker 表示启用白名单中**已有及以后创建的**待执行 Agent Run，可能产生配置供应商的 API 费用；simulation 只限定仪器部署，不把真实模型变成离线模型。本轮开发测试全部使用离线替身，没有使用真实密钥或付费 API。

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
root = Path('/tmp/alap-d12-simulation')
engine = json.loads((root / 'engine.json').read_text())
agent = {key: engine[key] for key in (
    'mode', 'execution_skills', 'policy_versions', 'capability_versions', 'artifact_root'
)}
agent.update(agent_actor='agent-worker', experiment_ids=['EXP-SIM-001'],
             poll_s=0.5, batch_size=20)
(root / 'agent.json').write_text(json.dumps(agent, indent=2))
outbox = dict(events_actor='events-worker', nats_url='nats://127.0.0.1:4222',
              stream='ALAP_EVENTS', subject='alap.events', poll_s=0.5, batch_size=1)
(root / 'outbox.json').write_text(json.dumps(outbox, indent=2))
PY
# 沿用 API 的 ALAP_DATABASE_URL 与 ALAP_MASTER_KEY_FILE，勿提交实际凭据。
.venv/bin/python -m alap.adapters.agents.server --config /tmp/alap-d12-simulation/agent.json
# 在另一个进程运行：
.venv/bin/python -m alap.adapters.messaging.server --config /tmp/alap-d12-simulation/outbox.json
```

两个进程均处理 SIGTERM/SIGINT，停止新受理并收尾当前步骤；被强杀时依据占位/claim 恢复。默认日志只含状态、Run ID 和固定错误码，状态去重及 30 秒心跳；不输出模型内容、密钥、连接串或异常原文。Agent 数据库故障退出，由部署层决定何时重启；outbox 的可恢复连接故障在进程内退避。NATS 服务端认证、TLS 和容量/保留策略需部署配置，当前不提供企业凭据文件管理或自动建流。

### 验证与剩余边界

`test_background_workers.py` 使用真实 PostgreSQL 和 JetStream，验证离线模型/工具多步推进、实验白名单、服务身份与撤权、分页绕过不可访问 Run、手动/后台争锁、锁连接死亡后的提交拒绝及不重发、退出信号的当前调用取消、独立 Agent 进程恢复 inflight、独立 outbox 进程发布/重启/退出，以及丢 ACK 后重连去重。既有 Agent/API、MCP 和消息账本测试继续回归。claim 过期故障注入不是 24 小时长测。

本轮不新增依赖、迁移或公共 HTTP 契约，不注册系统服务，不提供并行模型吞吐 SLA；单个同步模型或 MCP 请求可能延迟同进程其它 Run。多个 worker 可通过每 Run 锁竞争，数据库查询尚无大规模队列压测。下一工作项为 D12c Compose、配置/运维与备份恢复；完整常驻平台 E2E 和真实经过 24 小时以上模拟仍属于 D12d，D12 整期未完成。

2026-10-20 续接验收：首次全量测试的两个 Gateway 用例在冷启动等待 10 秒内未就绪，单独复验通过。测试 fixture 将只读 challenge 就绪轮询延长至有界 30 秒，并在超时时记录进程状态/日志；不增加设备命令重试或修改业务超时。首次失败证据保留在 `reports/d12b3-validation-initial.txt`，最终统一结果见 `reports/d12b3-validation.txt`。

## D12c 分项实施顺序

D12c 按独立验收点拆分，避免把 Compose 文件存在当作可运行部署：

1. **D12c.1 数据库初始化与迁移/运行权限分离**：新建专用数据库、私有连接文件、显式迁移、受限运行账号和业务回归；本轮实现。
2. **D12c.2 组件权限与容器部署**：进一步划分各组件数据库权限、主体/设备初始化、Compose 网络/持久卷/Secrets、锁定镜像与实际构建启动。现有共用 runtime 角色不能代替这一门禁。
3. **D12c.3 运维与恢复**：数据库/数据文件/Gateway journal 一致性备份、恢复至隔离目标、恢复屏障演练、真实指标及操作手册。
4. 完成后进入 D12d 完整平台 E2E、故障矩阵与实际 24 小时以上长测；D13 不提前开启。

## D12c.1：初始化、显式迁移与私有数据库连接文件

提供 `python -m alap.adapters.postgres.deployment init|migrate`。仅用于新建专用数据库，不接管已有数据库，不覆盖现有角色、目录或凭据，不向日常服务自动注入管理员身份。初始化所用集群管理凭据须由部署管理员单独提供；本地集成验证使用隔离 PostgreSQL 超级用户执行创建，然后业务测试全部用新建的非超级用户运行。

### 权限模型与明确边界

| 身份 | 用途 | 已实现限制 |
|---|---|---|
| 外部集群管理员 | 一次性创建新数据库与两个角色 | 不写入生成的连接文件，不传给 API/worker；没有自动销毁或接管旧库命令 |
| `<name>_migrator` | 拥有专用数据库及 `alap` schema，显式升级 | LOGIN，但 NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOREPLICATION/NOBYPASSRLS；只交给维护流程 |
| `<name>_runtime` | 当前阶段的 API/Agent/Engine/outbox 业务访问 | 无角色继承关系；CONNECT、schema USAGE，业务表 SELECT/INSERT/UPDATE/DELETE，序列 USAGE/SELECT；不能改结构、TRUNCATE、禁用触发器、改复制模式、创建角色或 SET ROLE migrator；alembic_version 只读 |

撤销新库的 PUBLIC CONNECT/TEMP 及 public schema 权限；固定 search_path 为 `alap,pg_catalog`。应用函数对 PUBLIC 撤销 EXECUTE，由 migrator 显式授权 runtime。升级后刷新已有对象授权，新表不会仅因创建就自动向 runtime 开放；失败时不假装升级成功。已有不可变记录触发器在运行账号下继续生效。

**当前 runtime 是共享应用信任边界，不是各组件最小表权限或数据库行级用户隔离**。持有该连接的进程仍能直接读写可变业务表；用户/实验授权由应用层执行，不能把数据库凭据提供给浏览器或普通用户。第 13 章要求的 Agent/Engine/聚合层独立权限仍由 D12c.2 实现。迁移账号有意保留修改结构的能力，不交给常驻服务。其它数据库的 PUBLIC 权限和服务器认证策略仍由集群管理员管理，本命令不修改现有库或 pg_hba.conf。

### 初始化与显式迁移

部署名限定 `alap_[a-z0-9_]{1,32}`。输出目录必须不存在、父目录必须已由管理员准备；输出目录 0700，文件 0600。初始化生成独立随机密码，以 SCRAM-SHA-256 保存数据库角色密码。连接文件是明文 Secret，必须挂载只读并限制宿主机/容器读取权限；不包含原管理员密码。只复制 host/hostaddr/port、sslmode/sslrootcert、channel_binding、target_session_attrs 与连接超时等共享传输配置；拒绝管理员 passfile、客户端 sslcert/sslkey/sslpassword、service 和 session options，避免继承管理员身份。CLI 日志只打印固定事件和错误码，不打印 DSN 或异常 SQL。

```bash
# /secure 是部署管理员已准备的私有目录；admin.dsn 已单独配置，勿提交 Git。
# 文件可包含 libpq conninfo 或 postgresql:// URL；管理 DSN 不接受 service/options/passfile 或管理员客户端证书身份配置。
ALAP_DATABASE_URL_FILE=/secure/admin.dsn \
  .venv/bin/python -m alap.adapters.postgres.deployment init \
  --name alap_simulation --output /secure/alap-simulation

# migrate 从该目录读取 migration.dsn，不需要集群管理员凭据。
.venv/bin/python -m alap.adapters.postgres.deployment migrate \
  --directory /secure/alap-simulation
```

生成 `migration.dsn`、`runtime.dsn`、非秘密 `deployment.json` 和完成初始化的 `initialized` 标记。再次 init 同名数据库/角色或已有目录会拒绝；migrate 可重复运行，通过 Alembic 判断当前版本。迁移前验证连接的数据库、当前账号和 schema 与 manifest 一致。版本依赖仍使用已有 requirements-dev.lock，没有新增依赖或业务迁移。

创建数据库不能纳入角色创建事务，因此 init 失败可能留下部分资源及已生成的私有文件。此时不自动删除数据库/角色或覆盖凭据，不生成完成标记；migrate 拒绝不完整初始化。管理员须根据部署名检查 pg_database/pg_roles、私有 manifest 和服务端日志，确认资源归属后处理；不要靠反复重跑 init 接管未知状态。现阶段没有自动修复/删除命令。

### 常驻服务接线与维护流程

API、Agent、Engine、outbox 及 `scripts/provision_api.py` 统一支持 `ALAP_DATABASE_URL_FILE`。它与原 `ALAP_DATABASE_URL` 必须二选一；同时设置、两者皆空或空文件直接失败。保留原环境变量方式兼容已有开发/CI，但部署使用挂载文件。Alembic 也支持文件和 libpq conninfo，并保留原 SQLAlchemy URL；Unix socket、转义密码与 search_path 不通过字符串拼接生成 URL。

```bash
# 新 shell 中先清除旧 DSN，避免两个来源混用。
unset ALAP_DATABASE_URL
export ALAP_DATABASE_URL_FILE=/secure/alap-simulation/runtime.dsn
# 再按 D12b 的配置启动服务，例如：
.venv/bin/python -m alap.adapters.engine.server --config /secure/engine.json
```

初始化不创建业务 service 主体、设备、用户、审批、Run、LLM 连接或模型密钥；这些前置配置仍需明确初始化流程，不能把上述命令当作一键完整平台。升级前停止新的任务并等待安全点、停止不兼容版本服务、按后续备份政策保存恢复点，再显式 migrate；升级失败不自动切换到高权限账号或启动旧服务写新结构。备份恢复、Secret 轮换、生产 TLS 与自动化部署仍待后续工作项。

### 验证

`test_deployment.py` 对每次验证创建独立数据库与两个真实 PostgreSQL 角色；检查权限拒绝、迁移对象归属、新函数显式授权前不可调用、审计不可变、重复/失败初始化边界、显式迁移 CLI 脱敏输出，以及受限 runtime 下 API/Agent 离线模型、三设备确定性执行/HDF5 和 outbox 数据库发布闭环。发布测试使用 ACK 替身，真实 JetStream 行为由既有事件集成测试覆盖。`test_database_settings.py` 覆盖文件来源冲突和密码/Unix socket 转换。测试销毁仅限自身随机生成的数据库/角色。

本机测试 PostgreSQL 的 Unix socket 使用既有 trust 认证，因此本轮证据验证真实角色权限与 SCRAM 存储格式，**不宣称已验证网络密码认证、TLS 或容器 Secret 挂载**；这些纳入 D12c.2。统一结果保存 `reports/d12c1-validation.txt`。未运行容器、未注册系统服务、未调用付费模型或真实仪器。

## D12c.2：组件数据库权限（容器部署仍待验收）

在 D12c.1 的新库初始化后，停止使用共享 runtime 的服务，再由部署管理员显式执行：

```bash
ALAP_DATABASE_URL_FILE=/secure/admin.dsn \
  .venv/bin/python -m alap.adapters.postgres.deployment components \
  --directory /secure/alap-simulation
```

生成私有 `components/` 目录及 `api.dsn`、`engine.dsn`、`agent.dsn`、`outbox.dsn`；各服务的 `ALAP_DATABASE_URL_FILE` 分别指向自己的文件。完成标记写入后，旧 runtime 已 NOLOGIN，且撤销数据库/schema/对象权限。已有连接也失去对象权限；不要依赖 NOLOGIN 主动终止已有连接。迁移文件与管理员文件不挂载给业务进程。组件初始化不能重复覆盖角色或凭据；中途失败保留资源供管理员检查，缺少完成标记的目录阻止后续迁移，不能靠重跑覆盖修复。

| 组件 | 数据库能力 | 明确禁止 |
|---|---|---|
| API | 身份、配置、凭据、审批与控制操作；读取平台数据 | 插入执行命令、DDL；不是浏览器可持有的账号 |
| Engine | 执行任务、命令、数据与事件；更新 Gateway epoch/对账引用 | 读取模型凭据、创建审批、修改平台角色 |
| Agent | 读取授权上下文/模型凭据；写 Run、轨迹、提案、分析和 MCP 调用记录 | 写执行命令、改审批/身份/凭据、直接修改 MCP 授权 |
| outbox | 读取事件、写 claim/inbox/projection；仅更新事件 published_at | 伪造事件、改事件 payload、读 Agent 内容 |

权限白名单位于 `component_roles.py`，包含表与列两层授权；迁移后清除旧表/列 ACL 再重新应用。新增表不自动开放，组件无相互继承关系。API 仍是受信任管理后端，具备业务控制所需的较广写权限；这些账号不是数据库行级租户隔离，实验权限继续由应用逐次校验。

`d12_001` 提供固定 schema/search_path 的 SECURITY DEFINER 函数。`lock_read_record` 只锁定白名单记录、不返回数据或修改记录，检查调用身份的表读取权限，使 Agent 复核授权时无需获得授权表 UPDATE。MCP 调用前会刷新发现结果，专用 `refresh_mcp_discovery` 允许 API/Agent 更新工具清单并撤销失效授权；它不能恢复 revoked、改变授权范围或创建授权。新工具仍须管理员审核。两函数均撤销 PUBLIC EXECUTE，outbox/Engine 不获得 MCP 发现函数权限。

专项验证使用独立真实登录，包含越权拒绝、真实三设备/HDF5 执行、离线 Agent 提案、API 凭据管理、outbox 数据库提交、授权锁阻止并发撤权、迁移清除残留列授权，以及真实 HTTP MCP 调用/签名变化拒绝/旧签名返回后授权不恢复。全部仅使用模拟器和离线模型。统一报告为 `reports/d12c2-validation.txt`。

组件权限测试本身不证明容器镜像构建、Compose 实际启动、网络认证或挂载；这些独立部署门禁的后续实测见下节。持久卷保留不能替代 D12c.3 的一致性备份恢复，未进入 D12d。

### D12c.2 实际容器部署续接

`deploy/simulation/` 提供已经实际构建/启动验证的单机 rootless 模拟部署：显式 prepare → build → initialize → up → verify，初始化和日常启动分开。操作细节、代理配置、短期管理员 token、卷/证书边界及 QA 临时端口见该目录 README。四组件独立 DSN、PostgreSQL TLS/SCRAM、Gateway mTLS、NATS TLS/认证及 Web 同源 API 已在真实容器间核验；API/Agent 数据只读，业务服务不挂载迁移凭据。

历史内核模块不匹配问题在重启后解除。Docker 官方 CloudFront CDN 即使经代理仍失败，本轮使用用户授权的 DaoCloud 路径，四个锁定摘要均已与 Docker 官方 registry 核对一致；不关闭 TLS 校验。新环境需复核 rootless 网络和代理地址，不照搬本机地址。普通服务仅 Web 绑定宿主机回环端口；后端集成测试的 PostgreSQL/NATS 回环映射仅由 QA 覆盖文件临时开启，完成后恢复正常配置。

本轮 547 项统一后端回归在真实容器 PostgreSQL/JetStream 上通过，报告 `reports/d12c2-compose-backend-validation.txt`。容器内 Python 3.14.8、Node 24.22.0、PostgreSQL 18.6、NATS 2.15.1；宿主测试 Python 3.14.7。该回归与跨容器验收范围不同，两者记录在 `reports/d12c2-compose-acceptance.md`。下一工作项为 D12c.3 运维与一致性备份恢复；完整 E2E、故障矩阵、实际 24 小时以上模拟仍属于 D12d。

## D12c.3 运维恢复实现边界

运维入口与操作顺序见 `deploy/simulation/README.md` 的 D12c.3 章节，决策见 ADR-053。代码分为独立加密归档适配器、只读状态/完整性审计和 Compose 维护编排；不向领域层引入 Docker、数据库或加密依赖。恢复强制 epoch 是现有引擎恢复用例的显式选项，普通重启维持原行为。

验收分别检查加密/路径拒绝、真实数据库恢复闸门/COMMITTED 文件损坏、实际 Compose 的加密冷备份和隔离恢复。对应 `tests/test_backup_archives.py`、`tests/integration/test_operations.py`；实际执行结果以实施状态和恢复演练报告为准，不把设计或单元测试等同于系统验收。关联 FR-009 命令对账、FR-011 数据完整性以及第 13 章部署恢复要求。D12d 的完整 UI/业务 E2E、故障矩阵与 24 小时以上负载仍须另行实施。
