# SmartUA → 真正的 Agentic Ad Platform：定位判断与升级方案

> 本文档基于对 README、PROJECT_SUMMARY、ARCHITECTURE、LLM_ROUTING 以及**实际代码**
>（`intent_engine.py` / `intent.py` / `IntentCenter.jsx`）的审阅，回答四个核心问题，并给出分阶段升级方案。

---

## 0. 核心结论（TL;DR）

1. **当前 SmartUA 不算 "agentic ad platform"，它是一个「意图驱动的投放控制台」**——有对话入口，但没有 agent 的自主循环。
2. **你的直觉是对的**：相比原来的 `ad-agent` / `ua-monitor`（agent + skill）形态，当前平台化版本**确实丢失了"进化能力"**。原因是平台把"agent loop（感知-规划-行动-反思）"简化成了"单轮意图解析 + 日志记录"，且没有任何记忆与反思回路。
3. **真正的 ad agent** = 目标驱动 + 自主决策循环 + 记忆/反思 + 真实执行 + 人在环。它会主动盯盘、会规划、会复盘、会越做越好。
4. **升级方向不是"退回 agent+skill"，而是"把 agent loop 装进平台"**：平台继续做"身体与护栏"（数据架构、安全分级、真实执行、审计），agent loop 做"大脑"。两者结合才是可落地的生产级 agentic 平台。

---

## 1. 先对齐：四种形态的区别

| 维度 | 传统投放平台 | 当前 SmartUA | Agent + Skill（原 ad-agent/ua-monitor） | 真正的 Ad Agent |
|------|------------|-------------|----------------------------------------|----------------|
| **驱动方式** | 菜单 + 表单 | 自然语言指令（单轮） | 目标/对话 + 技能调用 | 目标驱动 + 自主循环 |
| **自主性** | 0%（全人工） | 低（人下指令才动） | 中（有 think→act→observe 循环） | 高（可主动发起、自主规划） |
| **对话形态** | 无 | 单轮命令解析 | 多轮、可澄清 | 多轮、可解释、可主动汇报 |
| **执行** | 直接调 API | **模拟（simulated:True）** | 真实调用技能 | 真实调用 + 回采结果 |
| **学习/进化** | 无 | **无（闭环是空壳）** | 取决于是否设计记忆（多数无） | **有记忆 + 反思 + 策略自演化** |
| **安全机制** | 二次确认 | L0-L3 分级（设计好，未全落地） | 通常较弱 | 护栏即工具元数据，天然分级 |

**关键洞察**：当前 SmartUA 在"平台能力"（数据架构、安全分级、多租户、UI、审计）上**强于**原始 agent+skill，但在"智能进化"（循环、记忆、反思）上**弱于**一个设计良好的 agent+skill。升级要做的是把两者的优点合起来。

---

## 2. 回答你的四个问题

### Q1：这个项目算是 agentic ad platform 么？

**目前不算。** "Agentic" 的核心是**自主性（autonomy）+ 持续循环（loop）+ 目标导向（goal-driven）**。SmartUA 目前：

- 是**被动响应式**：必须人输入一句指令才动作，没有"主动盯盘→发现问题→提议/处置"的能力。
- 意图引擎是**单轮解析器**，不是 agent runtime：输入 → 分类到 8 个硬编码意图 → 生成记录。没有规划（planning）、没有工具选择推理、没有观察后再决策。
- 执行是**模拟的**（`execute()` 里 `platform_response_json={"simulated": True}`），没有真实闭环。
- 没有**记忆**与**反思**，所以不存在"越用越聪明"。

更准确的定位表述：**「对话式 / 意图驱动的 UA 投放控制台（Conversational UA Console）」**。这本身是一个有价值的产品形态，只是别在对外叙事里把它叫成 agentic platform——那会过度承诺。

### Q2：有大模型对话能力，但区别于 agent+skill 会缺少进化能力？

**确认，而且这是当前架构最该补的短板。** 逻辑链如下：

- "进化能力"不是"用了 LLM"就自动获得的。它来自三个东西：**记忆（记住做过什么、结果如何）+ 反思（复盘成败）+ 策略更新（把复盘变成下次更好的决策）**。
- 原始 `ad-agent`/`ua-monitor`（agent+skill）之所以"有潜力进化"，是因为 agent 框架天然带 `think → call skill → observe → think again` 的循环，只要再补一层记忆/反思，就能闭环。
- 当前 SmartUA 把这套循环**拍扁**成了 `parse(intent) → create_execution() → (mock) execute()`。LLM 在这里只做一次性的"自然语言→意图类"映射（`_parse_with_llm` 是单轮 prompt，返回即结束），**调用完就丢，不留存、不复盘、不复用**。
- 证据：
  - `execute()` 全模拟，没有真实结果可复盘；
  - `intent_engine.py` 没有任何 memory / history / feedback 入参；
  - schema 虽预留 `impact_2h/24h/7d`，但**没有任何回填逻辑**（"闭环学习"是壳）；
  - `IntentCenter.jsx` 历史用 `MOCK_INTENT_EXECUTIONS`，连展示都不是真实的。

