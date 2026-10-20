# ALAP 项目协作指引

## 当前基线

- 开发以 `docs/01–22` 和生成的 `ALAP_Engineering_Design_v3.1_完整合订本.md` 为准；原始 v3.0 合订本和 ZIP 保留不改。
- 用户明确要求：专用实验 Agent 平台；经 API 接入 LLM，支持主流供应商，首批 OpenAI/DeepSeek；Web 包含独立 Skills、MCP、模型、仪表板、用量、轨迹与知识管理。
- 按专业工程顺序分层实现，不追求快速演示。实施顺序以 `docs/20_DELIVERY_PLAN.md` 为准，实际完成项见 `IMPLEMENTATION_STATUS.md`。
- 额度限制下按 D01–D13 分期交付，区别于技术层 P0–P7。每期可跨会话；每期结束保存完成项、验证、遗留问题和下一动作。先读状态再续做，默认不在当期交接后自行跨期。不要假定能读取用户账户剩余额度。
- 已有 D03–D09 数据库/执行/数据、模型/Agent/Skills/MCP/知识及可启动 HTTP API；本期验收见状态文件，D10 实验工作区与 D11 平台控制台已完成本地验收，D12c.2 已完成 rootless 单机模拟部署本地验收；一致性备份恢复、完整 E2E/长测与现场尚待后续门禁。不能把计划、fixture 或接口定义称为已实现产品能力。
- 用户已授权安装工作所需依赖；优先使用项目 `.venv`，锁定新增依赖。不为普通可逆开发操作重复询问。

## 分层与实现边界

1. 顺序：P0 工程/需求 → P1 契约/领域 → P2 持久化/确定性执行/Simulator → P3 专用 Agent/模型/Skills/MCP → P4 API/身份 → P5 Web → P6 集成部署 → P7 现场。
2. `src/alap/domain` 不依赖 FastAPI、LangGraph、供应商 SDK、数据库或网络。应用用例依赖端口，外部实现放适配器。`contracts/` 为共享 Schema 唯一源。
3. Agent 只读或提交提案；设备写由 Scheduler 和 Gateway 执行。MCP 工具发现与 Skill 导入不授予权限。
4. PostgreSQL 是业务权威，设备读回是物理依据；NATS 是通知。LangGraph checkpoint 与实验执行状态分离。
5. 审批绑定计划版本/hash、设备、参数、策略/能力与有效期；旧审批不能覆盖变化后的计划。
6. 单设备单写者；Gateway 检查 epoch、fencing、租约；UNKNOWN 不盲重试，相关后继冻结后对账。
7. 暂停/取消先表达请求，执行器确认后才能显示完成。目标值、实际值、数据鲜度分别建模。
8. Dataset 完整文件/校验和/元数据提交后才 COMMITTED；Schema 通过不等于完成存储或获授权。
9. 状态与 outbox 同事务，实验 SSE 使用 experiment_seq，快照包含 event_cursor；不要用 aggregate_seq 混合多个对象。
10. 真机操作遵循第 11/12 章现场门禁；模拟参数不构成真机授权。Proposed 或开发基线决策不等于现场批准。

## 环境与命令

当前基础层 Python 3.14，版本以 pyproject.toml 和 requirements-dev.lock 为准。后续框架/驱动接入时验证兼容性。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-build-isolation --no-deps -e .
# 先按 docs/D03_DATABASE_DEVELOPMENT.md 启动隔离 PostgreSQL
# 按 docs/D05_DATA_RECOVERY_DEVELOPMENT.md 启动 JetStream
# 设置 ALAP_TEST_DATABASE_URL、ALAP_TEST_NATS_URL；全套检查不允许静默跳过集成测试
.venv/bin/python scripts/check.py
```

编辑源文档或契约后生成：

```bash
.venv/bin/python scripts/build_lifecycle_reference.py
.venv/bin/python scripts/build_design.py
.venv/bin/python scripts/build_openapi.py
```

不得直接维护生成文件。按改动运行适当测试；收尾执行统一检查。范围覆盖、异常路径及尚未验证的层次应明确记录。依赖升级后同步锁文件；不要把本机 editable 路径写进锁文件。

## 协作与记录

- 默认中文；明确区分已设计、已编码、已本地验证、已集成验证和已现场验收。
- 变更关联 FR/NFR、契约、测试和文档；阶段进度及时写入 IMPLEMENTATION_STATUS.md。
- 当前会话为 Linux `/home/endsen/ALAP`，已同步远程 D11 基线 836ec53；此目录 Git 元数据不可用，历史基线检出 `/tmp/alap-github-dliggqw9` 已随重启丢失，origin 为 endsen/ALAP；后续推送前重新取得远程基线。当前 D12 进行中，续接先读 D12 交接；实际环境及路径每次重新核对，勿沿用历史 macOS 路径。
- 使用多 Agent、外部服务或真机不是本文件隐含授权；普通测试使用离线模型替身与模拟仪器。
