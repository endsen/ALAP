# D12d.3 知识撤权终态收尾修复

日期：2026-10-23；第十批，关联 EVAL-23、Agent/知识权限边界与 NFR-002。D12d.3 尚未完成。

第九批发现：来源撤权使 load/commit 拒绝访问，但 AgentRun 留在 RUNNING，worker 每次轮询都重复拒绝。本批在 AgentRuntime.step 持有原独占锁期间捕获 SOURCE_REVOKED，通过新增端口 fail_revoked_source 请求受限收尾，随后仍向调用者抛出原错误，不返回已撤权历史。

PostgreSQL 实现要求当前所有权会话、原提交人及实验/资源权限、bundle hash 均有效；同事务重新检查来源，只有确认 SOURCE_REVOKED 才更新 READY/RUNNING 为 FAILED/done，并与 blocked 审计原子提交。既有历史、来源引用、token 预留保留，result=null；审计保留 prior_stage，inflight 时标记 model_outcome_unknown。已经终态、来源仍有效或已恢复授权均不改写。所有权连接丢失不能重连提交，状态更新用 revision CAS；没有取消来源读取权限检查或新增可绕过权限的 API。

独立 fork worker 的调用前/响应期间撤权测试改为要求终态收尾，后续 tick 不再选择此运行，模型不重放；正常检索和文献注入阻断继续回归。新增受限收尾负路径覆盖无锁、错误提交人、有效/恢复授权、既有终态、审计 INSERT 失败事务回滚和所有权连接终止；响应期间并发取消/收尾被独占锁拒绝。

首轮专项及资源权限回归 **41 项通过（79.59 秒）**，见 `reports/d12d3-revocation-closure-targeted.txt`；之后追加提交人自身撤权和重新授权后不重放断言，完整后端门禁 **593 项通过（560.30 秒）**，真实 PostgreSQL/NATS 集成未跳过；Ruff/格式、生命周期参考、合订本、OpenAPI/契约及依赖检查通过，见 `reports/d12d3-revocation-closure-backend-validation.txt`。未改 Web，沿用最近完整 Web 门禁。最终八服务 ACTIVE、首页 200/匿名 API 401；测试库/角色/token/活动运行/待发布事件均为 0，部署命令保持 45，15 份 COMMITTED 文件校验通过，QA 端口和隔离模型网络已移除。见 `reports/d12d3-revocation-closure-final-runtime.json`；此为既有镜像环境核对，不代表修复已部署。当前为源码及真实 PostgreSQL/独立进程验收，子进程使用离线模型；未验证 Compose HTTPS 撤权或 API/页面最小状态呈现。正常 load 仍拒绝撤权历史，所以不宣称页面可以直接读取 FAILED。其它来源类型（MCP/EVIDENCE）、提交人自身撤权等情况不在本次自动收尾范围。

未更新部署镜像；常规模拟部署恢复后仍运行上次已验证镜像，不将其健康核对称为本次产品修复的部署验收。下一批接续最小状态呈现与实际部署知识链路。未推送 GitHub、未进入长测或现场。
