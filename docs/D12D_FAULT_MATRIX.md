# D12d.3 故障与权限证据矩阵

更新：2026-10-21；**D12d.3 进行中，未通过整项门禁**。依据第 12 章 EVAL-01–24，关联 FR-001/003–015/020–029 与 NFR-001–005/007–009/012。该矩阵不改变需求通过标准，也不以已有测试数量代替系统验收。

层级：U = 纯逻辑/内存替身；I = 真实 PostgreSQL/文件/消息或 HTTP 集成，部分组件同进程；P = 独立服务进程；C = 实际 Compose 部署；F = 现场仪器。当前没有 F 证据。下表 `tests/` 路径相对项目根目录；函数名为可直接选择的 pytest 节点。已有 U/I/P 测试由统一门禁复验，C 证据独立保存。

## 逐项映射与缺口

| 案例 | 已有可追踪证据 | 当前层级与缺口 |
|---|---|---|
| EVAL-01 三设备顺序 | `apps/web/tests/deployment/agent.spec.ts`、`reports/d12d2-compose-evidence.json` | C：Agent 提案→人工批准→3 命令→HDF5；不证明真实模型规划质量或现场测量 |
| EVAL-02 越界电流 | `tests/test_plans.py::test_skill_parameters_are_validated`；`tests/integration/test_agents.py::test_plan_structure_scope_and_limits_fail_closed` | U/I 拒绝非法参数；尚缺实际部署越界请求/零命令证据，以及需求中的 POLICY_BLOCKED 告警语义核对，不将通用校验错误等同告警 |
| EVAL-03 文献注入 | `tests/integration/test_agents.py::test_prompt_injection_cannot_expand_tool_scope_and_key_is_redacted`；`test_injected_or_malformed_tool_request_is_blocked` | I/C：实际 HTTPS 返回 execute_device 越权工具时失败且零执行写入，见 `reports/d12d3-model-faults.json`；目标含绕过审批指令。尚未注入检索文献，不宣称完整文献注入验收 |
| EVAL-04 重复命令 | `tests/integration/test_execution.py::test_gateway_duplicate_id_must_match_bytes`；`tests/integration/test_wire_faults.py::test_actual_socket_cut_freezes_and_restart_never_replays[lost-response]` | I/P：相同 payload 重送返回持久结果、物理模拟动作一次；冲突 payload 的部署补证待完成 |
| EVAL-05 执行后响应丢失 | `tests/integration/test_wire_faults.py::test_actual_socket_cut_freezes_and_restart_never_replays` | P：真实 TCP 切断，分别在转发前/执行后；UNKNOWN 冻结、无重发；有持久结果则重启对账后 PAUSED，无结果保持 RECOVERING。循环 HTTP 未覆盖部署 mTLS 中断 |
| EVAL-06 两实验争资源 | `tests/integration/test_execution.py::test_cross_experiment_resource_race`；`tests/integration/test_engine_worker.py::test_competing_runs_wait_then_complete_without_overlapping_claims` | I：竞争/等待/无重叠；待常驻 Compose 两实验并发证据 |
| EVAL-07 浏览器断线 | `apps/web/tests/deployment/compose.spec.ts`；`reports/d12d2-compose-browser-regression.txt` | C：浏览器 SSE 中断禁写与重连；NATS 停服为独立补充案例，不能代替设备 ACK 或 SSE 故障 |
| EVAL-08 Agent 崩溃 | `tests/integration/test_background_workers.py::test_agent_process_recovers_inflight_and_stops`；`tests/integration/test_agents.py::test_pending_tools_survive_worker_restart` | P/I：持久 inflight 被标失败且不重复模型调用；已提交 tools 可恢复。待真实 HTTP 模型调用中 kill 的部署证据；未知模型结果不能自动重放 |
| EVAL-09 源表输出中网关失联 | `tests/integration/test_control.py::test_lost_stop_ack_keeps_unknown_and_quarantine_until_replayed_confirmation` | I 仅验证中心停止请求不确定性的处理；**不等同边缘失联监护、输出策略、独立 interlock**。需模拟失联监护专门实现/验收及现场策略批准，当前缺口 |
| EVAL-10 上传中断/哈希错误 | `tests/integration/test_datasets.py::test_partial_upload_stays_staging`、`test_post_commit_corruption_revokes_reads_preserves_history`；`reports/d12c3-restore-evidence.json` | I/P：独立 Engine/Gateway 遇真实存储路径故障保持 STAGING/VERIFYING，恢复后提交且无重复采集，见 `tests/integration/test_data_process_faults.py` / `reports/d12d3-data-process.txt`；文件缺失/损坏读取拒绝仍由测试进程调用服务。C：新模拟采集的文件缺失/损坏时，清单/下载/曲线接口均返回 422 ARTIFACT_INVALID，恢复后内容一致，见 `reports/d12d3-data-api-evidence.json`；冷恢复缺失阻断已有证据。C 浏览器故障初次加载、下载禁用和文件恢复后原页重试已通过，见 `reports/d12d3-data-browser-evidence.json`；活动上传失败、已打开页面的缓存失效及自动损坏发现仍待补 |
| EVAL-11 稳定但读数过期 | `tests/test_stability.py::test_window_guards`；`tests/test_stability.py::test_wrong_observed_values_are_rejected` | U：鲜度/完整窗口规则；待实际远程 telemetry 过期注入和后继零派发证据 |
| EVAL-12 批准后改计划 | `tests/integration/test_persistence.py::test_superseding_plan_invalidates_approval_and_freezes_run`；`test_policy_change_blocks_execution` | I/C：实际部署批准后将温度目标 295→296 K、计划 hash 改变，旧审批 SUPERSEDED；旧快照 STATE_CONFLICT，最新快照复用旧审批 PLAN_STALE，执行写入 0。见 `reports/d12d3-plan-evidence.json`。已有 Run 冻结及策略变化仍为 I 级证据 |
| EVAL-13 重复建议循环 | `tests/integration/test_resources.py::test_equivalent_proposal_from_independent_runs_is_deduplicated`；`test_collaboration_count_and_cooldown_are_durable` | I：内容去重/冷却/预算；待常驻 Agent 重复响应不产生自激 Run 的部署证据 |
| EVAL-14 网关冒充设备 | `tests/test_gateway_transport.py::test_mutual_tls_requires_client_certificate`；`tests/integration/test_execution.py::test_gateway_authorization_gates` | I：证书缺失及签名/资源约束；C mTLS 基础已有。**合法但身份错误的证书与设备映射**需专项核对，不能用“无证书失败”替代身份映射验收 |
| EVAL-15 零目标/不稳回读 | `tests/test_stability.py::test_wrong_observed_values_are_rejected`；`tests/test_plans.py::test_readback_must_match_setpoint` | U：区分目标与稳定判据；待 Gateway 不稳 telemetry 的 P/C 后继零派发证据，不推断样品磁通 |
| EVAL-16 两供应商格式 | `tests/test_models.py::test_same_planner_input_unified_tool_proposal`；`reports/d12d2-compose-evidence.json` | U/C：OpenAI/DeepSeek 本地 TLS 格式与实际模型标识；未调用官方在线 API |
| EVAL-17 流式异常/用量 | `tests/test_models.py`（分片、截断、限流、超时、取消、invalid usage）；`tests/test_offline_provider.py` | U/C：真实 HTTPS 截断 SSE、429、缺失 usage 已验，两供应商各一轮；见 `reports/d12d3-model-faults.json`。超时/取消/非法 usage 的部署组合仍待补 |
| EVAL-18 凭据/能力不可用 | `tests/test_models.py::test_missing_key_and_version_mismatch`；`tests/integration/test_api.py::test_credentials_encrypted_never_returned_and_cas` | U/I/C：禁用测试凭据后 Agent 失败、HTTPS 请求为 0，见 `reports/d12d3-model-faults.json`；能力版本漂移的部署路径待补 |
| EVAL-19 Skill 边界 | `tests/integration/test_agents.py::test_skill_import_does_not_run_or_grant_permissions`、`test_disabled_skill_blocks_new_binding_and_existing_invocation`、`test_new_skill_version_does_not_change_existing_run` | I/C：第二次 HTTPS 响应返回前，经真实 API 禁用已绑定 Skill；轨迹 SKILL_DISABLED、提案提交被阻断，见 `reports/d12d3-model-faults.json`。版本漂移部署组合待补 |
| EVAL-20 MCP 默认拒绝 | `tests/integration/test_resources.py::test_discovery_and_remote_annotations_do_not_grant_access`、`test_schema_change_requires_new_review_and_stops_old_run`、`test_remote_scope_fields_cannot_be_forged_by_model` | I/实际本地 HTTP，Web fixture 验过独立授权；不是常驻 Compose MCP 故障验收 |
| EVAL-21 用量去重/未知 | `tests/integration/test_api.py::test_dashboard_and_usage_grouping_preserve_unknown`；`tests/test_models.py::test_invalid_usage_is_not_published` | I/U/C：两轮无 usage 的响应保留 usage=null，API unknown_usage_completions=2，见 `reports/d12d3-model-faults.json`；重复统计部署补证待完成，估算费用不得冒充实际账单 |
| EVAL-22 轨迹/权限 | `tests/integration/test_api.py::test_agent_proposal_read_model_requires_run_owner`、`test_dashboard_and_usage_grouping_preserve_unknown`；`apps/web/tests/e2e/console.spec.ts` | I/fixture 浏览器；C 正常轨迹及 Agent 跨实验 403 已验，完整角色/字段矩阵待补 |
| EVAL-23 知识撤权/来源 | `tests/integration/test_resources.py::test_knowledge_tool_context_is_rechecked_after_revoke`、`test_source_resource_and_experiment_isolation`、`test_data_corruption_detected_by_actual_checksum_before_analysis` | I/真实文件；Web fixture 撤权已验，C 运行中撤权组合路径待补 |
| EVAL-24 页面异常状态 | `apps/web/tests/e2e/workspace.spec.ts`、`apps/web/tests/e2e/console.spec.ts`；`apps/web/tests/deployment/compose.spec.ts` | fixture 18 项与 C 观察者/SSE/令牌刷新已验；不能宣称“每页全部状态”覆盖，数据页故障初次加载/下载禁用/重试恢复已有 C 证据；其余页面仍需逐页盘点补证 |

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

