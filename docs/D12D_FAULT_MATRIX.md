# D12d.3 故障与权限证据矩阵

更新：2026-10-26；**D12d.3 进行中，未通过整项门禁**。依据第 12 章 EVAL-01–24，关联 FR-001/003–015/020–029 与 NFR-001–005/007–009/012。该矩阵不改变需求通过标准，也不以已有测试数量代替系统验收。

层级：U = 纯逻辑/内存替身；I = 真实 PostgreSQL/文件/消息或 HTTP 集成，部分组件同进程；P = 独立服务进程；C = 实际 Compose 部署；F = 现场仪器。当前没有 F 证据。下表 `tests/` 路径相对项目根目录；函数名为可直接选择的 pytest 节点。已有 U/I/P 测试由统一门禁复验，C 证据独立保存。

## 逐项映射与缺口

| 案例 | 已有可追踪证据 | 当前层级与缺口 |
|---|---|---|
| EVAL-01 三设备顺序 | `apps/web/tests/deployment/agent.spec.ts`、`reports/d12d2-compose-evidence.json` | C：Agent 提案→人工批准→3 命令→HDF5；不证明真实模型规划质量或现场测量 |
| EVAL-02 越界电流 | `tests/test_plans.py::test_skill_parameters_are_validated`；`tests/integration/test_agents.py::test_plan_structure_scope_and_limits_fail_closed` | U/I 拒绝非法参数；尚缺实际部署越界请求/零命令证据，以及需求中的 POLICY_BLOCKED 告警语义核对，不将通用校验错误等同告警 |
| EVAL-03 文献注入 | `tests/integration/test_agents.py::test_prompt_injection_cannot_expand_tool_scope_and_key_is_redacted`；`test_injected_or_malformed_tool_request_is_blocked` | I/C：实际 HTTPS 返回 execute_device 越权工具时失败且零执行写入，见 `reports/d12d3-model-faults.json`；目标含绕过审批指令。P：独立 AgentWorker 真实检索注入文献，tool 消息保留不可信标识，脚本模型返回越权调用后 TOOL_FORBIDDEN；见 `tests/integration/test_knowledge_process_faults.py`。C：第十二批两供应商真实 HTTPS 检索结果包含注入文献，模型替身返回越权工具后 MODEL_FAILURE，零提案/执行，见 `reports/d12d3-knowledge-https-evidence.json`；未验真实模型抵抗质量 |
| EVAL-04 重复命令 | `tests/integration/test_execution.py::test_gateway_duplicate_id_must_match_bytes`；`tests/integration/test_wire_faults.py::test_actual_socket_cut_freezes_and_restart_never_replays[lost-response]` | I/P：相同 payload 重送返回持久结果、物理模拟动作一次；冲突 payload 的部署补证待完成 |
| EVAL-05 执行后响应丢失 | `tests/integration/test_wire_faults.py::test_actual_socket_cut_freezes_and_restart_never_replays` | P：真实 TCP 切断，分别在转发前/执行后；UNKNOWN 冻结、无重发；有持久结果则重启对账后 PAUSED，无结果保持 RECOVERING。循环 HTTP 未覆盖部署 mTLS 中断 |
| EVAL-06 两实验争资源 | `tests/integration/test_execution.py::test_cross_experiment_resource_race`；`tests/integration/test_engine_worker.py::test_competing_runs_wait_then_complete_without_overlapping_claims` | I：竞争/等待/无重叠；待常驻 Compose 两实验并发证据 |
| EVAL-07 浏览器断线 | `apps/web/tests/deployment/compose.spec.ts`；`reports/d12d2-compose-browser-regression.txt` | C：浏览器 SSE 中断禁写与重连；NATS 停服为独立补充案例，不能代替设备 ACK 或 SSE 故障 |
| EVAL-08 Agent 崩溃 | `tests/integration/test_background_workers.py::test_agent_process_recovers_inflight_and_stops`；`tests/integration/test_agents.py::test_pending_tools_survive_worker_restart` | P/I：持久 inflight 被标失败且不重复模型调用；已提交 tools 可恢复。第十八批 C 级证据：两供应商真实 HTTPS 首片后 SIGKILL，退出码 137/非 OOM；无取消时重启 FAILED/MODEL_INTERRUPTED，有取消意图时 CANCELLED，均只有一次 HTTPS 请求；再次重启状态/轨迹不变，见 `reports/d12d3-agent-crash-evidence.json`。第二十一批 C：两供应商分别在已提交 pending tools、已提交 read_snapshot 结果后 SIGKILL，重启继续且每项仅一次 read/一次未审批提案/两次 HTTPS，第二次重启无变化，见 `reports/d12d3-tool-recovery-evidence.json`。第二十八批 C：两供应商真实 MCP SUCCEEDED 缓存已落盘、Agent 提交被真实行锁阻塞后 SIGKILL，保留授权时缓存恢复不重复远端调用，撤权时拒绝使用缓存，见 `reports/d12d3-mcp-cache-evidence.json`。仅覆盖只读工具该边界；未知模型结果不能自动重放 |
| EVAL-09 源表输出中网关失联 | `tests/integration/test_control.py::test_lost_stop_ack_keeps_unknown_and_quarantine_until_replayed_confirmation` | I 仅验证中心停止请求不确定性的处理；**不等同边缘失联监护、输出策略、独立 interlock**。需模拟失联监护专门实现/验收及现场策略批准，当前缺口 |
| EVAL-10 上传中断/哈希错误 | `tests/integration/test_datasets.py::test_partial_upload_stays_staging`、`test_post_commit_corruption_revokes_reads_preserves_history`；`reports/d12c3-restore-evidence.json` | I/P：独立 Engine/Gateway 遇真实存储路径故障保持 STAGING/VERIFYING，恢复后提交且无重复采集，见 `tests/integration/test_data_process_faults.py` / `reports/d12d3-data-process.txt`；文件缺失/损坏读取拒绝仍由测试进程调用服务。C：新模拟采集的文件缺失/损坏时，清单/下载/曲线接口均返回 422 ARTIFACT_INVALID，恢复后内容一致，见 `reports/d12d3-data-api-evidence.json`；冷恢复缺失阻断已有证据。C 浏览器故障初次加载、下载禁用和文件恢复后原页重试已通过，见 `reports/d12d3-data-browser-evidence.json`；P：独立 Engine 在临时文件 fsync 前/最终文件链接后 SIGKILL，STAGING 不可读，重启提交同一 Dataset、动作各一次，见 `tests/integration/test_upload_process_faults.py`；Compose 活动上传、字节写入中途失败、已打开页面的缓存失效及自动损坏发现仍待补 |
| EVAL-11 稳定但读数过期 | `tests/test_stability.py::test_window_guards`；`tests/test_stability.py::test_wrong_observed_values_are_rejected` | U/P：独立 Engine/Gateway 经 HTTP 测试代理接收过期窗口，READBACK_STALE、后继零派发；恢复正常读回后三任务完成、动作各一次。见 `tests/integration/test_telemetry_process_faults.py` / `reports/d12d3-telemetry-process.txt`；Compose/真机证据未提供 |
| EVAL-12 批准后改计划 | `tests/integration/test_persistence.py::test_superseding_plan_invalidates_approval_and_freezes_run`；`test_policy_change_blocks_execution` | I/C：实际部署批准后将温度目标 295→296 K、计划 hash 改变，旧审批 SUPERSEDED；旧快照 STATE_CONFLICT，最新快照复用旧审批 PLAN_STALE，执行写入 0。见 `reports/d12d3-plan-evidence.json`。已有 Run 冻结及策略变化仍为 I 级证据 |
| EVAL-13 重复建议循环 | `tests/integration/test_resources.py::test_equivalent_proposal_from_independent_runs_is_deduplicated`；`test_collaboration_count_and_cooldown_are_durable` | I：内容去重/冷却/预算；待常驻 Agent 重复响应不产生自激 Run 的部署证据 |
| EVAL-14 网关冒充设备 | `tests/test_gateway_transport.py::test_mutual_tls_requires_client_certificate`；`tests/integration/test_execution.py::test_gateway_authorization_gates` | I：证书缺失及签名/资源约束；C mTLS 基础已有。P：第 30 批迁入同 CA/同主机名错误服务端、错误客户端与未登记资源拒写验证；静态绑定实现见 ADR-054，C 升级/轮换和现场证据仍待补 |
| EVAL-15 零目标/不稳回读 | `tests/test_stability.py::test_wrong_observed_values_are_rejected`；`tests/test_plans.py::test_readback_must_match_setpoint` | U/P：经 HTTP 接收斜率超限窗口返回 READBACK_UNSTABLE；零磁场目标下超容差读回返回 READBACK_INVALID，采集未派发。恢复后动作各一次，见 `reports/d12d3-telemetry-process.txt`；非现场磁通/真实仪器证据 |
| EVAL-16 两供应商格式 | `tests/test_models.py::test_same_planner_input_unified_tool_proposal`；`reports/d12d2-compose-evidence.json` | U/C：OpenAI/DeepSeek 本地 TLS 格式与实际模型标识；未调用官方在线 API |
| EVAL-17 流式异常/用量 | `tests/test_models.py`（分片、截断、限流、超时、取消、invalid usage）；`tests/test_offline_provider.py` | U/C：真实 HTTPS 截断 SSE、429、缺失 usage 已验，两供应商各一轮；见 `reports/d12d3-model-faults.json`。第十三批再补两供应商负数/布尔/不一致 usage 与部分 SSE 后实际读超时共八项，见 `reports/d12d3-streaming-https-evidence.json`；第十三批 2s/max_attempts=1；第十四批 max_attempts=3 时连续 429 各三次请求、部分 SSE 后超时各一次，共四项通过，见 `reports/d12d3-retry-https-evidence.json`。第十五批两供应商调用前取消/调用中 RUN_BUSY 共四项 C 级边界通过，见 `reports/d12d3-cancellation-api-evidence.json`；第十六批已编码持久化意图与安全边界确认，12 项 I 级专项、615 项完整后端及 Web 10 单元/20 fixture 浏览器通过，第十七批新镜像及 d12_002 已部署，两供应商六项 API/浏览器取消通过，见 `reports/d12d3-cancel-deploy-evidence.json`，不能标记完整取消验收。第十九批两供应商首次 429 后成功、累计预留不足阻止重试、调用前预算不足共六项 C 级通过，见 `reports/d12d3-retry-budget-evidence.json`；其他期限/上下文/并发预算组合仍待补 |
| EVAL-18 凭据/能力不可用 | `tests/test_models.py::test_missing_key_and_version_mismatch`；`tests/integration/test_api.py::test_credentials_encrypted_never_returned_and_cas` | U/I/C：禁用测试凭据后 Agent 失败、HTTPS 请求为 0，见 `reports/d12d3-model-faults.json`；第二十批 C：同版能力覆盖 VERSION_CONFLICT；新模型 v2 tools=unsupported 导致新 Agent 发布 MODEL_UNAVAILABLE，旧运行仍使用 v1；禁用 v1 后即使 v2 可用也 CONFIG_DISABLED/请求 0，不自动切换。见 `reports/d12d3-version-binding-evidence.json`；供应商在线能力变化与调用中禁用仍待单独验 |
| EVAL-19 Skill 边界 | `tests/integration/test_agents.py::test_skill_import_does_not_run_or_grant_permissions`、`test_disabled_skill_blocks_new_binding_and_existing_invocation`、`test_new_skill_version_does_not_change_existing_run` | I/C：第二次 HTTPS 响应返回前，经真实 API 禁用已绑定 Skill；轨迹 SKILL_DISABLED、提案提交被阻断，见 `reports/d12d3-model-faults.json`。第二十批 C：同版 Skill 内容覆盖 VERSION_CONFLICT，新版 v2 发布后旧运行 bundle/hash 不变，实际 HTTPS 请求仍含旧 instruction 标记、无新标记；见 `reports/d12d3-version-binding-evidence.json`。依赖升级组合仍待补 |
| EVAL-20 MCP 默认拒绝 | `tests/integration/test_resources.py::test_discovery_and_remote_annotations_do_not_grant_access`、`test_schema_change_requires_new_review_and_stops_old_run`、`test_remote_scope_fields_cannot_be_forged_by_model` | I/实际本地 HTTP，Web fixture 验过独立授权；第二十六批 C：两供应商正常只读与模型 HTTPS 响应期间撤权四项常驻部署通过。维护发现无自动 grant，经 HTTP API 审批/撤销；正常 MCP 1 次、撤权 MCP 0 次且 FAILED/MCP_REVOKED，终态重启不重放。见 `reports/d12d3-mcp-grant-evidence.json`。第二十七批 C：两供应商 Schema 漂移/请求在途撤权四项通过；漂移撤销旧审批且新版不自动授权、零 tools/call；在途返回被拒绝，mcp_calls=UNKNOWN/null、零 Agent 历史/ledger/提案，重授权后终态重启不重放，见 `reports/d12d3-mcp-runtime-evidence.json`。第二十八批 C：两供应商 SUCCEEDED 缓存落盘/Agent checkpoint 未提交时中断恢复与恢复前撤权四项通过，远端仅调用一次、撤权缓存不发布，见 `reports/d12d3-mcp-cache-evidence.json`；非物理写/MCP 全故障空间验收 |
| EVAL-21 用量去重/未知 | `tests/integration/test_api.py::test_dashboard_and_usage_grouping_preserve_unknown`；`tests/test_models.py::test_invalid_usage_is_not_published` | I/U/C：两轮无 usage 的响应保留 usage=null，API unknown_usage_completions=2，见 `reports/d12d3-model-faults.json`；第十九批 C：首次 429 后成功仅一个完成、两个唯一尝试 ID、末次 usage=150；重复 GET 与 worker 重启后用量/轨迹不变。失败调用的实际尝试仍不等于 API recorded_attempts；多完成/跨实验聚合保留原 I 级范围，估算费用不得冒充实际账单 |
| EVAL-22 轨迹/权限 | `tests/integration/test_api.py::test_agent_proposal_read_model_requires_run_owner`、`test_dashboard_and_usage_grouping_preserve_unknown`；`apps/web/tests/e2e/console.spec.ts` | I/fixture 浏览器；C 正常轨迹及 Agent 跨实验 403 已验；第二十二批两供应商 98 项实际 HTTP 权限断言通过：同实验 observer/operator/approver 非提交人的详情/轨迹/提案与控制拒绝、自身列表/用量隔离；实验外/匿名拒绝；API 撤权后列表/用量/仪表板立即拒绝。见 `reports/d12d3-permissions-evidence.json`。第二十三批已编码提交人主体禁用/成员撤权/范围缩减的受限终态收尾，新增 19 项数据库测试及完整 638 项后端门禁通过，该批尚未更新部署镜像，见 `reports/d12d3-access-revocation-acceptance.md`；第二十四批新镜像两供应商非管理员 operator 调用前/真实 HTTPS 响应期间成员撤权与范围缩减共六项 C 级案例通过，FAILED/ACCESS_REVOKED、重授权/重启不重放，见 `reports/d12d3-access-deploy-evidence.json`。第二十五批两供应商调用前/实际 HTTPS 响应期间主体禁用四项 C 级案例通过：管理 API 禁用后令牌 401，原成员/设备范围保持，运行 FAILED/ACCESS_REVOKED、重启不重放，见 `reports/d12d3-principal-disable-evidence.json`。第二十九批 C：独立 observer 设备范围缩减后，数据清单/曲线/下载与设备详情拒绝，列表过滤，14 项 HTTP 断言与已加载页面权限恢复案例通过，见 `reports/d12d3-data-access-acceptance.md`；完整角色/字段及页面矩阵仍待补 |
| EVAL-23 知识撤权/来源 | `tests/integration/test_resources.py::test_knowledge_tool_context_is_rechecked_after_revoke`、`test_source_resource_and_experiment_isolation`、`test_data_corruption_detected_by_actual_checksum_before_analysis` | I/P：独立 AgentWorker 检索后、模型响应期间撤权均 SOURCE_REVOKED，后续不重放模型/不提交结果，见 `reports/d12d3-knowledge-process.txt`；第十批受限 FAILED 收尾已通过独立进程/真实数据库验证，保留来源拒绝与禁止重放，全后端 593 项通过；第十一批受限 API/页面及预置上下文的部署 READY→FAILED 路径通过，见 `reports/d12d3-revocation-view-evidence.json`。Web fixture 撤权已验，C：第十二批常驻 Agent 实际检索后的第二轮 HTTPS 响应期间撤权已通过（两供应商、本地替身），状态正确收尾、历史接口拒绝且不重放；不代表所有权限组合已覆盖 |
| EVAL-24 页面异常状态 | `apps/web/tests/e2e/workspace.spec.ts`、`apps/web/tests/e2e/console.spec.ts`；`apps/web/tests/deployment/compose.spec.ts` | fixture 18 项与 C 观察者/SSE/令牌刷新已验；不能宣称“每页全部状态”覆盖，数据页故障初次加载/下载禁用/重试恢复已有 C 证据；第十七批实际部署取消页面两供应商等待/确认状态通过；第二十九批新 Web 已修复数据页下载/曲线权限错误后的旧内容显示，22 项 fixture 浏览器与 1 项实际部署范围缩减/恢复案例通过，见 `reports/d12d3-data-access-acceptance.md`；其余页面仍需逐页盘点补证 |

