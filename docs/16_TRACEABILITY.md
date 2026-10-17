# 16 · 需求—模块—契约—验证追踪表

> v3.1 开发基线；原始 v3.0 保存在根目录合订本与 ZIP。新增平台范围见第 17、18 章，契约规则见第 19 章，实施顺序以第 20 章为准。

本表用于设计验收、Issue/PR 评审，完整需求见 `02_SRS.md`；测试编号参见 `12_EVALUATION.md`。

| 需求 | 负责模块/章节 | 契约入口 | 关键验证 |
|---|---|---|---|
| FR-001 | API Auth，04/11 | `openapi.yaml` security | Observer 设备写 403，EVAL-14 |
| FR-002 | Experiment Service，07/09 | `POST /experiments` | 幂等键、重复提交 |
| FR-003 | Planner Agent，05/06 | Agent Manifest + Proposal JSON 示例 | EVAL-01，计划 DAG 校验 |
| FR-004 | Approval Service，04/07 | `POST /experiments/{id}/approvals` | EVAL-12 |
| FR-005 | Agent Registry，05 | `agent_manifest.schema.json` | 配置版本 hash |
| FR-006 | Tool/Skill Registry，05/11 | Schema + Tool Metadata | EVAL-02/EVAL-03 |
| FR-007 | Device Registry，08 | `capability.schema.json`, instruments API | EVAL-14，离线禁写 |
| FR-008 | Scheduler，07 | Command Envelope/Resource Lease | EVAL-06 |
| FR-009 | Gateway/CommandLedger，07/08 | `command.schema.json` | EVAL-04/EVAL-05 |
| FR-010 | ExperimentView，06/09 | Dataset API/ABAC | 跨实验数据拒绝 |
| FR-011 | Data Service，09 | Dataset Manifest | EVAL-10 |
| FR-012 | SSE Service，04/10 | `GET /experiments/{id}/events` | EVAL-07 |
| FR-013 | Run Control，04/07 | `POST /runs/{id}/actions` | EVAL-09 |
| FR-014 | Multi-Agent Coordinator，06 | Proposal/Agent Manifest | EVAL-13 |
| FR-015 | Safety Gateway，08/11 | Command Policy/Fencing | EVAL-02/EVAL-14 |
| FR-016 | Agent Platform，05/06 | Autonomy Envelope | 越界变新提案 |
| FR-017 | Workflow Manager，07 | Plan Revision | EVAL-12 |
| FR-018 | Data Explorer，04/09 | Dataset API | 校验和/元数据导出 |
| FR-019 | Gateway/Deploy，08/13 | Capability + Command | 站点离线演练 |
| FR-020 | Skills Registry，05 | Agent Manifest | 技能版本锁定 |

## 发布审核

1. 所有 MUST 需求均有至少一个通过的自动化或现场测试及存档的结果链接。
2. 所有可影响物理世界的操作，在现场安全清单中有责任人及对应厂商规程。
3. `EVAL-02,03,04,05,06,09,10,11,12,14` 为阻断项；不允许以 Agent 自评“已安全”代替。
4. 文档更改必须更新追踪表；若 OpenAPI/Schema 更新而前端/网关未更新，发布不通过。

## v3.1 新增追踪

| 需求 | 设计入口 | 实施阶段 | 验证 |
|---|---|---|---|
| FR-021/022 | 18 多供应商、17 模型页 | P3/P4/P5 | EVAL-16/17/18 |
| FR-023 | 17 Skills、05 Registry | P3/P4/P5 | EVAL-19 |
| FR-024 | 17 MCP、11 权限 | P3/P4/P5 | EVAL-20 |
| FR-025 | 17 Dashboard、13 观测 | P4/P5 | EVAL-22 |
| FR-026 | 17 用量、18 Adapter | P3/P4/P5 | EVAL-21 |
| FR-027 | 17 轨迹、13 观测 | P2/P3/P4/P5 | EVAL-22 |
| FR-028 | 17 知识、05 Context | P3/P4/P5 | EVAL-23 |
| FR-029 | 17 页面与权限 | P4/P5 | EVAL-18/24 |

上述是规划追踪，不代表用例已执行。当前基础层代码与测试见根目录 IMPLEMENTATION_STATUS.md。

## D02 已执行与后续验证

| 需求范围 | 已落地证据 | 尚未验证 |
|---|---|---|
| FR-004 审批版本绑定 | lifecycle 的审批状态、证据 hash/版本/期限测试 | 数据库权限、计划不可变性、撤销并发（D03） |
| FR-009 命令执行 | tests/test_lifecycle.py：ACK 不代表成功、UNKNOWN 隔离、原命令不重放、取消竞争 | Gateway journal、实际 fencing 与故障恢复（D04） |
| FR-011 数据发布 | 提交证据守卫、损坏后撤回状态；共享状态 Schema | 文件持久化与数据库提交中断（D05） |
| FR-012 事件恢复 | 第 22 章锁顺序、outbox/游标/快照事务方案 | 真实事务、消息重复与 SSE 恢复（D03/D05/D09） |
| 跨接口一致性 | tests/test_contract_consistency.py：六种枚举与共享 Schema、OpenAPI 引用一致 | 实际 API 行为（D09） |

D02 完整本地检查输出保存在 reports/d02-validation.txt；不等价于集成/现场 EVAL 通过。
