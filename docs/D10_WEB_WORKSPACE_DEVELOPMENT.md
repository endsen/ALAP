# D10 · Web 实验工作区开发交接

本期实现位于 `apps/web`，使用真实 D09 HTTP API。验收状态和最终结果以根目录 `IMPLEMENTATION_STATUS.md` 为准。

## 实现范围

- Next.js App Router / React / TypeScript，锁定 Node 24 与 npm 依赖。OpenAPI 生成前端共享类型。
- 平台访问令牌登录、退出、实验筛选/分页、样品与实验创建；令牌仅保存在页面内存，刷新重新登录。
- 三栏实验工作区：目标会话、专用 Agent 提案/处理轨迹、设备范围与执行状态。每个目标绑定一个持久 Agent Run；不是完整 IM 会话系统。
- 计划草案由提案与当前 scope/version 生成，禁止把旧提案自动换成新快照。任务依赖、参数/约束、版本差异可查看；参数修订通过新提案形成新版本，本期没有任意 JSON 编辑器。
- 审批请求/批准/拒绝/撤销、创建 Run 和暂停/取消/恢复有确认窗口，绑定状态版本。设备操作仍由执行引擎/Gateway 核验。
- SSE 携带 Bearer 和 Last-Event-ID；重复事件忽略，缺口恢复快照，断线禁用写操作，撤权清除工作区，会话失效回登录。
- 设备页面只读；没有新鲜读回时显示未知。数据仅对 COMMITTED 校验通过记录提供曲线与 HDF5 下载，预览最多 2000 点、保留端点并标记降采样。

## 后端增量

增加 `/experiments/{id}/available-agents`、`/experiments/{id}/plan-context`、`/datasets/{id}/series`。扩充 `/me` 和工作区 snapshot/Agent Run 读模型。共 64 个契约操作，不需要新数据库迁移。`application/series.py` 在解析前后通过数据服务复核权限与校验和；原始数据仍以下载文件为准。

## 启动

先按 D09 文档启动 FastAPI，并为用户分配实验和设备范围、发布适用 Agent。生产配置不能使用测试 fixture。

```bash
npm --prefix apps/web ci
ALAP_API_ORIGIN=http://127.0.0.1:8000 npm --prefix apps/web run build
npm --prefix apps/web run start
```

`ALAP_API_ORIGIN` 是服务端 rewrite 的**构建时**配置；改变 API 地址后需要重新构建。浏览器只访问同源 `/api/v1`，不配置公网供应商密钥。默认端口 3000，默认监听回环地址。对外部署的 TLS、身份接入与常驻执行进程由 D12 补齐。

## 验证入口

```bash
# PostgreSQL/JetStream 与环境变量准备同 D09
.venv/bin/python scripts/check.py
npm --prefix apps/web exec -- playwright install --with-deps chromium --only-shell
.venv/bin/python scripts/check_web.py
```

Web 门禁检查类型生成漂移、TypeScript、单元测试、生产构建和 Chromium 浏览器用例。它将 API 构建目标设为回环 58000，Web 监听 53000；部署前应使用真实 API 地址重新构建。CI 工作流包含两个门禁，但本地验收不等同远程 CI 已通过。

浏览器测试启动 `tests/web_server.py`：真实迁移 PostgreSQL 隔离 schema、FastAPI、LangGraph、模拟 Gateway、HDF5 和测试专用执行线程。LLM 用确定性离线替身，不访问任何付费 API。该线程只用于验收，不是生产 scheduler。测试状态文件默认 `/tmp/alap-d10-web.json`，权限 0600，仅含临时身份/测试数据库信息，退出清理；不提交到仓库。浏览器 trace/video 关闭，避免录制 Authorization。本机验收可通过 `ALAP_BROWSER_EXECUTABLE` 指定已有 Chromium，本轮使用 Chrome for Testing 145.0.7632.6；CI 使用 Playwright 锁定下载的浏览器，不能据本地结果声称该版本或跨浏览器验收已通过。

## 边界与后续

D11 实现 Agent、模型、Skills、MCP、知识、仪表板、用量、审计与设置管理页面。D10 不把这些导航占位当作已实现。Agent 显示真实处理状态和持久结果，不伪造逐字 token 流。设备新鲜遥测、全时常驻执行、SSO、部署容量和现场仪器验证仍在后续工期。
