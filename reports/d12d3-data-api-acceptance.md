# D12d.3 部署数据 API 完整性验收

日期：2026-10-22；第五批本地部署验证，关联 FR-011/018、NFR-008 与 EVAL-10。D12d.3 仍进行中，未进入长测或现场。

新增 `check_data_fault.py`，使用八个真实 Compose 服务及正式 HTTP API，以测试管理员身份请求/批准模拟计划，常驻 Engine/Gateway 完成三个任务并产生一份 COMMITTED HDF5。正常基线同时读取清单、原始下载和曲线。

仅对新实验所属文件进行两种故障：将原文件移至同卷备份形成缺失，再恢复；第二次备份原文件后写入损坏字节，再恢复。每次操作都检查 dataset/experiment 归属、生成存储 key 和原始 checksum。两种故障下三个接口均返回 **422 ARTIFACT_INVALID**，清单与命令数据库投影不改变。每次恢复后的下载 SHA-256、清单与曲线都与正常结果一致。

证据 `reports/d12d3-data-api-evidence.json`：两种故障、六次拒绝断言通过；全局命令 36→39，只增加正常采集的三条，故障增量 0、活动执行 Run 为 0。finally 恢复新文件、撤销测试令牌，保留审计和正常采集数据；没有修改历史实验文件。若硬杀宿主进程，须检查 `.fault-backup` 并按 checksum 恢复，不能假定 finally 执行。

没有改变产品业务逻辑、公共 API/契约、依赖或迁移；未调用模型或真机。完整后端门禁 **576 项通过（445.92 秒）**，真实 PostgreSQL/NATS 集成未跳过；格式、契约/OpenAPI、生成文档和依赖一致性通过，见 `reports/d12d3-data-api-backend-validation.txt`。Web 产品未改，未重跑浏览器；API 曲线拒绝不等于已验证页面缓存/按钮禁用。

读取失败不会在本次演练中自动将数据状态改成 CORRUPT；请求时 fail-closed 与后台自动检测分开记录。本场景不覆盖上传途中写盘失败、持续损坏扫描或生产数据修复流程。后续优先补浏览器异常状态、过期/不稳 telemetry、权限组合和边缘失联监护/证书身份映射。未推送 GitHub。

最终八服务运行、控制模式 ACTIVE，仅 Web 发布 127.0.0.1:3000；首页 200、匿名 API 401。测试库/角色、有效 token、活动执行/Agent 运行及待发布 outbox 均为 0，命令总数 39。已重新从 API 容器只读校验测试文件 SHA-256，临时 `.fault-backup` 不存在；QA 端口关闭，未注册系统服务。见 `reports/d12d3-data-api-final-runtime.json`。
