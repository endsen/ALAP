# D12d.3 已提交工具边界恢复

2026-10-25，第二十一批；关联 EVAL-08 与 Agent checkpoint/工具 ledger 的恢复约束。D12d.3 尚未完成。

复用常规新镜像/d12_002、独立常驻 Agent 和实际 HTTPS 模型替身。两供应商各两个位置，共四项部署案例通过。专用 worker 的合法 poll_s 配置设为 5 秒，给边界观察留出窗口；常规 worker 配置不变。没有手工 advance、checkpoint 种子替换或数据库状态修改。

第一个位置：首轮 HTTPS 完成并提交模型工具请求，checkpoint=RUNNING/tools、iterations=1、pending_ids=[offline-read]，尚无 tool invocation/history。第二个位置：真实 read_snapshot 工具已提交，checkpoint=RUNNING/model、iterations=1，pending 空、ledger/history/tool_calls 各一。等待符合目标后对临时 agent-drill 发 SIGKILL，确认退出码 137/非 OOM；停机后完整比较采集的边界字段，防止轮询竞争被当作成功。

显式启动新 worker 进程后均继续成功：iterations=2、history/tool_calls=2，offline-read 与 offline-propose 各一次，唯一提案保持 PROPOSED、最终结果引用该提案，预留预算 128000。已提交 read 的 call_id/tool_ref/input_hash 在恢复后保持一致。原轨迹作为前缀保留，最终 model_completed/tools_completed 各二；每项实际 HTTPS 请求总数为 2，模型替身要求先完成真实 read 工具交换才返回提案。计划、审批、执行 Run、Task、Command、Dataset 写入均为 0，没有把提案提升为执行。

终态后再次重启 worker，等待新进程空 tick，数据库证据、状态和轨迹完全不变；全部案例结束后再检查 HTTPS 请求数各为 2。见 `d12d3-tool-recovery-evidence.json` 与 `d12d3-tool-recovery-run.txt`。

完整后端 **619 项通过（568.43 秒）**，真实 PostgreSQL/NATS 未跳过，Ruff/格式、契约/生成文档/OpenAPI、依赖检查均通过，见 `d12d3-tool-recovery-backend-validation.txt`。收尾八服务运行、控制模式 ACTIVE，schema d12_002 与既有镜像一致；首页 200、匿名 API 401。测试库/角色/token/启用测试配置/活动运行/待确认取消/待发布事件均为 0；命令保持 45，15 份 COMMITTED 文件校验通过；QA 端口及隔离模型网络已移除，见 `d12d3-tool-recovery-final-runtime.json`。

本批只增加验收脚本/入口及专用轮询配置，没有修改产品业务、Web、契约、迁移、依赖或镜像，不重复上一批浏览器验收。该证据仅覆盖内置只读/提案工具的已提交边界；不证明 MCP 外部调用恢复、事务内断电、自动重启或现场设备安全停止。后续继续权限矩阵与 MCP 运行期授权故障，不进入长测/D13，未推送 GitHub。
