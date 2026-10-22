# D12d 常驻平台集成验收

D12c.3 已验证冷备份与隔离恢复；D12d 验证实际常驻链路、故障和长时间负载。依据第 12 章 EVAL-01–24 与第 20 章分期计划，分别记录代码、短测和实际验收证据，不用进程存活时间替代负载运行时间。

## 验收顺序与当前边界

| 工作项 | 验收内容 | 通过标准 |
|---|---|---|
| D12d.1 常驻确定性执行与浏览器 | Web → HTTP API → PostgreSQL → Engine → mTLS Gateway → HDF5 → 浏览器；SSE 中断、观察者限制、刷新令牌清除 | 页面发起审批/Run，三个任务成功，数据下载校验和匹配，outbox 持久发布；不使用进程内模拟执行线程 |
| D12d.2 常驻 Agent 与 API 模型链路 | API 兼容的本地离线供应商替身、模型配置、Agent worker、提案、版本/预算/权限；与执行审批链组合 | 实际 HTTP 模型适配与常驻 Agent 产生可追溯提案，无付费模型或真机；不把预置计划称为 Agent 产出 |
| D12d.3 故障与权限矩阵 | EVAL-02–24 逐项链接既有单元/集成证据与缺少的跨进程证据，覆盖 ACK 丢失、UNKNOWN、重启、消息中断、冲突、数据失败及注入 | 记录注入位置、可观测结果、禁止副作用与恢复动作；未验证项明确保留，不把 fixture 测试全部提升为部署验收 |
| D12d.4 实际长时间负载 | 至少 24 小时 wall-clock，持续有界模拟任务、状态/延迟/失败计数、命令与数据对账 | 记录起止、负载间隔、计划/命令/数据数量、故障/恢复与最终对账；断电/中断留下未完成检查点，不通过改时钟补足时间 |

本轮从 D12d.1 开始，后续工作项须按顺序完成。D12d 整体通过前不进入 D13。

## D12d.1 可重复入口

先按 `deploy/simulation/README.md` 启动已有八服务，再运行：

```bash
# Node 24 和 npm ci 按 apps/web/package-lock.json；浏览器存于忽略目录。
cd apps/web
PLAYWRIGHT_BROWSERS_PATH=../../.local-deploy/browsers npm exec -- playwright install chromium
cd ../..
.venv/bin/python deploy/simulation/check_browser.py
```

浏览器版本由锁定 Playwright 管理。入口独占本地维护锁，拒绝缺失/停止的服务；在已有 simulation 创建唯一 `EXP-BROWSER-*`。维护身份仅配置测试观察者和实验资源范围，API 受限角色调用现有应用用例保存计划。**不预置审批、Run 或模型凭据**。随后真实 Chromium 操作部署端口 3000；测试不启动替代 API、内嵌执行线程或独立前端。

页面完成请求审批、人工身份审批、创建 Run、实时查看数据、下载 HDF5；比对文件签名和 SHA-256。观察者检查及 SSE 故障测试使用同一真实部署，SSE 故障只阻断测试浏览器的事件请求，明确不是设备网络故障。测试结束读取 PostgreSQL 权威记录，核对 1 Run/3 Task/3 Command/1 COMMITTED Dataset，并等待 outbox 的 published_at 完成。

短期测试令牌只存在 0600 私有临时状态文件，日志写报告前脱敏；关闭截图、录屏和 trace，测试输出目录也位于私有临时目录并在结束时移除。finally 撤销本次两条令牌。保留实验、审计、数据和观察者身份供追踪，不删除业务历史。失败不自动重试审批或执行，重新运行使用新的实验，不重放未知命令。

输出：`reports/d12d1-compose-browser.txt`、成功时生成的 `reports/d12d1-compose-evidence.json`。这覆盖 EVAL-01 的审批后执行部分、EVAL-07 的浏览器连接恢复及 EVAL-24 的部分状态路径；**不覆盖 Agent 规划、真实供应商兼容性、完整权限矩阵、设备 ACK 故障或长测**。实际结果以实施状态为准。

