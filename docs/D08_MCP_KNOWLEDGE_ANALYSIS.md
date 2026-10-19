# D08 · MCP、知识与分析协作开发交接

本期延续 D05–D07 本地代码，未上传 GitHub。提供内部应用接口与协议/集成验证，不表示已有 Web、生产认证或真机控制服务。

## 交付内容

- `application/resource_ports.py`：MCPTransport、DatasetReader、ResourceStore 端口。
- `adapters/mcp/http.py`：明确支持 MCP **2025-11-25** Streamable HTTP 的 initialize/initialized、会话头、tools/list 分页、tools/call，接收 JSON 与 POST SSE 响应。版本不匹配显式失败，没有自动协议降级。
- `application/agent_resources.py` / `adapters/postgres/resources.py`：MCP 连接注册、发现、人工审核的只读授权、来源版本/ACL、检索、确定性 IV 分析及权限复核。
- `application/collaboration.py`：基于权威 dataset.committed 事件的 Analysis/Planner 唤醒、证据引用、去重、冷却与次数预算。
- Agent Runtime 新增 Analysis 角色、scoped_knowledge、search_knowledge/analyze_dataset 与已授权 MCP 读取工具。原有 Planner/Instrument 行为继续验收。
- 迁移 d08_001 增加知识/ACL、MCP 连接/目录/授权/调用 ledger、分析结果、协作 claim 与提案业务指纹；新增 knowledge_source/analysis_summary 共享 Schema，OpenAPI 从源生成。

## MCP 授权与网络边界

发现和初始化不会执行业务工具，也不授予任何工具权限。远端 readOnlyHint/描述都是不可信声明；只有可信内部管理员通过 approve_read_tool 明确审核的工具才生成可发布的本地工具版本。首版只允许只读工具，拒绝物理写/任意 shell 的直接接入路径。

工具输入必须接受 experiment_id/instrument_ids，实际值由服务从当前运行作用域注入；模型不能指定这两个字段。远端仍须可信地执行该范围约定，不能仅凭协议注解证明服务器实现无副作用。结果必须带 structuredContent 并通过审核时的输出 Schema，不消费远端 sampling/elicitation 请求。Schema 或描述变化导致旧签名失效和授权撤销，不自动重新授权。

地址来自可信管理员配置，固定 URL 与 numeric IP。请求直接连接审核后的 IP，HTTPS 仍校验原 hostname 证书；不跟随重定向、不使用环境代理、不在执行时重解析 DNS。默认拒绝私网/链路本地/回环，仅显式允许的无凭据回环 HTTP 用于测试；真实远端要求 TLS。凭据仅使用 SecretStore 引用，若响应回显凭据即拒绝。

每次调用前重新发现并验证签名/授权。远端调用前持久化 INFLIGHT；成功缓存供本地 checkpoint 恢复复用，不重复远端调用；失败或中断为 UNKNOWN/INFLIGHT，不能自动重放。结果和输入由大小/Schema/超时限制，错误正文不进入模型；原始验证异常不向模型暴露。

限制：没有 stdio worker、旧 HTTP+SSE、2026 新协议、OAuth 交互登录、服务端主动请求、GET 流重连或 session DELETE 清理；连接不长期复用，支持有 session 的握手/后续请求，但服务端 session 回收依赖其过期策略。未联调任何公网 MCP 服务或仪器。地址更新需新连接版本及重新审核。

## 知识、记忆与撤权

导入的是限长文本、来源 URI、版本、资源范围和内容 hash；不抓取 URL、不执行文档命令。document 可按实验共享，memory 必须额外绑定具体 Agent 版本；两者均为资料，不是授权事实。默认只有创建者可读，分享/撤权由来源拥有者在当前实验写权限下执行。

检索为有界文本子串匹配，最多返回五条 1500 字符摘录及完整来源引用；没有向量模型、自动总结或跨实验记忆合并。每次搜索、读取、Agent checkpoint 加载、模型续跑和结果提交检查当前实验成员、仪器范围、来源 ACL/启停、Agent scope。被撤权的旧 history/已完成结果不能借 checkpoint 绕过授权。语义搜索与复杂文档切片可后续扩展，不把此版称为完整 RAG。

## Analysis 与有证据再规划

只读取 COMMITTED 数据，通过 D05 DatasetService 校验实际文件 checksum，并检查实验/仪器范围。首个算法 `iv-linear-summary@1` 对有界有限 IV 数组计算线性电阻、偏置和残差 RMS，保留 dataset_id、checksum、样本数及算法版本。它是描述性拟合，不能当作临界电流 Ic、磁通或设备新鲜读回的判据。

同一数据/checksum/算法结果唯一，持久化不可覆盖。生成的上下文包含权威来源引用；数据转 CORRUPT 或权限撤销后，旧分析不能继续作为可访问上下文/提案证据。未注入或未分析过的数据 ID 仍被拒绝。

AnalysisCoordinator 只接受 PostgreSQL outbox 中的 dataset.committed.v1 事件；重复事件/相同证据复用同一 Run，创建 Run 与绑定 claim 之间崩溃后可按固定 ID 恢复。新证据有次数和冷却预算，失败不退还名额。此为内部唤醒用例，尚未部署常驻订阅 worker。

提案按实验和结构内容建立业务指纹，忽略 proposal_id/source_agent_run_id/reason；同快照、任务/资源/风险/证据内容重复会原子阻断，不能靠更换 Run 或措辞重复提交。任务 ID/DAG/参数仍属于结构内容；不是自然语言或近似计划的语义去重。新提案始终为 PROPOSED，不创建审批、正式计划或硬件命令。

## 验证与复现

```bash
# 按 D05 文档启动隔离 PostgreSQL/JetStream，设置测试 URL
.venv/bin/python -m pytest tests/integration/test_resources.py tests/test_mcp_policy.py -q
.venv/bin/python scripts/check.py
```

本期测试使用真实 PostgreSQL、实际回环 HTTP MCP 服务、LangGraph、D05 生成的真实 HDF5，以及离线 LLM 替身。覆盖发现不授权、JSON/SSE、错误/版本/大小限制、地址策略、凭据回显、Schema 变化、作用域注入拦截、缓存恢复/未知不重放、知识隔离/撤权、内存作用域、数据腐坏、分析与提案血缘、事件/业务去重和协作预算。全套门禁通过：393 项测试（112.22 秒），其中本期新增 45 项；Ruff/格式、生成一致性、13 份 Schema/实例、OpenAPI 和 pip check 均通过。报告见 reports/d08-validation.txt。

没有新增第三方包；NumPy 已在既有锁文件中，本期将其显式列为直接依赖。未调用付费 LLM、公网 MCP 或真机。生产管理身份与 API、持续服务、OAuth/证书运维、科学算法现场标定分别属于后续工作，不能用本期替代验收。

## 官方协议依据与下一期

协议按 [MCP 2025-11-25 Transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) 和 [Tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) 实现明确子集，未声称支持所有协议版本和可选能力。

下一期 D09：FastAPI、身份/RBAC/ABAC、管理接口与读模型、SSE、统计与凭据接口。优先统一鉴权/版本冲突/错误脱敏边界，再暴露已有内部用例。
