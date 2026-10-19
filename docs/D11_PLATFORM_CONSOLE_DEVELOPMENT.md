# D11 · Web 平台控制台

日期：2026-10-19。本期在 D10 Next.js 工作区上接入 D09 管理 API，并补齐控制台所需的详情、校验和角色操作。验收状态以根目录 IMPLEMENTATION_STATUS.md 为准；没有启动 D12 部署工程。

## 已实现页面

| 路由 | 基础功能与权限 |
|---|---|
| `/agents`、`/agents/:ref` | 管理员创建版本草稿，配置角色、固定指令策略、模型、工具/Skills、实验/设备范围及预算；发布前校验、不可变版本差异、发布与禁用；有实验权限时创建受控测试运行、逐步推进/取消、查看轨迹 |
| `/models` | 管理员维护供应商连接与模型版本、能力声明、上下文/输出/超时/尝试限制；版本修订、禁用及显式合成文本测试；默认模型由 Agent 版本绑定 |
| `/skills`、`/skills/:ref` | 管理员导入 instruction/execution 草稿，编辑依赖、权限、Schema、前置条件和成功判据；校验、发布、禁用及版本比较；绑定通过 Agent 配置完成 |
| `/mcp` | 管理员配置固定地址 Streamable HTTP 连接；连接测试与工具发现；独立人工只读授权/撤销、禁用；展示当前 Schema hash 和过期标记 |
| `/knowledge` | 按授权实验和 Agent 作用域查看文档/记忆版本，导入、文本检索、核对来源/hash；来源所有者共享、撤销或停用 |
| `/dashboard`、`/usage` | 实验状态摘要与当前用户调用用量；按模型、Agent、UTC 日期筛选，区分逻辑请求/已记录尝试/未决请求；分组关联原始 Agent Run，下钻到轨迹 |
| `/traces/:experiment/:run` | LLM、工具/MCP、仪器命令标签；原始持久轨迹及命令台账状态，当前用户和资源范围由服务端复核 |
| `/audit` | 管理员查看持久操作审计、分页及当前页筛选 |
| `/settings` | 管理员查看注册身份、角色、禁用与撤销令牌；带原角色比较的角色变更；凭据创建/轮换/禁用；展示实际系统和历史保留策略 |

导航按角色显示，直接访问仍执行服务端鉴权。管理变更复用持久幂等键；配置/凭据版本冲突要求刷新，不自动覆盖。未知请求不自动重新生成键。危险操作提供对象和影响说明、显式确认及键盘操作。离线时禁写；401 退出会话，403 清除控制台内容；窗口获得焦点及每 15 秒重新检查平台身份。来源/实验权限在每次服务端操作时核验，不声称浏览器缓存即时收到所有外部授权变化。

## 后端与契约增量

在 `contracts/openapi.base.yaml` 增加 9 个操作，共 73 个契约操作，再生成 OpenAPI 和 TypeScript 共享类型。无新数据库迁移。版本详情不返回 canonical_bytes 或发布内部包；发布前校验复用发布规则，但不发布、运行模型或写设备。角色变更锁定身份、比较原角色并同事务保存审计，禁止自改角色及修改服务主体角色；平台角色变更不替代实验成员/设备授权。

模型连接测试必须由管理员显式触发：固定 `Reply OK.`，最多 32 输出 Token、一次尝试、最长 15 秒，不发送实验内容或业务工具。返回原始用量是否存在、耗时及文本测试结果，不自动将工具/视觉能力标为已测试。请求结果保存在现有幂等账本；重复同键不再调用供应商。本期测试只使用离线模型，没有使用真实凭据或付费调用。

用量分组新增 `agent_run_ids`，UI 可以核对其持久 trace。未知 Token/费用仍显示未知；不把完成数当作全部尝试，不假造价格、延迟或失败率。当前统计限定为用户/实验范围，模型连接合成测试由管理请求账本记录，不混入实验用量。

## 本机运行与验收

已同步 D05–D10 的远程基线 `93ab50f`；当前有效工作树为 macOS `/Users/endsen/codex/ALAP`。Linux `/home/endsen/ALAP` 是另一环境的历史路径。Python 3.14.8 与 requirements-dev.lock；Node 24.22.0 与 apps/web/package-lock.json。启动方法继续使用 D09/D10 说明。

```bash
# 使用已安装的 Node 24；不要使用本机默认 Node 26
export PATH=/opt/homebrew/opt/node@24/bin:$PATH
# 隔离 PostgreSQL：仅回环 55432，数据库 alap_test
/opt/homebrew/opt/postgresql@18/bin/pg_ctl -D /private/tmp/alap-d03-postgres \
  -l /private/tmp/alap-d03-postgres.log -o '-p 55432 -h 127.0.0.1 -k /private/tmp' start
# 独立终端启动，仅供测试
nats-server -js -a 127.0.0.1 -p 54222 -sd /private/tmp/alap-d11-nats
export ALAP_TEST_DATABASE_URL=postgresql://endsen@127.0.0.1:55432/alap_test
export ALAP_TEST_NATS_URL=nats://127.0.0.1:54222
export NO_PROXY=127.0.0.1,localhost
.venv/bin/python scripts/check.py
ALAP_SCREENSHOT_PREFIX=d11-regression .venv/bin/python scripts/check_web.py
```

临时数据库目录不存在时按 D03 文档重建。Chromium 由锁定的 Playwright 安装，本期不使用跨版本浏览器替代。浏览器 fixture 使用真实 PostgreSQL/FastAPI、回环 HTTP MCP、离线模型、独立模拟网关/HDF5；fixture 模型 profile 按所选版本装配，保持实际运行时的版本一致性门禁。API 的回环 HTTP 测试显式忽略系统代理，避免请求被转发给外部代理。退出后清理测试 schema 和临时身份文件，不保留常驻产品服务。

## 明确边界

- 指令策略仍固定为 `alap-policy@1`；可编辑的操作知识通过 instruction Skills 版本维护，不宣称已支持任意系统 Prompt 注册表。
- Skills 校验不执行代码；执行技能的模拟验证必须走已授权计划与实验工作区，不提供绕过审批的“直接运行”按钮。Agent 测试只生成提案。
- 配置按不可变版本修订；被禁用版本不原地重新开启。列表采用后端游标或明确数量上限；当前页搜索不冒充全库搜索。
- 系统设置显示实际“不自动删除历史”策略，不提供没有清理器支持的保留天数编辑。企业 SSO、完整计费、自动保留清理、跨浏览器、常驻进程/部署和备份恢复验收留到后续工程。
- MCP 为已实现的 HTTP 子集，无 stdio/OAuth 管理；知识为文本检索，无虚构索引进度。仪器标签显示台账而非实时遥测或敏感通信原文。
- 本期仍不构成真机或无人值守批准。D12 未开始，D13 现场门禁不变。

## 本期验收结果

- `reports/d11-validation.txt`：439 项后端测试及全部统一检查通过。
- `reports/d11-web-validation.txt`：10 项前端单元、18 项浏览器用例、类型/格式/生成一致性及生产构建通过。
- `reports/d11-mobile-validation.txt`：移动导航修正后的生产构建及专项浏览器复验通过。
- 已人工检查桌面模型页与移动设置页截图，导航无文字挤压、页面无横向溢出；完整截图见 `reports/d11-*.png`。
- D11 实现提交 `483f23d` 已推送到 GitHub `main`；远程 CI：https://github.com/endsen/ALAP/actions/runs/39265691351 （实现提交后端及 Web 门禁均已通过）。临时测试服务收尾停止，D12 未启动。
