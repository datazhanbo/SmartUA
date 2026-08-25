# SmartUA 大模型路由系统（v3）

> **版本说明**：本文档为 v3，基于 SmartUA **v1.8.x（2026-07-22）**。v2（`LLM_ROUTING_v2.md`）
> 已完整描述多模型路由、Agent Loop LLM 规划、规则引擎兜底等设计；v3 未改动 LLM 路由本身，
> 仅补充与生产升级路径（Phase 0.1 → 4.3）相关的**边界与责任划分**。
>
> v1（`LLM_ROUTING.md`）、v2 保留，作为演进对照。
>
> 文档路径：`docs/LLM_ROUTING_v3.md`

---

## 1. v3 不变量（继承 v1 / v2）

- LLM 与服务启动**解耦**：无 API Key 也能启动全功能运行。
- **优雅降级**：LLM 不可用 → 规则引擎兜底。
- **多模型路由**：按意图复杂度 / 数据敏感性 / 响应时间 / 成本自动选最优模型。
- Provider 矩阵、路由策略、`GET /api/v1/llm/status` / `POST /api/v1/llm/test-route` 契约与 v2 一致。

---

## 2. v3 强化的边界

生产升级把 LLM 的角色从 v2 的"更聪明的规划者"进一步收敛：

1. **LLM 只提议，不批准**：v3 的每个 L1/L2 写动作都必经审批链 + Dispatcher 状态机 + 幂等键。
   LLM 规划出的写动作和规则引擎产出的写动作走**同一条**护栏。
2. **LLM 不参与真实/模拟决策**：`execution_mode` 由 Connector 契约与配置决定；LLM 无法通过
   提示或工具选择使动作跳过 mock/live 边界。
3. **LLM 不参与影响判定**：`predicted / observed / attributed` 三档影响由代码路径决定
   （`tools._compute_impact` 出 predicted，`impact_collector.run_due_jobs` 从事实表回采 observed
   / attributed）。LLM 的自然语言解释不可以覆盖 envelope 里的 `kind` 与 `completeness`。
4. **LLM 不参与策略提权**：Phase 4.3 的学习门禁只看数据事实（execution_mode / completeness /
   kind），不看 LLM 摘要。LLM 生成的复盘文字可以进 Reflector 显示层，但改不动 `usable_for_learning`。

---

## 3. LLM 数据敏感性（v3 提醒）

生产切 live 后，Agent Session 的上下文里可能出现真实账户 ID、真实预算数值、真实媒体报表
片段。默认 `data_sensitivity="low"` 的调用应改为对应级别：

- `medium`：包含账户 ID / 内部策略参数。
- `high`：包含用户级归因数据 / 财务口径 ROI。

`LLMRouter` 会据此把 high 敏感请求路由到本地模型（Qwen 2.5 72B 等），避免真实经营数据发到
外部 API。这条路径在 v2 已存在，v3 明确列为切 live 前的必检项。

---

## 4. 无 LLM 时的 v3 行为

规则引擎兜底路径与 v2 一致：`_rule_based_decide` 按关键词把目标拆成多步。v3 补充：

- 预算增幅阈值 / 暂停阈值仍**优先咨询 Phase 3 策略层**（`strategy.advise`）。
- Phase 4.3 之后，`strategy.advise` 读取的 `_rules` 是**只由真实 usable 样本学到的**结果 —— 没有真实样本时保持硬编码默认。这条链在 v3 无声地把"Mock 数据永远不改规划"落到了规则引擎路径。

---

## 5. 无变化的其它章节

Provider 矩阵、路由策略、`llm_enhanced` / `rule_based` 模式对照、架构优势总结等，全部沿用 v2。
请直接参考 `LLM_ROUTING_v2.md` 相应章节。

---

*文档版本：v3 | 基于 2026-07-22 SmartUA v1.8.x 实际代码 | 配套 `ARCHITECTURE_v3.md` / `API_REFERENCE_v3.md` / `CONNECTOR_DESIGN_v3.md` / `USER_MANUAL_v3.md` / `RELATED_PROJECTS_v3.md`*
