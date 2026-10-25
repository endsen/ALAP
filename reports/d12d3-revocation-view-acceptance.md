# D12d.3 知识撤权状态视图与部署验收

日期：2026-10-23；第十一批，关联 EVAL-23/24、Agent 知识权限与 NFR-002。D12d.3 仍未完成。

第十批收尾修复后，原 load 继续拒绝撤权历史，导致用户无法查询终态。本批新增 owner-only run_summary 投影，详情与列表共用：先验证提交人、实验/资源成员权限与 bundle，再在同事务检查来源。仅 SOURCE_REVOKED 时返回标识字段、真实状态/版本、固定目标占位、result=null 和 access_error=SOURCE_REVOKED；其它错误照常拒绝。轨迹、提案和执行接口仍使用完整来源授权，不提供撤权历史。

契约在 AgentRunView 新增可选 access_error（唯一值 SOURCE_REVOKED），从 openapi.base.yaml 生成 OpenAPI 及 Web 类型。正常响应保持原字段。页面收到限制标识后隐藏缓存目标、提案和轨迹，禁用继续/停止操作；后台尚未收尾时显示等待，继续查询直到 FAILED。限制在当前会话保持，重新授权不自动显示旧缓存；不承诺服务器撤权尚未被页面获知前的即时清屏。

HTTP 专项 **2 项通过（6.11 秒）**，验证 RUNNING/FAILED 投影、列表不被单个撤权运行阻断、来源内容不泄露、历史接口拒绝、其他用户拒绝及原提交人实验权限撤销后的拒绝。首轮暴露 getAgentRun 的前置鉴权仍使用 load，已改为仅该 GET 操作使用相同受限视图鉴权，再运行通过。

Web 首轮因未设置项目浏览器缓存目录而无法启动 Chromium；已改用现有 `.local-deploy/browsers`，无新增依赖。浏览器后续暴露中文状态标签断言错误，修正后再跑；与后端门禁及镜像构建并行时出现 PostgreSQL ConnectionTimeout 和页面超时，保留 `reports/d12d3-revocation-view-web-contention.txt`，后续串行重跑，不放宽超时/产品权限断言。后端并行首轮 594 项通过、1 项 `test_dag_three_simulators_leave_iv_uncommitted` 因 PostgreSQL ConnectionTimeout 失败（885.39 秒），保留 `reports/d12d3-revocation-view-backend-contention.txt`，单独重跑完整门禁。串行完整后端 **595 项通过（549.94 秒）**，真实 PostgreSQL/NATS 集成未跳过，格式/契约/OpenAPI/生成文档与依赖检查通过。报告 `reports/d12d3-revocation-view-backend-validation.txt`；串行 Web 再次定位到新增测试误把普通状态徽标当作 role=status，已改为现有 title=FAILED 定位；撤权提示/缓存隐藏/动作禁用断言此前均通过。最终 Web 门禁通过格式/类型/生成类型一致性/生产构建、**10 项单元测试和 19 项浏览器测试（1.2 分钟）**，新增撤权缓存用例 5.7 秒通过。见 `reports/d12d3-revocation-view-web-validation.txt`。

部署脚本 `check_revocation_view.py` 使用新镜像、真实 HTTP API/Chromium 与独立数据库网络容器内的 AgentWorker。受保护上下文是维护入口经真实来源服务/运行时创建的 fixture，不宣称模型检索已经完成。撤权前无模型调用，撤权通过 API 执行；页面观察 READY 等待后，再由独立 worker tick 收尾并观察 FAILED。验证模型预留、提案、计划、审批、执行、命令、数据写入均为零。不是常驻模型响应期间撤权，也不是在线模型抗注入质量验证。

新镜像部署验证通过：实际 Chromium **1 项通过（5.4 秒，用例 4.2 秒）**，READY/revision 0 → FAILED/revision 1；目标占位/result=null/access_error 保持，真实列表可读而轨迹/提案拒绝。模型预留、提案、计划、审批、Run、Task、Command、Dataset 均为 0。见 `reports/d12d3-revocation-view-evidence.json`、`reports/d12d3-revocation-view-browser.txt`。后端镜像 `sha256:72ac2df361381a951f7ea094f7c03bfa6db03cae1ab4b143ca07b59c4944df4c`，Web 镜像 `sha256:992f194b1d61e8c7bbefda70d6f2ca5172ae3eab9120367e2e2925bbfa2c58ba`；构建报告 `reports/d12d3-revocation-view-build.txt`。最终八服务 ACTIVE，首页 200/匿名 API 401；测试库/角色/token/启用测试配置/活动运行/待发布事件均为 0，部署命令保持 45，15 份 COMMITTED 文件校验通过。QA 端口及隔离模型网络已移除，测试令牌已撤销；见 `reports/d12d3-revocation-view-final-runtime.json`。未推送 GitHub；未开始长测或现场。
