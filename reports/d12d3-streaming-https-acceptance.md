# D12d.3 非法用量与 HTTPS 流停滞

2026-10-24，第十三批；关联 EVAL-17/21。D12d.3 尚未完成。

扩展本地隔离 HTTPS/SSE 替身，OpenAI/DeepSeek 两格式各验证负数用量、布尔值用量、prompt+completion 与 total 不一致，以及不完整工具调用分片后连接保持六秒。专用模型 profile 设置 timeout_seconds=2、max_attempts=1；使用真实模型客户端、部署 API 与独立常驻 Agent worker，没有手动 advance，没有调用线上模型。沿用已有产品镜像，替身挂载与维护 fixture 输入使用当前源码。

八项部署验证通过，每项最终 FAILED/done、MODEL_FAILURE，iterations=1、预算预留保留、HTTPS 请求次数为 1；超时场景服务端确认已发送部分 SSE。无 model_completed、无 Agent 工具提交/提案，计划/审批/Run/Task/Command/Dataset 写入全部为 0。未知成功用量计数为 0，不意味着失败请求没有实际供应商费用。见 `d12d3-streaming-https-evidence.json` 与 `d12d3-streaming-https-run.txt`。

新增替身用量变异测试验证原数据不被修改且工具分片不变；首轮测试未解包 fault_chunks 的 (chunks, done) 返回值，修正测试后，替身及模型专项 81 项通过。没有修改产品权限或错误处理以迁就测试。完整后端 **604 项通过（541.73 秒）**，真实 PostgreSQL/NATS 集成未跳过；Ruff/格式、生命周期参考、合订本、OpenAPI/契约和依赖一致性全部通过，见 `d12d3-streaming-https-backend-validation.txt`。

本批没有产品代码、Web、公共契约、依赖或迁移变化，不重复上一批浏览器验收。取消、多次重试、其他权限组合仍待后续矩阵；不启动 D12d.4 长测或 D13，未推送 GitHub。

常规部署恢复后八服务运行、控制模式 ACTIVE，首页 200/匿名 API 401。测试库/角色、有效 token、启用测试配置、活动运行、待发布事件均为 0；设备命令保持 45，原有 15 份 COMMITTED 文件 SHA-256 校验通过，QA 端口及隔离模型网络已移除，见 `d12d3-streaming-https-final-runtime.json`。