## 本轮新增故障的注入与恢复契约

### WIRE-01：转发前断开 TCP

只在隔离测试库和 loopback HTTP proxy 注入。Engine 已尝试提交，代理在将第一个 accept 转发至独立 Gateway 前关闭 socket。预期中心 UNKNOWN、一个 Command、模拟动作 0、无 Dataset、至少两轮调度不再 accept。重启独立 Engine 后，无 Gateway 持久结果可证明该命令安全结束，保持 RECOVERING/UNKNOWN，不凭测试代理知道“未转发”就篡改业务判断。测试结束终止进程并删除临时测试库；不是现场自动恢复方案。

### WIRE-02：执行完成后丢弃响应

代理先读完 Gateway 的真实 accept 响应，然后关闭给 Engine 的 socket。预期 UNKNOWN、后继冻结、模拟动作 1、不自动重发。显式同命令同 payload 经 Gateway RPC 重送仍只有一次模拟动作。kill/restart Engine 后根据持久结果对账，Run 为 PAUSED、控制模式 ACTIVE，无自动 resume，后继命令仍未生成。该测试使用独立 Engine 与 Gateway 进程，代理在测试进程监听；不是 Compose mTLS 或真实仪器 ACK 故障。

### BUS-01：真实 NATS 停服与恢复

