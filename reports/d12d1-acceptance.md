# D12d.1 常驻部署浏览器验收（2026-10-21）

真实 Compose 浏览器短测通过：3 项场景，最终 26.5 秒。使用部署的 Next.js、HTTP API、PostgreSQL、Engine、mTLS Gateway、HDF5 与 outbox/NATS；没有启动 D10/D11 的进程内执行 fixture。整个 D12d 尚未完成。

## 证据

- `d12d1-compose-browser.txt`：请求审批、批准、启动 Run、查看曲线、下载 HDF5；文件签名和 SHA-256 与服务端 Manifest 一致。
- 同一套件验证观察者不能在 UI 审批/写入，并直接发送合法结构的审批请求得到 HTTP 403；刷新页面后令牌不持久保留。
- SSE 请求在测试浏览器中被主动中断，页面显示过期状态并禁用写操作；恢复事件连接后重新获得权威快照与可写状态。这不是 Gateway 网络故障测试。
- `d12d1-compose-evidence.json`：本次唯一实验的权威记录为 1 个 SUCCEEDED Run、3 个 SUCCEEDED Task、3 条 SUCCEEDED Command、1 份 COMMITTED Dataset；outbox published_at 已完成，未发布数为 0。记录了实际运行镜像。
- Web TypeScript 和 Prettier 检查通过，10 项单元测试通过，见 `d12d1-web-unit.txt`。Web 产品代码未改，直接使用此前构建的生产镜像；本轮未重跑 D10/D11 全套 fixture 浏览器测试。
- 最终统一后端门禁 **565 项通过（409.28 秒）**，Ruff/格式、契约、生成一致性与依赖检查通过，见 `d12d1-backend-validation.txt`。八服务恢复运行、首页 200、匿名 API 401、测试库/角色为 0、QA 端口已移除，见 `d12d1-final-runtime.json`。

种子只保存未审批计划，审批及 Run 由浏览器执行。模型规划部分没有调用，不能把这个计划称为常驻 Agent 的产出。角色、资源范围与短期 token 由显式模拟维护入口配置，测试后两条 token 撤销，业务历史和观察者身份保留供追溯。没有付费模型、真实仪器或新应用依赖。

## 调试发现

第一轮确定性执行与 SSE 通过，观察者无法读快照：测试身份遗漏平台角色与计划所需资源读取范围；产品按既有范围规则拒绝，不应放宽权限。另一次重新运行种子因复用创建幂等键被拒绝，修正为每次唯一实验/幂等键。之后补齐 observer 角色与三个模拟资源的读取范围，仍无写入/审批权限，全新实验复验通过；直接后端 403 断言也通过。失败浏览器输出保留 `d12d1-compose-browser-initial.txt`、`d12d1-compose-browser-scope.txt`，不冒充成功报告。

会话开始时本地 rootless Docker 已退出；恢复后 PostgreSQL 容器有旧 runtime 残留。保留原数据卷重建该容器后启动，未删除业务记录或注册开机服务。

## 未完成项

本工作项只覆盖 EVAL-01 的审批后确定性链路、EVAL-07 的浏览器恢复以及部分 EVAL-24。常驻 Agent 经 API 模型适配形成提案的部署链路、完整 EVAL-02–24 故障/权限矩阵、实际 24 小时负载均未完成。按 `docs/D12D_ACCEPTANCE.md` 下一步进入 D12d.2；D13 未启动。本轮未推送 GitHub。
