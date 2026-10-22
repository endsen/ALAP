# D12d.2 常驻 Agent/API 模型链路验收

日期：2026-10-21。范围：rootless 单机 Compose、模拟仪器、本地 TLS/SSE 供应商替身；没有调用官方模型、没有真实计费或真机操作。

## 实现与实测

- 新增 `check_agent.py`、维护种子与独立 TLS/SSE 替身；官方 HTTPS endpoint 白名单、真实模型传输器和正常 worker 的实验范围保持原配置。测试 worker 无 egress，仅连接两个 internal 网络；证书仅在测试容器信任。
- 两次完整部署验收都经真实 Web → API → PostgreSQL → 独立 Agent worker → HTTPSChatTransport → 替身。最终复验包含跨实验合法请求 403，OpenAI/DeepSeek 分别验证输出上限字段、流式工具片段、read_snapshot 往返、propose_plan 和 usage。
- 最终浏览器 **2 项通过（55.3 秒）**。浏览器 `/advance` 调用数为 0；两轮调用的每轮返回合成用量 100 input / 50 output / 150 total，不能解释为实际供应商计费。每 Run 保守预留 128000 token，两次模型调用、两次工具调用，固定模型/工具/Skill/实验范围。
- 两个最终实验各产生一条结构化提案，提案完成前审批/Run/Task/Command 转换审计为 0。人工身份通过 UI 转草案、校验、请求审批、批准、启动执行；每个实验 1 SUCCEEDED Run、3 SUCCEEDED Task/Command、1 COMMITTED Dataset、outbox 待发布 0。HDF5 签名及 SHA-256 在浏览器匹配。具体实验与镜像见 `d12d2-compose-evidence.json`。
- 修复现有 Web 会话不读取常驻 worker 终态的问题：运行中每两秒触发读取，终态刷新提案/轨迹，错误停轮询，卸载清定时器，人工推进时暂停轮询。真实部署测试依赖这一行为完成，不用手动推进掩盖后台更新问题。
- 原确定性部署链、观察者限制、SSE 中断恢复回归 **3 项通过（24.6 秒）**，见 `d12d2-compose-browser-regression.txt` 与 `d12d2-browser-regression-evidence.json`。旧 D12d.1 报告保留不覆盖。
- 协议替身专项 7 项通过；完整后端 **572 项通过（430.63 秒）**，真实 PostgreSQL/NATS 集成不跳过；完整 Web 类型/格式/契约类型/构建、10 项单元测试及 **18 项 fixture 浏览器测试（1.2 分钟）**通过。后者不替代本轮跨容器验收，截图 `d12d2-*.png` 为 fixture 回归证据。结果见对应 validation 报告。

## 调试与清理

首轮种子创建后私有状态文件再次独占写入失败；已分开种子与浏览器状态文件，并让网络清理容忍尚未创建的网络。未执行设备动作，临时 token、Agent/模型配置和测试凭据已禁用。首次成功运行后加强跨实验拒绝和审计断言并完整复验；所有实际执行均成功，未重放旧 Run。

临时两个容器、网络、CA/key 和浏览器令牌文件由 finally 回收；数据库保留实验、不可变提案/轨迹、数据与已禁用配置。版本化 Skill 为可复验 fixture 记录，不赋予设备写权限。强制杀死宿主程序不保证 finally，文档要求续接检查残留。最终八服务运行、控制模式 ACTIVE；仅 127.0.0.1:3000 发布，首页 200、匿名 API 401。测试数据库/角色、有效测试凭据/配置/Agent、有效 token 和未完成测试 AgentRun 均为 0，QA 端口与测试网络已移除，见 `d12d2-final-runtime.json`。未新增依赖，未推送 GitHub。

## 未覆盖

本地替身按示例任务构造响应，验证协议与平台执行边界，不证明 LLM 推理能力、官方在线兼容性或实际 token 统计。预算耗尽等异常仍依赖既有单元/数据库集成证据，未提升为本轮跨进程故障验收。D12d.3 完整故障矩阵、D12d.4 实际 24 小时负载、D13 现场均未完成。