入口 `.venv/bin/python deploy/simulation/check_messaging_fault.py`，维护锁、八服务运行、无活动 Run/outbox 积压为前置条件。实际停止 NATS，然后创建唯一未审批模拟计划。PostgreSQL 保留两条待发布事件，API 快照 event_cursor=2、无审批/Run，设备命令数不变。恢复 NATS 后常驻 outbox 发布完毕，JetStream 消息数恰好增加 2，再重启 outbox 后消息数不增加，快照游标不回退。finally 恢复 NATS/outbox 并撤销短期令牌；不删除业务审计。证据 `reports/d12d3-messaging-evidence.json`。

这验证消息中断不丢失权威业务状态，**不证明物理设备安全停止或长时间负载能力**。本轮不改时钟或租约过期时间；五秒观测仅用于多次轮询，不能计作 D12d.4。

### MODEL-01–06：实际 HTTPS 模型故障与运行期撤权

入口 `.venv/bin/python deploy/simulation/check_model_faults.py`，复用隔离 TLS/SSE 供应商与常驻 worker。OpenAI/DeepSeek 各运行越权工具、SSE 截断、HTTP 429、缺失 usage、禁用凭据、运行中禁用 Skill 六种场景，共 12 项。前两轮真实模型调用之间设置文件屏障，在第二个响应发出前用 API 撤销绑定 Skill；不通过直接改 checkpoint 制造结果。

