# D12d.3 模型故障与 Skill 撤销验收

日期：2026-10-21。D12d.3 第二批本地部署验证；整期仍进行中，不启动 D12d.4/D13。关联 FR-014/020–023/026/027、EVAL-03/17/18/19/21；完整需求映射与边界以 `docs/D12D_FAULT_MATRIX.md` 为准。

## 实现及故障证据

新增 `check_model_faults.py` / `model_faults.py`，复用 `check_agent.py` 的隔离 TLS/SSE 供应商、真实模型适配器和独立常驻 worker。扩展 provider 的响应故障、请求计数、响应屏障；每个撤权场景使用独立 Skill，避免影响其他测试。没有更改领域、应用、业务适配器、公共 API、迁移或依赖。

`reports/d12d3-model-faults.json`：OpenAI/DeepSeek 两种格式各六项，共 **12 项通过**。

| 场景 | 观测结果 |
|---|---|
| 返回 execute_device 越权工具 | FAILED，1 次 HTTPS 请求 |
| SSE 截断且无 DONE | FAILED，1 次 HTTPS 请求 |
| HTTP 429 | FAILED，1 次 HTTPS 请求；fixture max_attempts=1 |
| 缺失 usage | COMPLETED，两次响应 usage=null，API 未知用量次数 2，仅生成未审批提案 |
| 调用前禁用测试凭据 | FAILED，0 次 HTTPS 请求 |
| 第二次响应发出前禁用 Skill | FAILED，两次 HTTPS 请求，最终 blocked / SKILL_DISABLED |

数据库独立核对：12 个实验的计划、审批、执行 Run、Task、Command、Dataset 写入均为 **0**，仅两份未审批提案。请求计数只记录实验 ID 和模式，不记录请求正文或凭据。原有生产官方 HTTPS 白名单不变；临时 CA/DNS 只用于两个 internal 网络上的测试 worker，无外部模型网络调用。

首次演练在撤销 Skill 时，测试入口误传 `{}` 给无请求体接口，产品正确返回 422。修正为无 body 的 POST 后重跑全部 12 项通过，没有放宽接口契约。增加 finally 的应用层取消：停止隔离 worker 后，将本次未终结 AgentRun 经正常取消用例结束，再禁用测试配置/凭据/Agent/专属 Skill、撤销令牌并移除空测试网络；保留审计，不直接改 checkpoint。首次遗留检查未发现旧的活动 AgentRun。

## 回归与交接

- 默认正常入口回归 **2 项通过（54.2 秒）**，浏览器完成提案、人工审批、三任务模拟执行、HDF5 下载和校验。见 `d12d3-model-normal-agent.txt`、`d12d3-model-normal-evidence.json`；原 D12d.2 历史报告已保留。
- 完整后端门禁 **574 项通过（429.64 秒）**，真实 PostgreSQL/NATS 集成未跳过；Ruff/格式、契约/OpenAPI、状态机/合订本生成漂移和依赖一致性通过，见 `d12d3-model-backend-validation.txt`。
- 恢复八服务运行、控制模式 ACTIVE，仅 Web 发布 127.0.0.1:3000；首页 200、匿名 API 401，QA 端口和隔离模型网络已移除。临时测试库/角色、有效令牌、启用的测试模型/凭据/Agent/专属 Skill、活动 AgentRun/执行 Run、待发布 outbox 均为 0。命令总数 30→36，仅正常浏览器回归增加六条；见 `d12d3-model-final-runtime.json`。没有注册系统服务。
- `manage up` 返回后立即检查时匿名 API 曾返回 500；服务启动完成后重新只读检查为 401。当前启动命令返回不等于应用就绪，后续调用方仍应检查就绪状态；本轮最终报告记录复验结果，不掩盖初次瞬态失败。
- Web 产品代码未改，不重复完整 fixture 浏览器门禁；上面的真实部署两项覆盖共享测试入口回归。

目标中含绕过审批指令、模型返回越权工具，证明实际 HTTPS 输出不能扩张工具权限；**没有注入检索文献**，不作为 EVAL-03 整项通过。超时/取消/非法 usage、能力/版本漂移、知识/MCP 运行期撤权等部署组合仍待补。后续优先批准后计划变更、活动数据失败、过期/不稳回读，并处理边缘失联监护和证书身份映射缺口。没有真实供应商或现场仪器验收，不把短测计为长测。当前 D12d.2/3 本地新增内容尚未推送 GitHub。
