# D12d.3 独立进程异常读回验收

日期：2026-10-22；第七批本地验证。关联 FR-003/008/009、NFR-002 与 EVAL-11/15 的前置条件/读回规则；D12d.3 尚未完成。

新增 `tests/integration/test_telemetry_process_faults.py`，专项 **3 项通过（34.58 秒）**。真实 PostgreSQL、独立 Engine 与 Gateway，经 loopback HTTP 代理转发；只改 telemetry 观测值，用隔离测试密钥重签，保留条件/身份/RPC 绑定。不是认证攻击验收，不放宽产品认证，也不修改系统时钟或模拟器执行回执。

| 故障 | 观察与禁止副作用 |
|---|---|
| 时间戳整体减 60 秒 | READBACK_STALE，只有温度命令，磁场/采集均未派发 |
| 容差内的样本跳变导致斜率超限 | READBACK_UNSTABLE，只有温度命令，磁场/采集均未派发 |
| 零磁场目标但读数超出容差 | READBACK_INVALID，温度/磁场已完成，采集未派发 |

每项至少观察三次异常响应，无 Dataset，已执行动作各一次。恢复正常观测后，常驻 Engine 重新检查前置条件并继续执行，最终恰好三条成功命令、每条动作一次、一份 COMMITTED Dataset，资源释放。没有手工 advance、重发已执行命令、UNKNOWN 或自动 resume 的替代断言。测试退出前停止 Engine，再关闭代理，fixture 清理 Gateway/测试库。

该证据为 P 级：代理在测试进程内，Engine/Gateway 为独立进程；没有 Compose mTLS、真实仪器或样品磁通证据。产品代码、契约、依赖、Web 均未改变，未重复上一批完整浏览器测试。

完整后端门禁 **579 项通过（503.63 秒）**，使用真实 PostgreSQL/NATS，集成测试未跳过；Ruff/格式、生命周期参考、合订本、OpenAPI、13 项 Schema/示例与完整 OpenAPI 契约及依赖检查通过。见 `reports/d12d3-telemetry-backend-validation.txt`。

最终八服务恢复运行、控制模式 ACTIVE，仅 Web 发布 127.0.0.1:3000；首页 200、匿名 API 401。测试数据库/角色、有效 token、启用测试配置、活动运行与待发布事件均为 0；部署命令保持 45，全部 15 份 COMMITTED 数据文件校验通过，无临时故障备份。QA 端口与隔离模型网络已移除，未注册系统服务。见 `reports/d12d3-telemetry-final-runtime.json`。

下一步继续活动上传失败、剩余权限/模型/知识注入组合以及边缘失联监护、证书身份与资源映射实现缺口；不启动长测或现场，不推送 GitHub。