除缺失 usage 外均 FAILED；缺失 usage 保留未知统计，只产生未审批提案。禁用凭据为零 HTTPS 请求，截断/429/越权各一次请求，缺失 usage/撤销 Skill 各两次；fixture max_attempts=1，不据此宣称所有重试配置都已验收。所有场景的计划、审批、执行 Run、Task、Command、Dataset 写入均为 0。正常浏览器回归另验人工审批后的三任务执行，见 `reports/d12d3-model-normal-evidence.json`。

finally 停止隔离服务，通过应用用例取消未终结的本次 AgentRun，禁用测试配置/凭据/Agent/专属 Skill 并撤销令牌，保留审计。目标中的恶意指令和模型越权工具响应不是检索文献注入；不使用在线供应商或真实设备。验收与遗留见 `reports/d12d3-model-acceptance.md`。

### PLAN-01：批准后修改参数与拒绝旧授权

入口 `.venv/bin/python deploy/simulation/check_plan_fault.py`。要求八服务运行、无活动执行 Run/outbox 积压，持有维护锁。通过受限应用用例创建唯一未审批计划；随后全部审批、计划变更和启动请求经过部署 HTTP API。批准后把温度设定及相关读回条件从 295 K 改为 296 K，保存新版本，确认 hash 改变且旧审批 SUPERSEDED。

