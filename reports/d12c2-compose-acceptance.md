# D12c.2 真实容器部署验收（2026-10-20）

结论：**本地 rootless 单机模拟部署通过；D12c.2 完成。本结论不等价于生产、完整平台 E2E、备份恢复、24 小时负载或现场验收。**

## 实际实现与运行

- 显式 prepare/build/initialize/up/token/verify/stop；初始化不隐式嵌入应用启动，不自动覆盖凭据/角色/已有目录。新库、迁移、四组件角色由维护任务创建，业务容器不挂载管理员/迁移凭据。
- 真实构建后端镜像与 Next.js 生产镜像，八服务实际运行：PostgreSQL、JetStream、模拟 Gateway、Engine、Agent、outbox、API、Web。初始化只创建模拟设备登记、管理员和空实验，命令账本为 0，没有 LLM 凭据、审批或执行 Run。
- Docker 29.9.1 / Compose 5.6.0 / rootlesskit 3.3.0 / slirp4netns 1.3.6；容器内 Python 3.14.8、Node 24.22.0、PostgreSQL 18.6、NATS 2.15.1。主机 Python 3.14.7 用于测试。
- 内核重启修复模块缺失；daemon 显式使用用户提供的可达代理，官方 registry 返回 401 符合预期。CloudFront 镜像层 TLS/EOF 仍失败，按用户授权使用 DaoCloud；四个镜像摘要均与官方 registry HEAD 查询一致，锁定见 `deploy/simulation/images.env`。
- 最终镜像 ID 保存 `d12c2-image-builds.json`，已核对运行容器使用这些镜像；镜像 ENV 中没有构建代理。无全局 Docker 配置修改，无系统开机服务注册。

## 验证结果

| 检查 | 实际结果 |
|---|---|
| 后端统一质量门禁 | **547 passed in 447.69s**，真实容器 PostgreSQL/JetStream 的 TLS/认证连接；Ruff、格式、状态/契约/OpenAPI/文档生成一致性、pip check 通过 |
| 前端镜像 | `npm ci` 与生产构建成功；首页 HTTP 200 |
| 同源 API 与认证 | Web 代理匿名 `/api/v1/me` 返回 401；私有短期 token 请求返回 200 |
| 数据库传输/认证 | 业务连接 `pg_stat_ssl.ssl=true`；错误密码拒绝；`sslmode=disable` 拒绝 |
| Gateway mTLS | API 客户端证书获得有效签名 challenge；缺少客户端证书拒绝 |
| 组件权限 | Agent 插入执行命令、Engine 读取模型凭据、outbox 修改事件 payload 均被 PostgreSQL 拒绝 |
| 数据挂载 | API artifacts 写入失败；Engine 可写的卷哨兵在全部服务停止/恢复后保留，随后清理 |
| 事件发布 | 数据库 published_at 已提交，JetStream 持久流中有事件；重建后继续可核对 |
| 重启 | Gateway/Engine 重启后 Engine 恢复 ACTIVE 且 problems 为空；全部服务停止并按正常配置恢复后复验通过 |
| 令牌续签 | 中断数小时后旧 token 按预期过期；新增本地维护 `manage.py token` 将新 token 原子保存到私有文件，内容不进入终端日志 |
| 清理 | 随机 `alap_test*` 数据库及 `alap_testdeploy_*` 角色计数均为 0；QA 55432/54222 端口关闭，卷哨兵删除 |

统一门禁原始命令输出（已脱敏）见 `d12c2-compose-backend-validation.txt`。三个新增材料测试验证不覆盖已有目录、私有文件与证书用途、组件挂载/设备网络隔离。实际跨容器验收命令为 `deploy/simulation/verify.py`；最终结果：

```json
{"event":"compose_acceptance_passed","checks":["web_authenticated_proxy","api","agent","engine","outbox","outbox"]}
```

首次部署、Gateway/Engine 重启后、完整停止/正常配置恢复后三次均通过。最后一个 outbox 检查是 JetStream 留存核验，前一个是 SQL 越权拒绝。

## 保留状态与边界

本地模拟服务保留运行，只有 Web 发布 `127.0.0.1:3000`。数据库、消息和 Gateway 不对宿主机发布端口。凭据、代理环境、Docker 数据和临时日志在忽略的 `.local-deploy/` 下；不要提交。管理员 token 一小时有效，续签和停止命令见 `deploy/simulation/README.md`。

没有调用付费模型或真实设备，没有推送 GitHub。这里的 Web 验证是实际 HTTP/认证代理接线，不是重新执行浏览器完整交互；数据卷哨兵保留不是 Dataset 一致性恢复证明。中断期间数小时空闲运行也不是 24 小时负载验收。

下一工作项：D12c.3 数据库/数据文件/Gateway journal 一致性备份、隔离恢复、恢复屏障、指标与操作手册；随后 D12d 完整 E2E/故障矩阵/实际长测。D13 未开始。
