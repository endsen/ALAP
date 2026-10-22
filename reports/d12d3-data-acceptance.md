# D12d.3 独立进程数据故障验收

日期：2026-10-22。第四批本地验证，关联 FR-011、NFR-002/008 与 EVAL-10；D12d.3 整体未完成。

新增 `tests/integration/test_data_process_faults.py` 两种参数化场景，专项 **2 项通过（29.28 秒）**，报告 `reports/d12d3-data-process.txt`。独立 Engine 和 Gateway 使用真实 HTTP、PostgreSQL、HDF5 与持久模拟器 SQLite。故障只作用于 pytest 临时目录，不改正常部署的数据卷。

实际把临时存储目录替换为普通文件：Engine 报 STORAGE_UNAVAILABLE；数据保持 STAGING、manifest=null，采集命令 VERIFYING、无 provenance，读取返回 DATASET_NOT_COMMITTED。多轮调度不增加命令和模拟动作。恢复目录后常驻进程完成数据提交，恰好一份 HDF5、一条来源边和一条 committed 事件，Run SUCCEEDED，资源释放。

停稳 Engine 后分别移除或损坏已提交文件，真实 DatasetService 读取返回 ARTIFACT_INVALID，不重建文件、不修改历史 manifest。finally 恢复原始字节后读取校验通过；重启 Engine 并观测多轮，仍只有三条命令，每条模拟动作一次，Run 保持 SUCCEEDED。

读取校验在测试进程内调用，不能称为 C 级 HTTP/浏览器 Analysis 验收。存储路径不可用不等于实际磁盘满或半文件写入；未测试永久介质故障，未调用 verify_integrity 将状态转换为 CORRUPT，因此原始字节恢复不是生产 CORRUPT 恢复方案。没有真机/在线模型、业务代码/依赖/迁移/公共契约变更。Web 未修改，不重复浏览器门禁。

完整后端门禁 **576 项通过（448.39 秒）**，真实 PostgreSQL/NATS 集成未跳过，Ruff/格式、契约/OpenAPI、状态机与合订本生成、依赖一致性检查通过，见 `reports/d12d3-data-backend-validation.txt`。剩余：活动部署数据异常的 API/Analysis 组合、过期/不稳 telemetry、权限矩阵与边缘失联监护/证书身份映射。未推送 GitHub，未进入 D12d.4/D13。

最终八服务运行、控制模式 ACTIVE，仅 Web 发布 127.0.0.1:3000；首页 200、匿名 API 401。测试数据库/角色、有效令牌、活动执行/Agent 运行及待发布 outbox 均为 0，命令总数保持 36；QA 端口已关闭，未注册系统服务。证据 `reports/d12d3-data-final-runtime.json`。