分别用旧快照和最新快照携带旧 approval_id 启动，期望 409 STATE_CONFLICT 与 409 PLAN_STALE。拒绝请求不推进实验 revision；随后 event_cursor 保持稳定，观察常驻 Engine 多轮轮询后，Run/Task/Command/Dataset 仍为 0，全局设备命令不增加。finally 撤销两个测试令牌，保留审批失效和计划版本审计。不停止 Engine、不手工推进、不制造执行 Run；不能据此声称已部署验证运行中改计划的停止/冻结路径。

### DATA-01/02：独立进程存储失败与已提交文件异常

`tests/integration/test_data_process_faults.py::test_storage_failure_recovers_without_reacquisition[missing/corrupt]` 使用随机隔离 PostgreSQL 库、独立 Engine 与 HTTP Gateway 进程、临时 HDF5/SQLite。Engine 启动后把测试存储目录暂时替换成普通文件，触发真实文件系统错误；不 monkeypatch 存储函数。日志 STORAGE_UNAVAILABLE，Dataset STAGING、manifest=null，采集 Command VERIFYING，无 provenance；多个轮询中不重复采集。

恢复目录后常驻进程重试数据提交，形成一份 COMMITTED HDF5、一条来源边和一条 committed outbox 事件，Run 成功且释放资源。随后停稳 Engine，仅对本次临时文件分别删除/损坏，读取拒绝 ARTIFACT_INVALID，不重建文件或改 manifest；finally 恢复精确原始字节，再启动 Engine、多轮观察，每条模拟命令动作次数仍为 1。

这是 P 级执行/存储故障证据；读取校验由测试进程中的真实 DatasetService 调用，属于 I 级，不是浏览器或部署 HTTP 的 Analysis 禁用证据。没有验证磁盘写到一半、满盘、永久介质损坏或生产备份恢复；字节还原仅是测试清理，不是 CORRUPT 状态恢复协议。专项报告 `reports/d12d3-data-process.txt`。

### DATA-API-01/02：部署清单、下载与曲线拒绝损坏文件

入口 `.venv/bin/python deploy/simulation/check_data_fault.py`。维护锁、八服务运行且无活动执行 Run 为前置条件。真实 API 批准唯一模拟计划、启动三任务采集；仅操作这次新生成的 COMMITTED 文件，核对实验归属、存储 key 和原始 SHA-256 后将其移到同卷备份。分别保持原路径缺失或写入损坏字节，清单/下载/曲线三个真实 HTTP 接口均应返回 422 ARTIFACT_INVALID，数据库清单与命令投影不变化。

每种故障 finally 恢复备份，校验下载 SHA-256、清单和曲线与正常结果完全一致；外层 finally 再保障恢复并撤销短期令牌。常驻 Engine 保持运行，全局命令仅增加正常采集的 3 条，故障增量 0。不修改 dataset 状态、原始 manifest 或旧实验文件。硬杀宿主进程不能保证 finally；遇中断须先检查本次对象的 `.fault-backup` 并校验恢复，不自动重复采集。报告 `reports/d12d3-data-api-evidence.json`。

