# ALAP v3.1 契约目录

这是开发中的协议与领域边界，尚无部署的 API 服务。报文版本为 2.0，企划版本为 3.1，REST 路由版本为 `/api/v1`，三者分别管理。

- `*.schema.json`：Agent、Capability、Command、Event、StableCondition、PlanTask、PlanProposal、PlanRevision、DatasetManifest 共 9 份共享结构。
- `examples/*.json`：每份 Schema 对应一个可验证正例；`simulator_skills.json` 为仅限模拟的技能约束，不能用于真实设备限值。
- `openapi.base.yaml`：手写路由和非共享结构。
- `openapi.yaml`：生成规范；共享组件由 JSON Schema 生成，REST 请求删除服务器身份字段，公共数据结果限定 COMMITTED。

项目依赖安装后，在根目录运行：

```bash
.venv/bin/python scripts/build_openapi.py
.venv/bin/python contracts/validate_contracts.py
.venv/bin/python -m pytest -q
```

`ContractCatalog` 从显式目录加载 Schema，引用只从本地 registry 解析，不进行网络下载。结构验证与领域验证分开：通用 validate 仅检查形状/JSON 值；validate_proposal/revision/dataset/command 增加相应语义检查。调用者必须使用适当的语义入口，实际权限、资源实时状态和物理执行仍属于后续应用/执行层。

`source_agent_run_id` 为当前完整 Agent 计划的来源字段；REST 不接受客户端自行填写，后续应用层从授权 Agent run 获取。人工静态模板应经明确的模板规划运行记录产生计划；不能伪造已有 Agent 身份。此应用映射在 P3/P4 验证。

完整规则与设计取舍见 `docs/19_CONTRACT_DECISIONS.md`；历史 v3.0 协议仍在原 ZIP 中。