所以结论：**当前方案相比 agent+skill，不是"多了进化"，而是"把进化循环拆掉了"**。要补回来，不是回到纯 agent+skill，而是把 agent loop 作为一等公民嵌回平台。

### Q3：什么才是真正的 ad agent？

一个真正的广告投放智能体，应同时具备以下能力：

1. **持续感知（Perceive）**：通过连接器 + 四层数仓，实时/周期掌握账户、素材、ROI、CPI、归因状态。
2. **目标导向规划（Plan）**：给定目标（如"在 ROAS≥1.5 前提下稳住量级"），能自己拆步骤、定优先级、排时序——而不是等指令。
3. **真实行动（Act）**：通过统一的工具/技能注册表调用真实媒体 API（暂停、调价、建计划、换素材），并在安全护栏内执行。
4. **结果回采与反思（Reflect）**：行动后拉取 2h/24h/7d 指标，判断"这步到底有没有用"，形成成败样本。
5. **记忆与策略自演化（Learn）**：把成败样本沉淀为记忆，更新启发式/策略/提示词，使下一次决策更好；并能为不同 app/账户学到不同打法。
6. **与人协作（Collaborate）**：高风险走人在环（L2），中等风险主动提议并给推理（L1），低风险自动执行（L0）；能解释"为什么这么做"，并在不确定时主动问人。
7. **多轮对话**：能澄清歧义、追问目标、汇报进展，而不是一次性解析。

一句话区分：**命令解析器 = 你说 X 它做 X；真正的 ad agent = 它知道目标，自己想出 X，并且越做越准。**

### Q4：如果要往这个方向升级，需要怎么做？

核心架构思想（详见下方图示）：

> **平台 = 身体 + 护栏；Agent Loop = 大脑。**
> 把所有后端能力（暂停/调价/建计划/查询/报表）注册为 **Tool/Skill Registry** 中的"工具"，每个工具带风险元数据 → 自动映射到 L0-L3 分级。Agent Loop 在护栏内调用这些工具，并写入记忆、触发反思。

#### 关键桥梁：Tool/Skill Registry（平台与 agent 的接口）
- 现有 FastAPI 端点（campaign/creative/data/intent）天然就是"工具"。
- 每个工具声明：`name`、`description`、`risk_level`（自动来自 L0-L3）、`params_schema`、`side_effect`（读/写）。
- Agent 不直连媒体，只通过 Registry 调用 → 安全分级、审计、多租户天然生效。
- 这样"平台化"和"agent+skill"就统一了：**平台提供经护栏的工具，agent 负责编排与决策**。

#### 分阶段路线图

**Phase 0 — 夯实真实闭环（地基，先补"信任"）**
- 目标：让"执行"和"学习"有真实数据可谈。
- 任务：
  1. 实现真实 Connector（Meta/Google/TikTok Marketing API），替换 `execute()` 的 `simulated`。
  2. 行动后**回采**指标，把 `impact_2h/24h/7d_json` 真实回填（schema 已预留，只缺逻辑）。
  3. 修复 `IntentCenter.jsx` 的 Mock 历史，改为读真实 `/intent/executions`。
- 验收：一个真实的"暂停低 ROI campaign → 24h 后看到 ROI/CPI 变化"可被系统记录。

**Phase 1 — 引入 Agent Loop（进化的引擎）✅ 已完成（v1.1.0）**
- 目标：从"单轮解析"升级为"规划 + ReAct 循环 + 多轮对话"。
- 任务：
  1. 在后端加 `agent_runtime`：输入可以是"目标"而不只是"指令"（如"把美国区 ROAS 提上来"）。
  2. ReAct 风格循环：`think → select tool → (execute or propose) → observe → think again`，直到目标达成或需人确认。
  3. `IntentCenter` 从"单句输入框"升级为"多轮对话 + 计划可视化"（展示 agent 的逐步推理与待确认动作）。