该 C 级证据验证请求时的拒绝，不验证后台自动扫描、CORRUPT 状态转换、浏览器旧缓存/按钮状态或运行中上传失败；这些仍是后续门禁。这里只为测试恢复新文件的精确字节，不是生产数据修复协议。

### DATA-WEB-01/02：浏览器数据错误与重试恢复

入口 `.venv/bin/python deploy/simulation/check_data_browser.py`，复用新实验采集和文件故障入口，不覆盖上批 API 报告。两个场景分别在文件缺失/损坏时打开 `/data/{id}`，登录后验证明确的完整性错误提示、下载禁用、无曲线；浏览器发出私有文件屏障信号，控制端校验并恢复原始对象，浏览器在同一页面点击“重新获取状态”，验证错误消失、曲线恢复、下载 SHA-256 一致。不使用路由 mock 或伪造成功响应。

修正 ARTIFACT_INVALID 提示，避免将数据文件异常引导为修改计划/输入。私有状态文件、屏障和日志保存在临时目录，finally 清理并撤销令牌、恢复文件；不保存截图、视频或 trace。两项报告为 `reports/d12d3-data-browser-missing.txt` / `d12d3-data-browser-corrupt.txt`，数据库/API 对账为 `reports/d12d3-data-browser-evidence.json`。

该测试覆盖故障发生后的初次页面加载和显式重试；没有验证已打开页面在后台文件变更后的即时缓存失效、下载中途损坏或自动完整性扫描。其余 EVAL-24 页面状态仍待验证。

### READBACK-01–03：过期、不稳定与零目标错误读回

`tests/integration/test_telemetry_process_faults.py` 使用随机数据库、独立 Engine/Gateway 与 loopback HTTP 代理。代理转发真实请求，仅在 telemetry 响应中替换采样数据：所有时间戳减 60 秒；一个采样值在容差内变化但斜率超限；零磁场目标下把读数设置到容差之外。保留条件、来源和 RPC 绑定，用隔离测试密钥重新签名。这模拟来源合法的错误读回，不是攻破签名/mTLS；不更改系统时钟、产品逻辑或设备执行回执。

分别观察 READBACK_STALE、READBACK_UNSTABLE、READBACK_INVALID，至少三次故障响应期间无后继派发。前两项只有温度命令（动作一次），磁场/采集待执行；零场错误读回已有温度/磁场两命令，采集待执行。均无 Dataset。解除代理注入后常驻 Engine 自动重读并继续正常前置条件评估，最终三条命令、动作各一次、一份 COMMITTED Dataset、资源释放。没有 UNKNOWN 或审批变更，不把正常重读称为未知命令重试，也不冒充需要人工 resume 的冻结恢复。

专项 **3 项通过**，报告 `reports/d12d3-telemetry-process.txt`；P 级证据，非 Compose mTLS/现场设备。代理在测试进程内，Engine/Gateway 独立运行。测试只用临时数据库/文件，正常部署业务不受注入影响。

### UPLOAD-01–02：写入发布边界的进程中断

新增 `tests/integration/test_upload_process_faults.py`，真实 PostgreSQL、独立 Engine/Gateway 与 HDF5 文件，两个边界专项初验 **2 项通过（24.67 秒）**。测试专用子进程启动器仅在目标 fsync 前等待，由父进程实际 SIGKILL；HDF5 写入、硬链接、数据库提交及恢复仍使用产品实现。两个位置分别为临时文件写完、同步前，以及最终硬链接创建后、目录同步前。

中断时 Dataset 为 STAGING、manifest 为空，采集命令 VERIFYING；来源边和 committed 事件均为零，即使已有最终文件仍拒绝读取。正常启动器重启后依据持久回执完成同一 Dataset，唯一来源/提交事件，三条命令动作各一次、资源释放；已存在的最终对象 inode 保持不变。没有重发采集、手工提交或自动恢复设备动作。见 `reports/d12d3-upload-process.txt` 与本批完整后端报告。

该证据为 P 级进程崩溃恢复，故障定位使用测试钩子；不是 Compose 故障、磁盘满、HDF5 字节写到一半、操作系统断电或 fsync 耐久性验证。SIGKILL 绕过 finally 会保留 `.upload-*` 孤儿文件；它没有 manifest 引用、不能公开读取，但自动回收尚未实现，不把临时目录的 fixture 清理称为生产回收。

### KNOWLEDGE-01–04：检索注入与运行期来源撤权

`tests/integration/test_knowledge_process_faults.py` 的四项专项 **4 项通过（9.53 秒）**。真实 PostgreSQL、独立 fork AgentWorker；父进程受控 tick，子进程内离线 ScriptedModel，不是 HTTPS/Compose 常驻循环。正常对照与恶意工具响应均使用实际检索的同一注入文献，验证 tool 内容与不可信标签、system 未被替换、越权工具被拒。两种撤权分别发生在检索后调用前、第二次模型响应期间，均拒绝后续访问/提交且无模型重放。四项均零提案/审批/设备执行写入。

