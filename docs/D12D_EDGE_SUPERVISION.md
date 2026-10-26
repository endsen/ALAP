# D12d.3 近端监护基础（第 30 批）

关联 EVAL-09、FR-009、第 11 章设备分类与独立保护原则。当前完成独立模拟模块和故障测试，**不是现有 Gateway/Engine 执行链的失联保护，也不是 EVAL-09 整项通过**。

## 已实现边界

SimulationLossPolicy 绑定版本、0.1–60 秒模拟超时以及三个固定设备策略：源表 zero_output，磁体/温控 hold；拒绝把源表停机套用所有设备。策略使用不可变副本，已有状态文件拒绝静默换版本。

独立 edge_server 进程使用专用 SQLite 输出模型，不能复用现有 simulator/journal 数据库。一个状态文件只有一个监护 owner；读写使用事务及持久同步。状态为 WAITING → ARMED → TRIPPED。心跳绑定当前 generation 和递增整数 sequence；旧世代、重复、布尔或越界序号拒绝，不延长期限。超时用单调时钟，审计另存 UTC 时间、策略、原因、故障前输出与分类动作。

scan、heartbeat 和 write_output 都检查失联；对外返回拒绝前先提交锁存，避免异常回滚导致故障消失。监护停止推进或单调时钟回退也锁存；源表模拟值归零，温控/磁体保持值。锁存只能通过精确 incident/generation 的本地显式确认转入 WAITING，新世代和新心跳仍不会自动恢复输出。重启视为监护空档，锁存保留，历史审计不删；正常停止已启用监护也锁存。

本地确认的 operator/reason 是审计字段，**不是已认证身份**。这些 Python 端口仅供私有模拟研究，不是授权网络接口，不得直接暴露给 Web/Agent/MCP。新模块没有加入默认 Compose、Gateway server、Engine worker 或实际设备驱动。

## 验证与局限

tests/test_edge_supervision.py 验证策略、心跳防重放、三种超时检测边界、锁存事务、确认/不自动恢复、限值、owner 互斥、错误库拒绝和审计失败回滚。tests/test_edge_process.py 使用独立进程与真实经过时间，覆盖持续心跳后静默、SIGSTOP 监护停顿、SIGKILL 后重启与显式重新启用。

软件监护本身被杀死时不能主动改变输出；重启后处理或仍存活的调用方检测不能替代硬件保护。SQLite/审计故障会使事务回滚、调用报错，不能证明真实仪器已停止；没有硬实时延迟保证。本模型仅模拟输出值，没有源表在途扫描、部分 Dataset 或真实执行命令。

## 接线前必须完成

1. 将监护状态与实际模拟器输出模型统一，持续 IV 扫描与监护不得共享阻塞整个操作的执行锁；中途终止要持久保存结果且不发布部分数据。
2. Engine 所有权/epoch 绑定的认证心跳独立于阻塞执行 RPC；旧 owner、旧 epoch、重放、租约过期不能续命，权限/身份不可仅靠上述本地字段。
3. Gateway journal、中央 UNKNOWN/对账、任务/运行及停止结果打通，不能因心跳恢复而重发未知命令或恢复运行。
4. 经受控 API/维护身份确认故障，验证权限、读回、锁存、重启/网络故障及恢复链，再评审 C 级部署；现场阈值、动作与互锁仍须 G1/G2。

## 第 31 批：可选执行链接线（2026-10-26）

以上“未接入”描述是第 30 批基础交付边界，本批增量已把前述第 1–3 项接入可选模拟运行路径，仍未完成第 4 项或 EVAL-09 整项验收。

- 独立 monitor、Gateway、Engine 三个实际子进程运行；SupervisedSimulator 以 edge_outputs 为读回依据，IV 逐点等待并在结束时源表归零。写入前持久化动作身份，连续采集中断只留事故和部分点数，不提供可提交的 artifact。Gateway 被杀死时由仍存活的 monitor 归零；重启后显式对账才收敛失败，不重发动作。
- Engine 仅在 accept 调用存续期间发送心跳；专用随机密钥与命令密钥分离，且不向 API/Agent 提供。每次检查同一数据库会话 advisory lock、控制 epoch/ACTIVE、提交人的有效审批、资源租约/隔离/fencing/策略/能力、运行调度门禁。检查失败停止心跳；数据库阻塞亦可能触发超时，不承诺实时性。
- `/supervision` 独立于 `/rpc` admission 和设备操作锁；仅有状态与心跳两个操作，无确认或输出写接口。TLS 部署沿用证书绑定；loopback HTTP 仅用于本地模拟。心跳严格绑定活动 command_id/epoch/generation，序号递增，UTC 有效期最多 2 秒；命令结束后的旧心跳不能重新 ARMED。命令自身 deadline 在监护端强制执行。
- 中断签名回执是 FAILED_CONFIRMED；中央用已有对账转换保存命令失败、任务失败和 Run 暂停/冻结。运行中的直接失败回执和重启后 UNKNOWN 对账均覆盖。锁存时禁止绑定新 epoch，恢复停在 RECOVERING；不会自动确认事故或恢复输出。

### 显式本地配置

