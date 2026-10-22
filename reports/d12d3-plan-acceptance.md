# D12d.3 批准后计划变更验收

日期：2026-10-21；第三批本地部署验证。关联 FR-003/004/005、NFR-001/002 与 EVAL-12；D12d.3 仍进行中，未进入长测或现场。

新增 `deploy/simulation/check_plan_fault.py`，使用运行中的八服务和真实 HTTP API。创建唯一未审批模拟计划后，以管理员测试身份请求并批准；把温度目标和相关读回条件从 295 K 改为 296 K，保存第二版计划。

实际结果见 `reports/d12d3-plan-evidence.json`：计划 hash 改变，旧审批 SUPERSEDED；旧 If-Match 启动请求返回 409 STATE_CONFLICT，最新 If-Match 但复用旧 approval_id 返回 409 PLAN_STALE。两次拒绝不改变实验版本，随后观测中游标保持稳定。常驻 Engine 继续轮询，五秒观测后 Run、Task、Command、Dataset 均为零，全局命令保持 36，outbox 待发布为零。

业务变更全部使用正式 API；只用数据库只读查询独立对账。测试身份/范围种子与令牌撤销沿用模拟维护模式，令牌不写报告。finally 撤销本次 owner/observer 两条令牌；保留两个计划版本和失效审批审计。没有新应用依赖、迁移、契约或产品业务代码改动。

完整后端门禁 **574 项通过（435.08 秒）**，真实 PostgreSQL/NATS 集成未跳过，Ruff/格式、契约/OpenAPI、生成文档及依赖一致性检查通过，见 `reports/d12d3-plan-backend-validation.txt`。Web 产品及浏览器入口未改，不重复此前浏览器验收；本批是实际 HTTP 部署验收，不称浏览器测试。

本场景没有创建排队或运行中的 Run，因此不会把既有 `test_superseding_plan_invalidates_approval_and_freezes_run` 的 I 级冻结证据提升为 C 级。策略/能力变化组合仍待部署补证。后续继续活动数据失败、过期/不稳回读、其余权限组合及边缘失联监护/证书身份映射缺口。未调用模型或真机，未推送 GitHub。

收尾八服务运行、模式 ACTIVE，仅 Web 发布 127.0.0.1:3000；首页 200、匿名 API 401。临时测试库/角色、有效令牌、活动 AgentRun/执行 Run、启用测试配置均为 0，命令总数保持 36。重启后的待发布事件观察为 26→10→0，排空后保存 `reports/d12d3-plan-final-runtime.json`；QA 端口关闭，未注册系统服务。
