# D12d.3 新版本部署与取消闭环

2026-10-24，第十七批；关联 EVAL-17/24 与第 22 章取消事务。D12d.3 尚未整体完成。

升级前只读核对八服务及原有 45 条命令/15 份 COMMITTED 文件。使用既有 operations.py 冷备份流程停止所有服务并生成加密完整快照，私有目录 `.local-deploy/backups/pre-cancel-deploy-20261024`，密钥单独存于 `.local-deploy/backup-keys`，不进入仓库。报告 `d12d3-cancel-deploy-backup.txt`；旧精确镜像仍保留，未执行数据卷删除。本次未重复冷恢复演练，不把备份生成等同于新增恢复验收。

按锁文件构建新后端/Web 镜像后，仅启动 PostgreSQL，以维护身份显式调用 `alap.adapters.postgres.deployment migrate --directory /private/deployment`，随后刷新组件权限并启动新镜像。schema 从 d12_001 升到 d12_002；前后命令均为 45、COMMITTED Dataset 均为 15，历史运行的取消时间初始为空。新旧镜像完整摘要和核对结果见 `d12d3-cancel-deploy-upgrade.json`，构建日志 `d12d3-cancel-deploy-build.txt`。正常 up 不隐式迁移。

扩展本地 TLS/SSE 替身 cancel_hold 模式：发送第一片不完整 read_snapshot 工具参数后等待 release 文件，释放后发送剩余合法响应和 usage。专用 profile timeout_seconds=90/max_attempts=1，模型地址和格式仍经真实适配器，内网与测试 CA 限于专用容器，不调用线上供应商。OpenAI/DeepSeek 各验证调用前取消、运行中 API 取消、实际 Chromium 页面取消，共六项全部通过。

调用前 READY→CANCELLED，专用 worker 重启后请求数仍为 0、预算/iterations 为 0。运行中先确认服务端已发送分片，然后取消返回 200、RUNNING、cancel_requested=true；同一幂等键重放仍返回相同待确认结果。释放屏障后常驻 worker 确认 CANCELLED/done，保留预算和 prior_stage=inflight/model_outcome_unknown=true 审计，最终请求为 1、iterations=1。没有 model_completed 事件、工具提交、提案或计划/审批/执行/命令/Dataset 写入；终态再次取消不改状态/轨迹。全部场景结束后再次核对请求数。见 `d12d3-cancel-deploy-evidence.json` 与 `d12d3-cancel-deploy-run.txt`。

两个真实部署浏览器用例通过（OpenAI 6.1 秒、DeepSeek 5.5 秒）。浏览器经 Web/API 提交取消，先看到等待确认和 RUNNING、重复取消/推进禁用，再释放模型屏障并看到 CANCELLED；页面未提前伪装终态，浏览器持久存储为空。没有 mock HTTP 状态。报告 `d12d3-cancel-deploy-openai-browser.txt`、`d12d3-cancel-deploy-deepseek-browser.txt`。旧版 RUN_BUSY 报告保留不改，当前入口改为新版严格断言。

模型/替身专项 81 项通过。完整后端 **615 项通过（566.16 秒）**，真实 PostgreSQL/NATS 集成未跳过，Ruff/格式、契约/OpenAPI、生成及依赖检查通过，见 `d12d3-cancel-deploy-backend-validation.txt`；本批产品业务/Web 源码未改变，生产构建和实际部署浏览器已验，上一批 Web 10 单元/20 fixture 结果保持各自范围。取消仍是安全边界确认，不承诺即时终止 socket、撤回远端副作用或退还模型费用。worker 中断恢复、更多权限/预算组合仍待后续；不进入长测或现场，未推送 GitHub。

最终八服务运行、控制模式 ACTIVE、schema=d12_002，实际后端/Web 镜像摘要与升级记录一致。首页 200/匿名 API 401；测试库/角色、有效 token、启用测试配置、活动运行、待确认取消、待发布事件均为 0；命令保持 45，15 份 COMMITTED 文件校验通过，QA 端口与隔离模型网络已移除。见 `d12d3-cancel-deploy-final-runtime.json`。
