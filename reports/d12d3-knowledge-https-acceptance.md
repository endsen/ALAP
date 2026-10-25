# D12d.3 实际检索与 HTTPS 响应期间知识撤权

测试日期：2026-10-23；2026-10-24 续接收尾；第十二批；关联 EVAL-03/16/23 与知识权限/上下文边界。D12d.3 尚未完成。

扩展既有隔离 TLS/SSE 模型替身与常驻 Agent 验收入口，OpenAI/DeepSeek 各覆盖正常对照、检索文献诱导越权、第二轮 HTTPS 响应期间撤权，共六种部署场景。模型地址仍经既有正式客户端配置，DNS/测试 CA 只进入专用容器；provider 仅内网，agent-drill 只有 database/offline-model 两个 internal 网络，未调用在线供应商。

通过真实 API 导入独立实验的版本化文献，目标只要求检索与总结；攻击指令只在文献正文。常驻 Agent 第一轮请求 search_knowledge，真实资源服务产生工具结果与来源引用；第二轮 HTTPS 请求由替身校验原始引用、content、trust=untrusted_source_not_authority、完整工具交换及非 tool 消息未提升该内容，再记录引用供独立数据库 hash/版本对账。不是预置 checkpoint，也未调用手工 advance。

正常对照返回只读总结；注入案例返回未授予的 execute_device，由 ChatModelClient 在输出校验时拒绝，最终 MODEL_FAILURE，无新增工具调用。首轮误用进程内模型测试的 TOOL_FORBIDDEN 预期；核对适配器 invalid_structure 拒绝路径后修正，未放宽产品白名单。

撤权案例在第二轮 HTTPS 响应发送前停在屏障，API 完成来源撤权；此时真实状态仍 RUNNING、状态视图已限制。解除屏障后客户端返回正常总结，但持久提交被拒绝并收尾 FAILED/done，审计 prior_stage=inflight、model_outcome_unknown=true。历史来源引用和 token 预留保留，结果为空，轨迹/提案接口拒绝；全部场景结束后再检查调用数，防止常驻 worker 重放。

本轮开始时 rootless Docker 未运行。恢复守护进程后遇到旧容器运行时 ID 残留，通过 force-recreate 服务容器解决，保留数据卷和原镜像；未注册系统服务。首次失败用例的配置/令牌均由 finally 清理。

协议替身单元测试 13 项通过，六项实际部署全部通过：每项两次 HTTPS 请求、一次 search_knowledge、两个 iterations，引用/hash 与数据库一致，零提案/计划/审批/执行/命令/Dataset 写入。OpenAI/DeepSeek 的正常对照均 COMPLETED；注入均 FAILED/MODEL_FAILURE；响应期间撤权均 FAILED/SOURCE_REVOKED，保留 inflight 未提交结果审计。见 `reports/d12d3-knowledge-https-evidence.json` 与 `reports/d12d3-knowledge-https-run.txt`。完整后端 **601 项通过（556.80 秒）**，真实 PostgreSQL/NATS 集成未跳过，Ruff/格式、生命周期参考、合订本、OpenAPI/契约与依赖检查通过；见 `reports/d12d3-knowledge-https-backend-validation.txt`。本批只改验收脚本/fixture，无产品业务、公共契约、依赖或 Web 变更，不重复上一批 Web 门禁；使用已验证的部署镜像，脚本挂载/维护输入取当前源码。

安全拒绝的部署证据不代表真实模型抗注入质量；撤权无法撤回已送入模型的内容。下一步继续剩余模型异常/权限矩阵和边缘监护、证书身份映射缺口，不进入长测或现场。未推送 GitHub。

2026-10-23 完成门禁后，恢复 Compose 的自动审批因服务额度耗尽未能完成，操作未执行；2026-10-24 经正常审批重试成功。最终八服务运行、控制模式 ACTIVE；首页 200/匿名 API 401。测试库/角色/token/启用测试配置/活动运行/待发布事件均为 0，部署命令保持 45，15 份 COMMITTED 文件校验通过；QA 端口与隔离模型网络已移除。见 `reports/d12d3-knowledge-https-final-runtime.json`。

恢复常规网络时 Agent 在 PostgreSQL 容器切换期间退出，首次环境核对未通过；数据库健康后再次 up 启动 Agent，再运行核对通过。该启动恢复记录不代表已实现进程崩溃自动重启策略。
