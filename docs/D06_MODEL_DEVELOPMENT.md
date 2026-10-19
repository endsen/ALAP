# D06 · 多供应商模型接入开发交接

日期：2026-10-18。基于 D05 本地代码，不含远程提交或 CI 验收。

## 交付边界

- `application/models.py`：ModelClient/SecretStore 端口、冻结的 ProviderConnection/ModelProfile、能力状态、请求预算和统一事件。连接与模型版本显式绑定，调用记录带配置版本；没有默认供应商切换。
- `adapters/llm/chat.py`：OpenAI/DeepSeek 的 `chat-completions-v1` 适配，分别发送 `max_completion_tokens` / `max_tokens`，统一 SSE、文本、工具参数、实际模型、usage 和终态。仅支持单候选文本消息。
- 工具参数分片不可执行；只有完整 `[DONE]`、正常 finish_reason、唯一调用 ID、已提供工具名称和 JSON Schema 全部校验后，finish 才包含 tool_proposals。Adapter 不执行任何工具；Agent/授权与确定性执行仍分层。
- JSON 输出采用显式 `json_object_mode` 加本地 Schema 验证，不声称供应商严格 Schema 模式。工具和 JSON 约束同时使用、视觉或工具结果历史消息当前显式拒绝；D07 扩展多轮工具历史时必须维护配对与授权检查。
- 429/408/部分 5xx/连接故障可在尚未输出内容时有界重试。每次独立 ID、耗时、请求 ID、用量；已输出的尝试失败不会重试拼接。未知 usage 为 unknown，不计作零。
- 总请求时限、每次时限、最多三次尝试、保守输入字节/输出 token 预留、响应字节上限；失败尝试仍占预算。同步流提供 Event 取消和 socket watchdog。DNS/TLS 建连受 socket timeout 约束；不保证 OS DNS 阻塞可即时取消。
- 当前预算单位为 tokens，不是货币。价格仅版本引用，账单/价格目录及持久用量聚合留待相应服务期，禁止据此宣称精确费用。

## 凭据与网络

开发密钥由 `EnvironmentSecrets` 读取 `env:变量名`，配置没有明文字段，repr 隐藏引用。真实冒烟使用 getpass 无回显，仅进程内存保存凭据。错误响应体和异常对象不进入公开事件或报告；请求 ID 仅保留有限安全字符。

标准库 HTTPS transport 固定官方域名与允许路径，不使用环境代理、不跟随重定向、不接受用户提供的其他 host/端口/凭据/query。OpenAI `/v1`，DeepSeek 根路径或 `/v1`。自定义/本地模型、Anthropic/Gemini、Responses 协议尚未实现；需要独立协议及管理员出站策略，不能通过改 URL 冒充支持。

配置是内部 Python 不可变值对象，尚无数据库配置注册表、管理 API、前端连接状态、集中 Secret Store 或生产 egress firewall。能力的 declared/tested 是配置声明，本模块不把一次请求成功自动升级成完整模型能力认证。SDK 没有新增；使用锁定 Python 3.14 标准库 HTTPS 与现有 jsonschema。

## 验证与复现

```bash
.venv/bin/python -m pytest tests/test_models.py -q
# 明确选择真实调用才执行；交互输入凭据，无回显。固定合成文本、最多三次生成请求。
.venv/bin/python scripts/smoke_llm.py
# 启动 D05 文档中的隔离 PostgreSQL/JetStream 并设置环境变量后执行
.venv/bin/python scripts/check.py
```

离线覆盖 EVAL-16/17/18 的协议层：两个供应商同一 Planner 输入、工具参数分片/非法 JSON/重复键/重复 ID/未知工具/Schema 错误、截断、缺失或非法 usage、认证/限流/连接错误、重试预算、取消、阻塞读取中断、上下文预算、响应大小、能力/凭据/版本缺失、外部 Schema 引用和地址拒绝、敏感错误脱敏。

真实 DeepSeek 冒烟：读取模型目录后选中 `deepseek-flash`，三项成功；文本 56、JSON 112、工具 363，总计 531 tokens（供应商报告），不推断货币费用。见 `reports/d06-deepseek-smoke.json`。没有保存 Prompt/响应全文或密钥；未做真实 OpenAI 调用。

全套门禁通过：303 项测试（原 243 项 + 本期 60 项）、Ruff/格式、生成漂移、契约/OpenAPI 和依赖检查。结果见 `reports/d06-validation.txt`。未涉及真实仪器、Web、Agent Runtime 或生产长时间故障测试。

## 官方协议依据

本期实现前核对以下官方页面；模型名单从服务端发现，不从企划硬编码生产默认模型。

- [OpenAI Chat API](https://developers.openai.com/api/reference/resources/chat)
- [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)
- [DeepSeek Models](https://api-docs.deepseek.com/api/list-models/)

## 下一期

D07 专用 Agent 与 Skills：先定义版本化角色/授权工具与技能集、多轮历史和 checkpoint 边界，再接入 ModelClient。补齐配对的 assistant/tool 历史消息，严格区分工具提案与实验计划提交；上下文裁剪和记忆不得删除审批/安全证据。按第 05/20 章验收，不直接推进 Web 或真机执行。
