# D12d.3 提交人撤权修复部署验收

2026-10-25，第二十四批。关联 FR-010/014/027、NFR-001/002/012 与 EVAL-22。D12d.3 尚未完成。

升级前完成加密冷备份 `pre-access-deploy-20261025`（密钥独立保存于私有目录，不纳入报告），全部源服务停稳。随后构建并部署后端镜像 `sha256:a7a87199c15b8061cb0093de4c00e15498bb26af27607b8319d5c39424036025`，Web `fd41b31a` 保持。原始镜像仍保留；本次无数据库迁移，d12_002/命令 45/COMMITTED 数据 15 保持。镜像内检查确认包含 fail_revoked_access。见 `d12d3-access-deploy-backup.txt`、`d12d3-access-deploy-build.txt`、`d12d3-access-deploy-upgrade.json`。

**六项实际部署案例通过**：OpenAI/DeepSeek 格式各调用前成员撤权、HTTPS 响应首片后成员撤权、首片后设备范围缩减。提交人为独立非管理员身份（平台默认 observer，实验明确授予 operator）；没有借助 admin 身份提交 AgentRun。admin/实验 owner 仅通过实际成员 API 改变授权。专用常驻 worker 与隔离 TLS 模型替身实际通信，无手工 advance/终态 seed。

调用前 READY/model 撤权后，worker 收尾 FAILED/ACCESS_REVOKED，请求 0。响应期间先等待真正 SSE 首片、通过 API 撤权/缩范围，再确认运行详情/轨迹/提案/取消均 403，最后释放模型流；两类各一次 HTTPS，请求预算保留、受限终态追加一次 blocked trace，prior_stage=inflight、model_outcome_unknown=true。最后已提交 checkpoint 的其余字段保留；未发布本次模型结果或工具/提案，计划/审批/执行 Run/Task/Command/Dataset 写入均为 0。

再次授权后提交人可读到真实 FAILED，提案为空。重启独立 worker 并等新进程空 tick，数据库 checkpoint/版本/轨迹/写入计数及 HTTPS 请求数保持不变；终态不重放。最后再次撤销测试成员权限，统一 finally 禁用身份/令牌/配置并清理临时容器/网络，保留审计历史。证据 `d12d3-access-deploy-evidence.json`，日志 `d12d3-access-deploy-run.txt`。

完整后端 **638 项通过（652.42 秒）**，真实 PostgreSQL/NATS 未跳过，Ruff/格式、契约/OpenAPI/生成文档及依赖检查通过，见 `d12d3-access-deploy-backend-validation.txt`。收尾八服务运行、模式 ACTIVE、d12_002/新镜像一致，首页 200/匿名 API 401；测试库/角色/token/启用测试配置及身份/成员权限/活动运行/待确认取消/待发布事件均为 0。命令保持 45、15 份 COMMITTED 文件校验通过，QA 端口与隔离模型网络移除，见 `d12d3-access-deploy-final-runtime.json`。

无新增产品、迁移、依赖或 Web/API 契约改动；本批将上一批源码修复部署并增加验收工具。未重复无变更的 Web 浏览器验收。主体禁用仍只有数据库集成证据；MCP 授权撤销、完整受限字段/角色/页面矩阵继续保留，不将本地替身等同线上模型或现场验收。不进入长测/D13，未推送 GitHub。