- 验收：给一个模糊目标，agent 能拆成多步、调用多个工具、中途向人确认高风险动作。
- 实现位置：
  - `backend/app/services/agent_runtime/session.py`：多轮会话状态（目标 / 步骤 / 待审批 / 上下文）+ 进程内会话仓库。
  - `backend/app/services/agent_runtime/tools.py`：Tool/Skill Registry，把"观察 / 筛选 / 预测影响 / 暂停 / 调预算 / 调出价 / 换素材 / 报表"封装为带 **L0-L3 风险元数据**的工具；写工具经 `MockMediaConnector` 真实执行并回填 `impact_2h/24h/7d_json`（闭环学习空壳首次被填上数据）。
  - `backend/app/services/agent_runtime/loop.py`：ReAct 编排，**规则引擎兜底 + LLM 规划路径**；**L1/L2 高风险动作走人在环审批**（批准续跑、驳回后记住被驳动作并重新规划）。
  - `backend/app/api/v1/agent.py`：多轮 Agent 对话 API（`POST /agent/sessions` / `/approve` / `/message` / `GET /agent/sessions/{id}`）。
  - 验证：`scripts/demo_agent_loop.py`（模糊多目标 → 拆多步 → L1 审批 → 真实执行 → 观察 → 回采影响 → 终态，含驳回分支）。
- 决策来源（与"LLM 解耦 + 优雅降级"原则一致）：有可用 LLM 时走 LLM 规划（解析 ReAct JSON）；无 LLM（如本环境）自动降级到确定性规则规划器，行为一致、不报错。

**Phase 2 — 记忆与反思（进化的燃料）** ✅ **已完成（v1.3.0）**
- 目标：让系统"记住并复盘"，把经历沉淀为可复用的启发式。
- 已实现（见 `backend/app/services/agent_runtime/memory.py` + `reflection.py`）：
  1. **Episodic Memory（单例、跨会话持久）**：每次写动作执行后，由 `tools._write` 自动沉淀为 `Episode`，含 `pre_state`（动作前账户快照）+ `impact_2h/24h/7d_json`（反事实因果效应）+ `outcome`。无 DB 依赖（演示友好），生产应落库为 `EpisodicMemory` 表。
  2. **Reflection 模块**：`Reflector.reflect()` 把 Episode 复盘为「自然语言摘要 + 启发式规则」，规则引擎兜底、可选 LLM 增强。已提取出：止损规则、预算边际递减（增幅收敛 ≤10%）、素材疲劳短期提振、提价伤 ROI。
  3. **反哺规划（闭环关键）**：`loop._rule_based_decide` 的预算分支 consult `memory.suggest_budget_increase_cap()`，当历史加预算 7d 平均 ΔROI 转负时自动收敛增幅 —— 实现"同一类问题第二次处理更稳"。
- 验证：`scripts/demo_phase2.py` —— 场景A 多目标执行沉淀 4 条 Episode → 场景B 复盘提取规则 → 场景C 新账户（换种子=新账户）下，规划器 consult 记忆把预算增幅从默认 +20% 收敛到 +10%（572 而非 624），证明记忆跨账户、跨会话生效。
- API：`POST /agent/reflect`（全局复盘）、`POST /agent/sessions/{id}/reflect`（按会话复盘）。

**Phase 3 — 策略自演化（进化的产物）** ✅ 已完成（v1.4.0）
- 目标：策略从"硬编码"变为"可学习、可迁移、可持久"。
- 已实现：
  1. `backend/app/services/agent_runtime/strategy.py`：`StrategyStore` 从 Episode 记忆**挖掘**可学习参数
     （`budget_increase_cap` 加预算增幅上限 / `pause_roi_threshold` 暂停阈值 / `rotate_when_roi_below` 换素材触发下限），
     每条带 `confidence`（依样本量）+ `n_samples` + `source`；`advise(key, default)` 供规划器查询，无/低置信度优雅回退默认。
  2. **落盘持久化**（`config.agent_strategy_path` → `backend/data/strategy.json`）：解决 Phase 2「重启即失」风险，
     策略可跨进程、跨账户迁移（新账户从首步即用学到参数，无需重新踩坑）。
  3. 规划器（`loop._rule_based_decide`）预算增幅与暂停阈值**优先咨询策略层**，回退 Phase 2 记忆收敛，再回退硬编码默认。
  4. API：`POST /agent/strategy/learn`（记忆→策略+落盘）、`GET /agent/strategy`、`POST /agent/strategy/reset`。
