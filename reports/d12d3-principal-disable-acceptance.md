# D12d.3 主体禁用部署验收

2026-10-25，第二十五批；关联 FR-010/014/027、NFR-001/002/012 与 EVAL-22。D12d.3 尚未完成。

使用既有后端 a7a87199/Web fd41b31a、d12_002、独立常驻 Agent 和本地 HTTPS 模型替身。为 OpenAI/DeepSeek 格式各创建两个独立非管理员实验 operator，覆盖调用前与模型 SSE 首片后主体禁用，共 **4 项部署案例通过**。没有在线模型或真机，也没有手工 advance 或终态 seed。

先验证非管理员自身禁用请求为 403，然后通过 admin 管理 API 禁用指定测试主体。脚本只读确认主体已禁用，但原实验成员权限仍有效、设备范围保持完整，排除成员撤权/缩范围作为替代原因。原令牌读取详情/轨迹/提案、取消均立即 401/UNAUTHENTICATED。常驻 worker 根据原提交人复核，调用前模型请求 0、响应期间请求 1，最终均 FAILED/ACCESS_REVOKED。仅追加一次 blocked 事件（prior_stage=model/inflight，流中标记 model_outcome_unknown），已提交 checkpoint 的其余字段与预算保留。工具调用 ledger、提案及计划/审批/Run/Task/Command/Dataset 写入均为 0。

真实 HTTPS 流在管理 API 禁用与读取拒绝确认后才放行。收尾后再次重启 worker、等待空 tick，数据库状态/版本/轨迹/写入计数及请求数不变，禁用令牌仍 401；不重放模型。主体未恢复，不将其称为重授权验证。证据 `d12d3-principal-disable-evidence.json`，运行日志 `d12d3-principal-disable-run.txt`。

完整后端 **638 项通过（583.49 秒）**，真实 PostgreSQL/NATS 未跳过，Ruff/格式、契约/OpenAPI/生成文档与依赖检查通过，见 `d12d3-principal-disable-backend-validation.txt`。收尾八服务运行、模式 ACTIVE、d12_002/镜像一致；首页 200/匿名 API 401。测试库/角色/token/启用测试配置及身份/成员权限/活动运行/待确认取消/待发布事件均为 0；命令保持 45、15 份 COMMITTED 文件校验通过，QA 端口与隔离模型网络移除，见 `d12d3-principal-disable-final-runtime.json`。

本批仅扩展可选部署验收分支/入口与记录，无产品业务、Web/API 契约、迁移、镜像或依赖变化，不重复浏览器验收。finally 禁用/撤销随机测试身份、令牌、成员权限和配置，保留审计历史；移除专用容器/网络。

MCP 已有集成级发现不授权、Schema 变更重新审批、缓存读取撤权和未知结果不重放测试，尚无本批常驻部署证据。下一批优先实现隔离 MCP 服务下的运行期授权故障部署验收，再补完整受限字段/页面矩阵。主体恢复、所有角色组合仍未覆盖。未进入 D12d.4/D13，未推送 GitHub。
