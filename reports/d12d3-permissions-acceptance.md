# D12d.3 部署 Agent 权限矩阵

2026-10-25，第二十二批，关联 EVAL-22。D12d.3 尚未完成。

常规 d12_002/既有镜像，独立常驻 Agent 通过实际本地 HTTPS 模型替身完成两供应商格式的只读与提案链路。每项两次 HTTPS、一次只读调用与一份 PROPOSED 提案，不手工 advance。使用随机隔离实验和四个独立测试身份，成员授权和撤销均经实际 API；初始身份由维护 seed 创建，不模拟认证或响应。

每供应商 49 项、合计 **98 项 HTTP 权限断言通过**：observer/operator/approver 虽有相同设备范围，仍不能读取提交人的详情、轨迹、提案，也不能取消或推进其运行；三个角色的自身运行列表为空，用量和仪表板内 Agent 用量为空，不泄露提交人运行 ID。outsider 无实验成员权限，相关接口 403；匿名请求 401。三个角色经 owner API 撤权后，列表、用量、仪表板新请求立即 403。失败响应没有 items/result 成功字段。运行提交人的状态、轨迹和提案在测试前后完全一致。计划/审批/执行 Run/Task/Command/Dataset 写入均为 0。

证据：`d12d3-permissions-evidence.json`，运行日志：`d12d3-permissions-run.txt`。专用 worker/模型容器与网络移除，测试身份及令牌禁用、成员权限撤销；业务历史保留。完整后端 **619 项通过（568.63 秒）**，真实 PostgreSQL/NATS 未跳过，Ruff/格式、契约/OpenAPI/生成文档及依赖检查通过，见 `d12d3-permissions-backend-validation.txt`。最终八服务运行、模式 ACTIVE、d12_002/镜像一致，首页 200/匿名 API 401；测试库/角色/token/启用测试配置/活动运行/待确认取消/待发布事件以及本批启用测试身份和成员权限均为 0。命令保持 45、15 份 COMMITTED 文件校验通过，QA 端口和隔离模型网络已移除，见 `d12d3-permissions-final-runtime.json`。

本批只增加部署验收工具和可选 fixture 身份/清理分支；没有修改产品业务、契约、数据库迁移、依赖或镜像，不重复上一批 Web 验收。当前创建运行者是部署 admin/实验 owner；不代表非管理员运行提交人的全角色对照、受限资源字段、运行中提交人撤权、MCP 授权撤销或浏览器缓存权限行为已完成。下一批继续这些权限缺口及 MCP 运行期授权故障，未进入长测/D13，未推送 GitHub。