- 验收（见 `scripts/demo_phase3.py`）：多账户累积 6 条 Episode → learn 出增幅收敛至 +10% →
  模拟「重启+新账户」后，规划器从首步即用 +10%（对照无策略默认 +20%），且策略 JSON 已落盘可被重新加载。
- 注：文档原规划的"四层数仓特征 / 策略 A/B / 元学习优化提示词"仍是后续增强方向，当前 Phase 3 已交付**可学习策略参数**这一核心。

**前端对接（v1.5.0）** ✅ 已完成
- 新增 `frontend/src/pages/AgentConsole.jsx`「智能体控制台」：多轮对话 + 步骤时间线 + **L1/L2 内联审批** + 右侧「智能体大脑」面板（已学策略 / 经验复盘 / 学习·重置策略）。
- `frontend/src/api.js` 新增 `agentAPI`（覆盖 `/agent/*` 全部端点）；`App.jsx` + `MainLayout.jsx` 注册 `/agent` 路由与导航。
- 运行：后端 `uvicorn main:app --port 8000` + 前端 `npm run dev`（Vite 代理 `/api → :8000`），需先登录（Agent 端点要求 JWT）。
- 经验：对接过程中靠端到端 HTTP 调用链验证，发现并修复了 `_record_execution` 误传 `approval_required` 导致审批 L1 动作 500 的 bug。

**Phase 4 — 主动式自治（进化成熟态）** ✅ 已完成（v1.6.0）
- 目标：从"人召唤"到"主动守护"。
- 已实现（见 `backend/app/services/agent_runtime/autonomy.py`）：
  1. APScheduler 周期巡检：检测到异常 → 复用 Agent Loop / Tool Registry 分级处置。
     - 异常类型：`CPI 飙升 / ROI 跌破阈值 / 素材疲劳 / 花费异常 / 账户被封（Meta appeal 等）`。
     - L0（换素材）**自动执行**；L1/L2（暂停/调预算）生成"主动提案"进入**人在环审批队列**；
       仅通知类（花费异常、账户被封）**不自动改动**，避免危险自动缩量。
  2. 主动汇报：扫描历史 + 告警流在「智能体控制台 → 主动自治」面板可见，待审批提案可一键批准。
  3. 账户自适应：ROI 止损阈值优先采用 Phase 3 已学策略（`pause_roi_threshold`），随经验收敛；
     同 (异常, campaign) 冷却去重避免重复打扰。
- 验证：`scripts/demo_phase4.py`（疲劳自动轮换 + ROI 跌破待审批 + 账户被封告警 + 去重 +
  数据驱动阈值）+ `scripts/test_autonomy_http.py`（真实 HTTP：登录→巡检→审批→告警流→启停）。
- 验收达成：系统在未收到指令时，主动发现并分级处置异常（自动轮换 / 提案暂停 / 账户被封告警），
  且 ROI 止损阈值由 Phase 3 策略驱动，处置标准随经验自适应。

#### 建议的"最小切片"（先做的第一刀）
不要一上来做全套。建议从 **Phase 0 + Phase 1 的交集**切一个 MVP：
> 选一个真实媒体（如 Meta）接一个真实动作（暂停/调预算），打通"真实执行 → 24h 回采 → 多轮对话里展示计划与结果"。
这条链路一旦跑通，Phase 2-4 的"记忆/反思/演化"就有了真实数据土壤，否则都是空中楼阁。

---

## 3. 风险与权衡

- **过度自动化风险**：UA 真金白银，L2/L3 必须守住人在环；agent 的"自主"应严格受 L0-L3 约束。
- **归因难题**：投放效果受季节/竞品/算法影响，单步动作的效果"因果"很难干净隔离——反思模块要接受" quasi-causal"，用对照/增量法而非简单前后对比。
- **LLM 不可靠**：保留现有"规则引擎兜底 + 多模型路由 + 优雅降级"的设计，agent 的每一步动作都应可追溯、可回滚。
- **数据真实性**：先消灭前端 Mock，否则团队会被假数据误导决策。

---

## 4. 下一步建议（可立刻启动）

1. **本周**：确认一个可对接的真实媒体沙箱账号（或 mock-server 但带真实回采时序），把 `execute()` 的 `simulated` 拿掉。
2. **两周内**：实现 `impact_*` 回填 + 前端真实历史，跑通 Phase 0 MVP。
3. **同步**：在文档/对外叙事里，把定位从 "agentic platform" 调整为 "**对话式智能投放控制台（迈向 agentic）**"，避免过度承诺，也给团队一个清晰的演进叙事。

---

*版本：v0.1 | 基于 2026-07-10 代码审阅 | 待评审*