## 实现审查发现

- 当前 `src/alap/adapters/gateway/server.py` 装配的是模拟器、签名 RPC 和 mTLS listener；没有独立的设备失联策略监护循环。`ControlService` 的中心取消/UNKNOWN 处理不能替代 EVAL-09 的近端设备策略。后续先在模拟器明确设备分类、策略版本、失联证据和受控恢复，现场阈值/停机方法仍须 G1/G2 批准，不能默认所有设备统一关输出。
- `src/alap/adapters/gateway/transport.py` 校验签名 RPC 的 `gateway_id` 与本地身份；listener 校验客户端证书链。当前没有将客户端证书主体与资源登记进行显式映射的应用层证据。后续需用“同 CA 签发但身份错误”的证书验证，而非仅测缺证书/不可信 CA；签名约束仍保留，不能为了测试放宽现有认证。

## 后续门禁

1. 继续 D12d.3：优先补 EVAL-02/03/08/10/11/12/15/17–19 的运行期负路径和跨进程组合证据；按上述缺口逐项缩小范围，不直接标记通过。
2. 对 EVAL-09 边缘失联策略和 EVAL-14 证书身份映射进行实现审查，明确模拟可验部分与现场必须签署部分；缺少实现不能仅写作“已有测试”。
3. 完成逐页 EVAL-24 状态盘点及剩余权限组合后，才评审 D12d.3 是否可交接到长测；本轮不启动 D12d.4，更不进入 D13。
