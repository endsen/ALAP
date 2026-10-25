# D12d.3 持久化取消请求与确认

2026-10-24，第十六批；关联 EVAL-17、FR-021/Agent 运行权限及事务边界。当前源码实现与本地集成验收，尚未升级常规 Compose 镜像/数据库，不声称部署完成。

新增 d12_002 迁移：cancel_requested_at 记录首次请求，不修改 checkpoint revision；只允许非终态首次写入、其他字段保持相同。触发器拒绝清除、改时间、同步改绑定/checkpoint。原 API/Agent 角色已有 agent_runs 更新权限，不增加其他组件权限。请求经 run owner、当前成员/范围和来源复核；终态无操作、重复请求保留时间。

取消先持久化，随后尝试原运行独占锁。空闲可立即确认，运行中返回实际 RUNNING 与 cancel_requested=true。worker 在推进和后续工具调用前检查；提交事务在同一行锁下裁决取消与结果的顺序。先提交请求则丢弃未提交模型/工具结果与提案，保留历史、预算预留及 prior_stage/model_outcome_unknown 轨迹；取消 checkpoint 与轨迹同事务。已提交终态不被晚到取消覆盖。取消抢在模型预算预留提交前时，不再发起模型调用。安全边界确认不等于立即关闭已发出请求或回滚远端副作用。

API 状态投影增加 cancel_requested；请求确认前状态仍 READY/RUNNING。Web 对话显示“已请求取消，等待后台确认”并禁用重复取消/手动推进，继续轮询真实状态；控制台测试面板显示待确认与查看最新轨迹入口。相同 HTTP 幂等键重放可保持原待确认响应，最新状态使用 GET。

首次专项 5 失败/50 通过（76.01 秒），原因是旧 protect_agent_run 要求全部更新推进 revision，阻止独立请求字段；调整迁移为严格首次意图例外，原绑定保护不放宽。修正后取消专项及并发 worker/API 共 12 项通过（15.54 秒）：持久化新 store 恢复、owner/成员约束、预留前竞争、实际提案/工具提交前竞争、已完成终态优先、真实轨迹 INSERT 失败原子回滚、时间/绑定/checkpoint 不可篡改、API 待确认和确认后状态/幂等。报告 `d12d3-cancel-intent-targeted.txt`、`d12d3-cancel-intent-targeted-rerun.txt`。

首轮完整后端 612 通过/3 失败（561.44 秒）：一项旧进程测试仍期待取消 RUN_BUSY、两项受限状态精确比较未纳入新增字段。更新新契约预期，保持撤权后的失败收尾/拒绝读回/禁止重放断言；知识撤权组合 6 项通过（14.82 秒），见 `d12d3-cancel-intent-revocation-regression.txt`。完整后端复跑 **615 项通过（570.42 秒）**，真实 PostgreSQL/NATS 集成未跳过，迁移往返与格式/契约/生成/依赖检查通过；见 `d12d3-cancel-intent-backend-rerun.txt`。

Web 完整门禁通过：类型/格式/生成契约类型/生产构建、10 项单元与 20 项 fixture 浏览器（1.3 分钟），包含取消意图保持 RUNNING、重复操作禁用、worker 确认后才显示 CANCELLED。报告 `d12d3-cancel-intent-web-validation.txt`。该 UI 用例使用响应 fixture，真实取消 HTTP 语义由数据库/API 专项证明，不称为 Compose 浏览器证据。

新镜像、部署迁移、独立常驻 worker 的真实 HTTPS 响应期间取消、跨进程崩溃恢复及部署浏览器待后续验证。常规环境保持第十五批旧镜像，不将旧 RUN_BUSY 证据改写为新功能通过。未进入 D12d.4/D13，未推送 GitHub。

常规旧部署恢复后八服务运行、控制模式 ACTIVE；首页 200/匿名 API 401。测试库/角色/token/启用测试配置/活动运行/待发布事件均为 0，设备命令保持 45，原有 15 份 COMMITTED 文件校验通过，QA 端口及隔离模型网络移除。见 `d12d3-cancel-intent-final-runtime.json`。没有将旧业务数据库迁移为 d12_002，也没有将新源码门禁冒充已部署能力。