撤权后 checkpoint 仍 RUNNING（model/inflight）、result=null，不能把拒绝访问称为终态收尾。完整边界及后续修复约束见 `reports/d12d3-knowledge-acceptance.md`；不证明模型本身抗注入能力，已交给模型的内容也无法事后撤回。

### KNOWLEDGE-CLOSE：知识撤权的受限终态收尾

`AgentRuntime.step` 在原独占锁内捕获 SOURCE_REVOKED，调用 `AgentStore.fail_revoked_source`；适配器在原会话事务重检权限与实际撤权，才从 READY/RUNNING 改为 FAILED/done 并追加审计，随后原读取错误仍返回调用者。历史/来源引用/预留不删除，inflight 的未知模型结果以审计字段保留。无锁、身份不符、提交人无权限、有效/恢复授权及已有终态不允许被此路径改写；原所有权连接死亡不得重连。

首轮专项及资源回归 41 项通过（79.59 秒），追加断言后完整后端 593 项通过（560.30 秒）。独立 worker 不再选取已收尾运行，调用前/响应中撤权不重放模型；真正 PostgreSQL 审计 INSERT 故障验证状态与审计一起回滚。完整结果、范围及部署限制见 `reports/d12d3-revocation-closure-acceptance.md`。

### KNOWLEDGE-VIEW：撤权后的最小状态与页面呈现

第十一批新增 owner-only 状态投影，RUNNING/READY 不伪装为 FAILED；只有实际 worker 收尾后才显示终止。来源撤权时目标置固定提示、结果为 null、access_error=SOURCE_REVOKED；轨迹/提案仍拒绝，其他用户和失去实验权限的提交人不能读取投影。HTTP 专项 2 项通过（6.11 秒）。Web 收到受限状态后隐藏缓存目标/提案/轨迹并禁用动作，部署验证使用 fixture 预置来源，不冒充真实模型检索。完整验证与范围见 `reports/d12d3-revocation-view-acceptance.md`，完整后端 595 项、Web 10 单元/19 浏览器及部署 Chromium 1 项通过。

### KNOWLEDGE-HTTPS：实际检索与模型响应期间撤权

第十二批六项部署案例通过，两供应商各正常对照/文献注入/响应期间撤权。常驻 Agent 经真实 API 发起，第一轮 search_knowledge 获取版本化来源，第二轮 HTTPS 由替身校验实际文献、来源引用和不可信标签。攻击内容没有放在目标指令或 system；越权响应由真实模型适配器拒绝，Agent MODEL_FAILURE。撤权通过 API 在第二轮响应屏障期间完成，随后提交被拒并收尾 FAILED，inflight/模型结果未提交事实保留；每项最终请求数仍为 2，零提案/执行写入。详见 `reports/d12d3-knowledge-https-acceptance.md`，完整后端门禁 601 项通过（556.80 秒）。

该证据补齐了第十一批预置上下文与第九批进程内模型的范围缺口，但线上模型抗注入质量仍未验证。本批未改产品代码或 Web，不重复上一批浏览器门禁。

## 实现审查发现

- 第十四批核对取消路径：AgentRuntime.cancel/step 共用运行独占锁，当时的 `tests/integration/test_background_workers.py` 明确运行中取消返回 RUN_BUSY。模型客户端 Event 取消是另一条路径；第十五批部署 API 已复现该拒绝（409），保持 RUNNING 后超时 FAILED，没有伪装 CANCELLED；调用前取消/终态幂等也已验证。第十六批已新增持久化请求及安全边界确认，I 级专项、完整后端及 Web fixture 门禁通过；第十七批已完成新镜像/迁移及实际 HTTPS 取消部署与 Chromium 验证；旧 RUN_BUSY 报告作为历史证据保留，安全边界确认不等于即时断开远端调用。

- 第九批发现的知识来源撤权后 RUNNING 滞留，第十批已通过新增受限终态收尾路径修复源码；原 load/commit 的来源拒绝保持，历史/引用保留且不重放模型。独立进程与事务负路径验收见 `reports/d12d3-revocation-closure-acceptance.md`；全量门禁 593 项通过，第十一批已补受限 API/页面与新镜像预置上下文部署验证；第十二批常驻 Agent 实际检索后 HTTPS 响应期间撤权也已通过（本地替身），其它权限组合仍需补齐。其它资源类型及提交人自身撤权不在本批自动收尾范围。

- 当前 `src/alap/adapters/gateway/server.py` 装配的是模拟器、签名 RPC 和 mTLS listener；没有独立的设备失联策略监护循环。`ControlService` 的中心取消/UNKNOWN 处理不能替代 EVAL-09 的近端设备策略。后续先在模拟器明确设备分类、策略版本、失联证据和受控恢复，现场阈值/停机方法仍须 G1/G2 批准，不能默认所有设备统一关输出。
- `src/alap/adapters/gateway/transport.py` 校验签名 RPC 的 `gateway_id` 与本地身份；listener 校验客户端证书链。当前没有将客户端证书主体与资源登记进行显式映射的应用层证据。后续需用“同 CA 签发但身份错误”的证书验证，而非仅测缺证书/不可信 CA；签名约束仍保留，不能为了测试放宽现有认证。