## 后续续接注意

- D12d.2 应使用独立本地 HTTP 供应商替身，通过真实模型适配器处理请求/响应/用量；不得直接在 Agent 中替换内存对象后称为 API 部署联调。当前常驻 Agent 的实验白名单需显式配置相应测试实验，不能扩大到所有实验。替身和测试配置不得混入正常供应商凭据。
- D12d.3 先整理第 12 章案例的证据层级，尤其区分浏览器 SSE 中断、NATS 中断、Gateway 网络断连和设备 ACK 丢失；这几类故障不能互相替代。
- D12d.4 需要独立可续查的负载驱动、持久日志、停止机制和运行时生命周期管理。当前前台 rootless daemon 的存在不能证明重启续跑或 24 小时负载能力；须先验证驱动器的小规模试跑，再启动真实长测，并在状态文件保存实际进程、起止与进度位置。

## D12d.2 常驻 Agent 与离线供应商链路

入口：启动正常八服务后运行 `.venv/bin/python deploy/simulation/check_agent.py`。关联 FR-003/004/005/006/014、FR-011 和模型 API 接入要求，以及 NFR-004/005/008/009/012 的审计、状态、完整性、轨迹与保密性局部门禁。入口独占维护锁，创建两个唯一实验、版本化模型/Agent 与短期管理员令牌；不预置提案、计划、审批或执行 Run。模型能力标为 `declared`，不冒充官方供应商实测。

测试增加两个临时容器：无数据库权限的 TLS/SSE 供应商替身，以及仅允许本次实验的真实 Agent worker。专属 internal 网络将官方主机名解析到替身；一天有效的私有证书只挂载并信任于测试 worker，生产 `official-https-only` 校验不改，通常 Agent 的实验白名单不变。测试 worker 只有 database 与 offline-model 两个 internal 网络，无外部模型出口；替身无发布端口、无真实凭据，凭据仅固定的无效测试字符串。临时 CA/key 不进入正常容器或仓库。

Chromium 提交目标，禁止调用 `/advance`，等待后台 worker 完成。真实 `ChatModelClient/HTTPSChatTransport` 发送请求，替身验证 OpenAI `max_completion_tokens` 与 DeepSeek `max_tokens`、路径、工具范围及 snapshot，先返回分片 `read_snapshot` 调用，再从完整工具往返生成分片 `propose_plan` 响应。它是确定性的协议替身，使用示例任务生成模型响应，不代表模型推理质量；数据库提案确由 Agent 的工具校验与提交路径产生。

页面自动读取后台 Agent 状态，终态刷新提案及轨迹；网络/权限错误停止轮询，卸载取消定时器，人工推进期间不轮询。验收检查两次模型调用、两次工具调用、模型版本/实验范围、保守预留预算与独立的供应商用量；越出 Agent 实验范围的合法请求返回 403。提案完成前的审批/执行审计为零，再由浏览器人工身份提交计划、批准和启动 Run，最终核对三个成功命令、一份 COMMITTED HDF5、下载 SHA-256 和 outbox 清空。

正常结束或异常 finally 停止并移除两个临时容器，禁用本次 Agent/模型连接/凭据、撤销令牌，删除空测试网络与私有临时目录；审计和业务数据保留。强制终止宿主进程时 finally 无保证，续接须检查残留 `agent-drill`/`offline-provider`，停止后清理，不能绕过八服务前置检查。报告为 `reports/d12d2-compose-agent.txt` 和 `reports/d12d2-compose-evidence.json`。此验证不覆盖官方在线供应商、实际计费、并行模型吞吐、完整故障矩阵或 24 小时长测。

## D12d.3 故障矩阵续接

逐项状态与证据层级见 [D12D_FAULT_MATRIX.md](D12D_FAULT_MATRIX.md)。本轮先补真实 TCP 响应切断和实际 Compose NATS 停服/恢复，后者入口为 `deploy/simulation/check_messaging_fault.py`。两种故障不可互相替代；完整故障矩阵仍进行中，不能据此开始 24 小时长测或现场操作。
