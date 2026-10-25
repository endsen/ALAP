# D12d.3 模型能力与 Skill 版本绑定

2026-10-25，第二十批；关联 EVAL-18/19。D12d.3 尚未整体完成。

复用既有部署镜像/d12_002、本地 HTTPS 替身和常驻 Agent。两供应商各三种场景，共六项实际 API/数据库/HTTPS 验证通过。创建 READY 运行后仅暂停专用 agent-drill，通过正式 API 操作版本，再启动真实 worker；无手工 advance、无直接改写 bundle。

模型新版本：尝试在 v1 内改 tools 能力被 409 VERSION_CONFLICT 拒绝；创建 v2 并声明 tools=unsupported，新 Agent v2 绑定该模型后发布返回 422 MODEL_UNAVAILABLE，保持 DRAFT。既有运行 bundle/hash/model version 保持 v1，真实 HTTPS 完成只读答复，请求 1。

旧模型禁用：同版覆盖仍拒绝，创建可用的 v2，再以当前 revision 禁用 v1。旧运行保持 v1 绑定并以 CONFIG_DISABLED 失败，即使新版可用也不自动切换，HTTPS 请求 0。此场景在首次模型调用前禁用，不声称调用中禁用已验证。

Skill 新版本：同版内容覆盖返回 409 VERSION_CONFLICT，v2 新内容成功导入发布。旧运行 bundle/hash/skill refs 均保持不变；真实 HTTPS 替身要求收到 VERSION_PIN_OLD、拒绝 VERSION_PIN_NEW，最终只读完成、请求 1，证明运行上下文没有静默换版。新版本本身不授予额外工具权限，未执行设备动作。

六个实验均零 Agent 工具提交/提案，以及计划/审批/Run/Task/Command/Dataset 写入。场景结束后再次核对请求总数。见 `d12d3-version-binding-evidence.json` 与 `d12d3-version-binding-run.txt`。共享清理按本批独立 case 的 extra_versions=[2] 禁用测试 v1/v2 模型、Agent、Skill，令牌撤销，审计保留；其他实验版本不在清理范围。

模型与替身专项 **85 项通过（0.98 秒）**。完整后端 **619 项通过（579.45 秒）**，真实 PostgreSQL/NATS 集成未跳过，格式/lint、契约/OpenAPI、生成及依赖检查通过；见 `d12d3-version-binding-backend-validation.txt`。本批无产品业务、Web、契约、迁移、依赖或镜像变化，不重复已完成的浏览器验收。这里验证的是管理 API 的版本/能力声明与发布约束，不是线上供应商能力探测、真实能力退化或全部依赖升级组合。后续继续权限矩阵及剩余故障场景，不进入长测/D13，未推送 GitHub。

最终八服务运行、模式 ACTIVE、schema=d12_002/镜像一致；首页 200/匿名 API 401。测试库/角色/token/启用测试 Agent/Skill/模型/凭据（含 v2）、活动运行、待确认取消和待发布事件均为 0；命令保持 45，15 份 COMMITTED 文件校验通过，QA 端口与隔离模型网络移除。见 `d12d3-version-binding-final-runtime.json`。