## 后续门禁

1. 继续 D12d.3：优先补 EVAL-02/03/08/10/11/12/15/17–19 的运行期负路径和跨进程组合证据；按上述缺口逐项缩小范围，不直接标记通过。
2. 对 EVAL-09 边缘失联策略和 EVAL-14 证书身份映射进行实现审查，明确模拟可验部分与现场必须签署部分；缺少实现不能仅写作“已有测试”。
3. 完成逐页 EVAL-24 状态盘点及剩余权限组合后，才评审 D12d.3 是否可交接到长测；本轮不启动 D12d.4，更不进入 D13。

## 第二十九批：已加载数据页的权限收缩

关联 FR-001/010/011/029、NFR-008/012 与 EVAL-22/24。使用既有 COMMITTED 模拟数据，独立 observer 仅通过真实成员 API 获得三设备范围，再移除一个设备。部署 HTTP 已确认清单、曲线和下载均 403，设备列表只含剩余授权设备，被移除设备详情 403；完整授权下载校验和正确，清单不暴露 storage_key。测试身份、短期令牌和成员授权在 finally 清理，不生成新设备命令或数据。

旧 Web 镜像的 Chromium 已复现下载 403 后按钮仍启用，见 `reports/d12d3-data-access-browser-before.txt`。源码修复统一处理清单/曲线/下载的 401/403：隐藏曲线与来源记录、禁用下载；显式重试重新挂载资源读取，避免直接恢复旧缓存。新增两个 fixture 浏览器案例覆盖下载拒绝、曲线拒绝、重复拒绝及重新授权读取；Web 10 单元/22 浏览器门禁通过。部署复验及本批完整收尾结果见 `reports/d12d3-data-access-acceptance.md`。

该修复在请求收到权限错误后生效；尚无后台权限推送来主动抹除已加载数据，不能撤回用户此前已下载的文件。不代表所有角色/页面/字段组合已经通过；其余矩阵缺口和 D12d.4 门禁保持。


## 第三十批：证书绑定与独立监护基础（2026-10-26）

在 1a3d456 基线迁入旧 stash 的独立证书绑定和上传测试可移植修正；未恢复旧业务实现或整份历史文档。HTTPS endpoint 绑定服务端指纹，发送 RPC 前校验；Gateway 从 TLS socket 取得调用方指纹，按连接隔离，转发头不能伪造。真实 PostgreSQL + 独立 mTLS Gateway 验证三类拒写与正常命令，负路径 journal/模拟动作零，中心 UNKNOWN 不自动重派。配置生成与升级约束见 deploy/simulation/README.md。旧 EVAL-14 “仅证书链”缺口已补 P 级静态登记，不宣称已部署或现场通过。

EVAL-09 新增独立进程监护基础与专用输出模型：源表归零、磁体/温控保持，持久锁存、旧心跳拒绝、显式确认后仍需新心跳和输出命令。SIGSTOP/SIGKILL 故障验证的是该独立模型，**未接入 Gateway/Engine 链，不等于源表执行中断网的完整验收**。实现、限制与下一批接线要求见 D12D_EDGE_SUPERVISION.md；原执行链监护缺口仍保留。

### 第 31 批：EVAL-09 可选模拟执行链增量

第 30 批隔离输出模型已接入显式配置的 Gateway/Engine 路径（ADR-056）。新增三进程正常采集、Engine SIGKILL/数据库所有权失效、错误心跳密钥和 Gateway 同时死亡后的显式恢复；失败时源表归零、无部分 Dataset、命令确认失败/任务失败/Run 暂停，锁存禁止新 epoch，动作不重放。详见 `tests/integration/test_edge_execution.py`、`reports/d12d3-edge-execution-focused.txt`。

这是 P/I 本地模拟证据；上文默认部署没有监护服务的描述仍适用于默认 Compose。真正网络分区、维护授权/恢复、执行中监护/存储异常组合和 C 级部署尚待补齐，EVAL-09 不标为整项通过，不进入长测或现场。

### 第 32 批：维护授权与锁存解除门禁

EVAL-09 增加人类 admin 维护 API、独立 API→Gateway 凭据、事故/世代/epoch/策略/读回精确绑定、双侧命令收敛检查、monitor 鲜度/源表为零和事务审计。确认仅 WAITING；Engine 后续握手不恢复旧 Run 或重试失败命令。拒绝非人类/非管理员、旧审查、过期授权、监护停止推进、非零源表、未对账 journal；丢失确认回复保持待核对，不自动重发。证据见 `reports/d12d3-edge-maintenance-focused.txt` 和 `tests/integration/test_edge_maintenance.py`。

当前仅 P/I 本地 HTTP/数据库/模拟进程门禁；C 级证书与部署组合、真实网络分区和现场仍未完成，EVAL-09 继续保留未整项通过。
