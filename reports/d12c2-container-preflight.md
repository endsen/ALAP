# D12c.2 容器前置检查（2026-10-20）

状态：**历史阻塞已处理，D12c.2 实际模拟部署验收通过**。内核重启后使用用户授权代理与 DaoCloud 镜像路径，摘要核对官方 registry。最终证据见 `d12c2-compose-acceptance.md`；下方保留排障历史，不代表当前阻塞。

## 已完成

- Docker 29.9.1 官方静态包下载，gzip/tar 完整性检查通过，隔离解压到被 Git 忽略的 `.local-deploy/bin`，CLI 返回版本 29.9.1（dfc520d）。没有注册开机服务或改动主机 Docker 配置。
- Compose 5.6.0 断点下载最终完成，SHA256 与官方文件一致，CLI 版本检查通过；未运行 Compose 服务。
- rootless extras 使用相同 Docker 版本；主机已有 newuidmap/newgidmap 与 subordinate UID/GID 配置，用户命名空间可用。
- slirp4netns 1.3.6 的 x86_64 文件 SHA256 与官方 SHA256SUMS 一致：`411167abceff1fc8a7c562f53ed9f26d3ec8a17df4e2fe6eaa3bd53f1c1e1d48`。
- 临时 Docker 数据与运行目录均在 `.local-deploy/`；尝试以 rootless 启动，无 root 系统安装。
- 最终后端质量门禁：544 passed in 229.24s，见 `d12c2-validation.txt`。专项 23 项通过，包含真实数据库、HTTP MCP、模拟执行与 HDF5。该门禁未包含容器部署。

## 实际阻塞证据

`uname -r` 返回 `7.1.9-arch1-2`，`/lib/modules` 仅包含 `7.2.9-arch1-1`。

rootless Docker 在创建默认 bridge 时退出：

```text
failed to create NAT chain DOCKER:
iptables: Failed to initialize nft: Protocol not supported
```

另在独立用户/网络命名空间运行只读 legacy NAT 检查，使用专用临时锁文件，未修改主机防火墙：

```text
modprobe: FATAL: Module ip_tables not found in directory /lib/modules/7.1.9-arch1-2
iptables (legacy): can't initialize iptables table `nat': Table does not exist
```

这确认了当前运行内核所需模块缺失；不能将 rootless 用户空间工具安装视为容器网络已可用。没有以关闭防火墙、关闭容器隔离或 host 网络绕过后冒充标准 Compose 验收。

## 恢复后续接

1. 保存其它工作后由主机管理员修复运行内核与已安装模块的一致性。通常需要重启进入已安装内核；此建议仍须核对启动项，未自动重启或改动引导配置。
2. 重新检查 `uname -r`、对应模块目录及隔离网络 NAT，再启动临时 rootless Docker。
3. Compose 5.6.0 已完成下载/校验，可用 `.local-deploy/bin/docker-compose`；重新启动前复核 Docker socket 路径。
4. 继续主体/设备初始化、镜像构建、Compose 网络/持久卷/Secrets 与真实启动验证。Gateway 跨容器使用 mTLS，API/Engine/Agent/outbox 各挂载自身连接文件，迁移凭据只交给维护流程。
5. 通过后才推进 D12c.3 运维恢复、D12d 全链路与实际 24 小时以上模拟；本次不标记 D12c.2 完成。

来源：[Docker 静态安装说明](https://docs.docker.com/engine/install/binaries/)、[rootless 前置要求](https://docs.docker.com/engine/security/rootless/)、[slirp4netns 1.3.6](https://github.com/rootless-containers/slirp4netns/releases/tag/v1.3.6)、[Compose 5.6.0](https://github.com/docker/compose/releases/tag/v5.6.0)。静态安装仅为本机部署验证，后续运维需管理安全更新。

## 重启后复验（2026-10-20）

- 运行内核与模块目录均为 `7.2.9-arch1-1`。rootless Docker 29.9.1 成功初始化默认 bridge、overlayfs 和 BuildKit；安全选项包含 seccomp、rootless、cgroupns。
- 使用本地官方 rootlesskit 静态二进制创建临时探针镜像，在默认 bridge、只读根文件系统、移除 capabilities、no-new-privileges 下实际运行，退出码 0，输出 `rootlesskit version 3.3.0`。这证明容器执行可用，不证明 ALAP 镜像或服务已完成。
- 官方 `hello-world` 镜像连续两次在镜像层下载失败，目标为 `production.cloudfront.docker.com`，错误 EOF；宿主机直接 HTTPS 连接该域同样返回 curl 35（TLS 连接失败）。没有关闭 TLS 验证或引入不明镜像源。
- 下一前置项是恢复官方镜像 CDN 网络访问或配置受信任的网络代理，再完成应用镜像构建及 Compose 验收；不需要再次因旧内核问题重启。
- 重启清除了 `/tmp` 中旧测试服务，现有 544 项通过报告为重启前结果；本次没有声称业务全量复验。
