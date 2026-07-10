# SmartUA 大模型路由系统（v2）

> **版本说明**：本文档为 v2，基于 SmartUA **v1.6.0** 重写。保留原 `LLM_ROUTING.md`
> 的多模型路由、解耦启动、优雅降级等核心设计（v1 原版保留），并**新增** Agent Loop
> 如何使用 LLM 做规划（可选增强）、以及无 LLM 时规则引擎兜底的行为。
>
> 文档路径：`docs/LLM_ROUTING_v2.md`

---

## 1. 核心设计原则（沿用 v1，不变）

1. **服务启动与大模型集成解耦**：无需任何 LLM API Key 即可启动运行；LLM 是增强层，不是依赖层。
2. **优雅降级**：LLM 不可用 → 规则引擎兜底（始终可用）。
3. **多模型智能路由**：按意图复杂度 / 数据敏感性 / 响应时间 / 成本自动选最优模型。

---

## 2. 支持的 LLM Providers（沿用 v1，不变）

| Provider | 模型 | 能力标签 | 成本($/1k) | 延迟 | 优先级 |
|----------|------|---------|-----------|------|--------|
| Claude | Claude 3.5 Sonnet | 复杂分析/策略/创意 | 3.0 | 2000ms | 1 |
| GPT-4o | GPT-4o | 快速/创意 | 2.5 | 1500ms | 2 |
| DeepSeek | DeepSeek V3 | 代码/快速 | 1.0 | 800ms | 3 |
| 本地模型 | Qwen 2.5 72B | 敏感数据/内部 | 0.1 | 5000ms | 4 |

路由策略：`best_fit` / `fastest` / `least_cost` / `highest_quality`（由 `llm_routing_strategy` 配置）。

### API（沿用 v1，不变）
- `GET /api/v1/llm/status`：查看各 Provider 可用性与路由策略
- `POST /api/v1/llm/test-route?intent_type=&data_sensitivity=`：测试路由决策

### 无需配置即可运行
不配置 API Key → 纯规则引擎模式，所有功能（含 Agent）正常可用。

---

## 3. v2 新增：Agent Loop 中的 LLM 使用方式

Agent Loop（`agent_runtime/loop.py`）把 LLM 作为**规划增强**，而非必需依赖。

### 3.1 开关与探测
```python
# backend/app/config.py
agent_use_llm_planning: bool = True   # 是否用 LLM 做 ReAct 规划
```
```python
# loop._llm_available()
if not settings.agent_use_llm_planning:
    return False
try:
    from app.services.llm import is_llm_available
    return is_llm_available()
except Exception:
    return False
```

### 3.2 LLM 规划路径（`_llm_decide`）
当 LLM 可用时：
1. 把**工具清单**（`registry.system_prompt_snippet()`，含每个工具的 `risk_level` / `side_effect` / 参数）注入系统提示。
2. 把已发生的步骤（💭思考 / 👁观察 / ✅已执行）与当前目标拼为对话历史。
3. 调用 `LLMRouter.chat_completion("campaign.optimize_batch", messages, data_sensitivity="low")`。
4. 解析返回的 ReAct JSON：
   - `{"thought":"..","action":"工具名","params":{...}}` → 执行该工具
   - `{"thought":"..","final_answer":"结论文本"}` → 终态
5. **Agent 只「提议」不替人审批**：LLM 规划出的 L1/L2 写动作仍转 `awaiting_approval`，由人审批
   （与规则引擎路径完全一致的安全护栏）。

### 3.3 规则引擎兜底（`_rule_based_decide`）
当无 LLM / `agent_use_llm_planning=false` / LLM 调用异常时，自动降级到确定性规则规划器：
- 按关键词把模糊目标拆成多步：暂停低 ROI / 给高 ROI 加预算 / 换素材 / 报告。
- 预算增幅与暂停阈值**优先咨询 Phase 3 策略层**（`strategy.advise`），回退 Phase 2 记忆
  收敛（`memory.suggest_budget_increase_cap`），再回退硬编码默认。
- 行为一致、不报错——本环境（无 API Key）即走此路径，Agent 全功能可演示。

### 3.4 为什么这样设计
与项目「LLM 解耦 + 优雅降级」原则一致：**Agent 的每一步动作都应可追溯、可回滚**，
LLM 仅提供"更聪明的规划"，最终执行/审批/记忆仍由平台护栏与确定性逻辑掌控。

---

## 4. 解析模式对照（v2）

| 模式 | 触发条件 | 特点 |
|-----|---------|------|
| `llm_enhanced` | LLM 可用 + `agent_use_llm_planning=true` + 解析成功 | Agent 用 LLM 规划多步动作 |
| `rule_based` | 无 LLM / 关闭规划 / LLM 失败 | Agent 用确定性规则规划（默认兜底），全程可用 |

> 意图引擎（`/intent/execute` 单轮解析）同样有 `parse_method: llm_enhanced | rule_based`，
> 与 Agent Loop 共享同一套路由与降级机制。

---

## 5. 架构优势（沿用 v1，不变 + v2 补充）

1. **无强制依赖**：LLM 是可选增强，即使全不可用，Agent Loop（规则规划）+ 主动自治照常工作。
2. **渐进式启用**：先上线基础 Agent（规则引擎），后续配 LLM Key 即获得更智能的规划。
3. **高可用**：LLM 中断不影响核心投放操作与主动巡检。
4. **成本可控**：按意图类型路由到最合适模型。
5. **隐私保护**：敏感数据自动走本地模型。

---

*文档版本：v2 | 基于 2026-07-10 SmartUA v1.6.0 | 配套 `ARCHITECTURE_v2.md` / `API_REFERENCE_v2.md` / `CONNECTOR_DESIGN_v2.md` / `USER_MANUAL_v2.md` / `RELATED_PROJECTS_v2.md`*
