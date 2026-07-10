# SmartUA 项目记忆

## 项目定位与演进方向
- SmartUA 是基于 ad-agent / ua-monitor 两个 agent skill 提炼而来的「对话式/意图驱动 UA 投放控制台」。
- 当前（2026-07）定位是"意图驱动的投放控制台"，**还不是 agentic ad platform**：意图引擎为单轮解析、execute() 为模拟执行、无记忆/反思闭环。
- 战略共识（2026-07-10）：升级目标 = 真正的 ad agent（目标驱动 + 自主循环 + 记忆反思 + 真实执行 + 人在环）。架构原则 = **平台做身体与护栏，Agent Loop 做大脑，Tool/Skill Registry 桥接**。详见 docs/AGENTIC_AD_PLATFORM_UPGRADE.md。
- LLM 路由（解耦+优雅降级+多模型）是核心亮点，升级中保留。

## 关键代码事实（审阅时确认）
- `intent_engine.py`：8 个硬编码意图类；`_parse_with_llm` 为单轮 prompt；`execute()` 写 `platform_response_json={"simulated": True}`。
- schema 已预留 `impact_2h/24h/7d_json`，但无回填逻辑（"闭环学习"为空壳）。
- `IntentCenter.jsx` 用 `MOCK_INTENT_EXECUTIONS` 展示历史，与"无 Mock"原则冲突。
- 已新增 `services/simulation/engine.py`（有状态因果模拟引擎：预算/出价/素材疲劳→ROI/CPI，可复现、可算动作影响）+ `services/connectors/mock_media.py`（注册为 `mock` 渠道，写操作真改状态）。替代被封的 Meta 作为 Phase 0 进化闭环的数据土壤。运行验证：`scripts/demo_mock_media.py`。
- **Phase 1 Agent Loop 已完成（2026-07-10，v1.2.0）**：`services/agent_runtime/`（session.py 多轮状态 + tools.py Tool/Skill Registry 带 L0-L3 风险元数据 + loop.py ReAct 循环，规则引擎兜底 + LLM 规划路径 + L1/L2 人在环审批）。写工具真实执行并回填 `impact_2h/24h/7d_json`；新增 `api/v1/agent.py`（多轮 Agent 对话 API）。验证：`scripts/demo_agent_loop.py`。meta 被封期间 `config.agent_default_platform="mock"`，恢复后改回 "meta" 零改动。
- **Phase 2 记忆/反思已完成（2026-07-10，v1.3.0）**：`services/agent_runtime/memory.py`（Episode + 进程内单例 `EpisodicMemory`，跨会话持久，写动作执行后由 `tools._write` 自动沉淀；`suggest_budget_increase_cap()` 等决策修正）+ `reflection.py`（`Reflector.reflect()` 复盘为摘要+启发式规则，规则引擎兜底/可选 LLM）。闭环关键点：`loop._rule_based_decide` 预算分支 consult 记忆收敛增幅。新增 `POST /agent/reflect` 与 `POST /agent/sessions/{id}/reflect` 端点；`config.agent_reflection_enabled` 可开关。验证：`scripts/demo_phase2.py`（场景C 新账户下规划器把预算增幅从 +20% 收敛到 +10%）。记忆目前进程内、重启即失，生产需落库为 EpisodicMemory 表。
- **Phase 3 策略自演化已完成（2026-07-10，v1.4.0）**：`services/agent_runtime/strategy.py`（`StrategyStore` 从 Episode 记忆挖掘可学习参数 `budget_increase_cap`/`pause_roi_threshold`/`rotate_when_roi_below`，带 confidence+n_samples+source；`advise(key,default)` 供规划器查询；**落盘 JSON 持久化** `config.agent_strategy_path`→`backend/data/strategy.json`，解决 Phase 2 重启即失、支持跨账户/跨进程迁移）。接入：`AgentContext` 加 `strategy`；`loop._rule_based_decide` 预算增幅/暂停阈值**优先咨询策略层**，回退记忆收敛，再回退硬编码；`_budget` 把 `_pct` 透传进 Episode 供挖掘；`AgentLoop.learn_strategy()`；API 新增 `POST /agent/strategy/learn`、`GET /agent/strategy`、`POST /agent/strategy/reset`。验证：`scripts/demo_phase3.py`（多账户 6 Episode→learn 出增幅收敛 +10% 并落盘→模拟重启+新账户，规划器从首步即用 +10% 而非默认 +20%，策略 JSON 可被重新加载）。进化闭环（经验→记忆→策略→迁移复用）正式收口。
- **前端对接已完成（2026-07-10，v1.5.0）**：新增 `frontend/src/pages/AgentConsole.jsx`「智能体控制台」——多轮对话 UI（步骤时间线按 kind 渲染 thought/observation/action/approval/final）+ **L1/L2 内联审批**（批准续跑/驳回重规划）+ 多轮追问 + 右侧「智能体大脑」面板（已学策略/经验复盘/学习·重置策略）。`frontend/src/api.js` 新增 `agentAPI`（10 方法覆盖 `/agent/*`）；`App.jsx`+`MainLayout.jsx` 注册 `/agent` 路由与导航项。旧 `IntentCenter` 保留并存。`vite build` 通过；并用真实 HTTP 端到端链（登录→建会话→审批 L1→多轮→策略→学习→复盘）验证，发现并修复 `_record_execution` 误传 `approval_required` 导致审批 500 的 bug。运行：后端 `uvicorn main:app --port 8000` + 前端 `npm run dev`（代理 `/api→:8000`），需先登录。