先启动 `python -m alap.adapters.gateway.edge_server --config <edge.json>`；edge.json 包含 mode=simulation、独立 state_path 和 loss_policy（version、timeout_s、三个固定设备策略）。Gateway 配置增加 `supervision` 对象：state_path 指向同一个监护数据库，heartbeat_key_file 指向独立的至少 32 字节随机文件，sample_interval_s 在 0.01–1 秒内。Engine 的 gateway_transport.endpoints 对应 Gateway 增加相同 heartbeat_key_file。不得将此密钥加入 API/Agent 配置。只在独立新建的模拟状态目录启用；不要复用既有未受监护物理动作库。

实际心跳周期约 0.1 秒，接口超时 1 秒；策略 timeout_s 须按本机负载选择并验收，不能视作硬实时阈值。默认 Compose 不生成上述配置、密钥或 monitor 服务。

### 本批验证与下一门禁

`tests/test_edge_command.py` 覆盖活动命令/epoch/世代、过期/重复心跳、命令完成后拒绝续命、deadline 不可延长、未完成动作禁止确认。`tests/integration/test_edge_execution.py` 覆盖正常跨超时窗口采集并 COMMITTED、阻塞 accept 期间心跳通道可达、命令密钥无法访问心跳、错误心跳密钥、Engine SIGKILL、PostgreSQL 会话所有权失效、Engine/Gateway 中断与 Gateway 显式恢复。每项确认无重复动作，失败路径无 Dataset 发布。

尚待：认证维护身份与恢复 API；真正网络分区、监护/存储故障在执行链的组合验收；取消/暂停与中断的更多竞态；C 级 Compose/mTLS 部署复验。磁体/温控中断保持并要求设备特定对账，不能使用源表“已静止”证据。软件监护和共享 SQLite 损坏仍不能证明真实设备安全；G1/G2、长测与现场未开始。

## 第 32 批：人类维护身份与受控恢复（2026-10-26）

本批完成可选模拟路径的维护 API 和认证委托（ADR-057），取代前述“无网络确认端点”的历史状态；私有 Python 端口仍不能视为身份授权。

- `GET /api/v1/maintenance/gateways/{gateway_id}/edge`：仅启用的人类 admin 可查看事故、世代、Gateway epoch、策略、三设备读回、监护扫描鲜度、最近确认审计及中央恢复状态。
- `POST /api/v1/maintenance/gateways/{gateway_id}/edge/acknowledgements`：必须带 Bearer 和 Idempotency-Key；请求按 `contracts/edge_ack.schema.json` 提交 incident、generation、gateway_epoch、policy_version、expected_outputs、reason。actor 从认证主体产生，客户端不得指定或伪造。人类 admin 权限在缓存重放前也重验。
- 中央要求 RECOVERING、所有命令终态及停止请求 CONFIRMED；先保存 `edgeAcknowledgementIntent`，包含 review_id、操作者、事故/读回/原因、中央 epoch 和短期授权。不会在 API 内启动恢复、重放未知命令或修改 Run。
- Gateway 要求独立维护密钥，检查授权最多 10 秒、Gateway epoch 和本地命令终态，并与执行/握手互斥。monitor 确认事务要求无活动命令、扫描未过期且时钟未倒退、源表为零、全部读回与策略等于审查值；世代变化、过期、审计失败均拒绝。确认和监护审计同事务提交，转 WAITING，输出不变。
- API 与 Gateway 间失去确认回复时不自动重试。相同 Idempotency-Key 保持 EXECUTION_UNKNOWN；使用 GET 的 last_acknowledgement.detail 中 review.review_id 与中央意图核对。此字段是历史审计，不能替代当前 mode/incident；已完成幂等响应同样只代表当次历史结果。
- Engine 可以随后完成原有恢复握手，但旧 Run 保持 PAUSED，失败命令/任务不重试，部分 Dataset 不发布。Gateway 崩溃留下的非终态 journal 必须先走已有显式 recover_command。

### 本批配置与验收边界

在 Gateway 的 supervision 对象增加 `maintenance_key_file`；API 的 gateway_transport.endpoints 对应项增加同一路径或同值密钥文件。密钥至少 32 字节且独立于签名/心跳密钥，仅装配到 API 与 Gateway，不给 Engine/Agent。未配置时公共维护请求返回服务不可用，Gateway 不开放 `/maintenance`。旧 Compose 不自动生成密钥、授权或监护服务。

维护前应先停止接入/确认需处理事故，启动现有 Engine 显式恢复流程，使中央进入 RECOVERING；先对账所有未知命令与停止请求，再读取维护状态，审查分类读回后提交精确确认。确认后再次读取当前状态并检查 Engine 恢复结果；不能把 HTTP 200 当作运行恢复授权。直接修改 SQLite 不是该身份流程的一部分。

本批测试是本机 HTTP API + PostgreSQL + 三个独立模拟进程，不替代 C 级 mTLS/Compose 验收。维护委托存在最长 10 秒有效窗口，权限撤销在签发前与幂等读取时复查，不能保证已发出的短期授权即时撤回。真正网络分区、执行中监护/存储组合、取消/暂停竞态及现场 G1/G2 仍待后续，不进入长测。
