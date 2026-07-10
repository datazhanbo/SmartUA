# SmartUA 系统架构设计文档（v2）

> **版本说明**：本文档为 v2，基于 SmartUA **v1.6.0（2026-07-10）** 的实际代码重写，反映
> 「Agentic Ad Platform」升级路线（Phase 0→4）落地后的最新架构。v1 原版
> `ARCHITECTURE.md` 予以保留，记录升级前的「对话式意图驱动控制台」形态。
>
> 文档路径：`docs/ARCHITECTURE_v2.md`

---

## 1. 系统定位与一句话总结

> **平台 = 身体 + 护栏；Agent Loop = 大脑；Tool / Skill Registry = 桥接。**

SmartUA 已从 v1 的「对话式 / 意图驱动的 UA 投放控制台」演进为 **迈向 Agentic 的投放平台**：

- **身体（平台）**：四层数据模型、四层数仓、连接器、安全分级（L0–L3）、审计、多租户、JWT、前端控制台。
- **大脑（Agent Loop）**：目标驱动的 ReAct 循环——会规划、会多轮、会观察后再决策、会回采结果。
- **桥接（Tool Registry）**：把平台能力（观察/筛选/预测/暂停/调预算/调出价/换素材/报表）注册为带风险元数据的工具，Agent 在护栏内调用。
- **进化层**：Episodic Memory（记忆）→ Reflection（反思）→ StrategyStore（策略自演化）→ 跨账户/跨进程复用。
- **守护层（Phase 4）**：APScheduler 周期巡检 + 异常分级处置（主动自治）。

代理能力分层（从被动到主动）：

| 形态 | 驱动 | 自主循环 | 记忆/反思 | 主动发起 |
|------|------|---------|-----------|---------|
| v1 控制台 | 人下指令（单轮） | 无 | 无（空壳） | 无 |
| Agent Loop（Phase 1） | 目标（多轮） | 有（ReAct） | 无 | 无（人召唤才动） |
| + 记忆/策略（Phase 2–3） | 目标 | 有 | 有（越做越准） | 无 |
| **+ 主动自治（Phase 4）** | **目标 + 系统周期巡检** | 有 | 有 | **有（主动守护）** |

---

## 2. 总体架构图

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           SmartUA 智能投放平台 (v1.6.0)                          │
├──────────────────────────────────────────────────────────────────────────────┤
│  前端控制台 (React 18 + Vite + AntD 5)                                          │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐    │
│  │ Dashboard│  │ Campaign 详情 │  │ 素材管理     │  │ 🤖 智能体控制台        │    │
│  │ 投放大盘 │  │ 四层下钻     │  │ Creative     │  │  多轮对话 + 步骤时间线 │    │
│  │ ROI360   │  │              │  │              │  │  + 智能体大脑(Tabs)    │    │
│  │ 告警列表 │  │              │  │              │  │  + 主动自治面板        │    │
│  └────┬─────┘  └──────┬───────┘  └──────┬───────┘  └───────────┬──────────┘    │
│       └───────────────┴────────────────┴───────────────────────┘               │
│                                  │  /api/v1  (JWT + RBAC + 审计 + 多租户)         │
├──────────────────────────────────────────────────────────────────────────────┤
│  API Gateway (FastAPI)                                                         │
│  ┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────────────┐   │
│  │ auth     │ campaigns│ creatives│ data     │ connectors│ intent / llm    │   │
│  │ apps     │          │          │ alerts   │          │                  │   │
│  └──────────┴──────────┴──────────┴──────────┴──────────┴──────────────────┘   │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  🤖 agent_router (agentic 大脑入口)                                     │  │
│  │  /agent/sessions  /approve  /message  /reflect  /strategy  /autonomy   │  │
│  └───────────────────────────────┬────────────────────────────────────────┘  │
├──────────────────────────────────────┼───────────────────────────────────────┤
│  ╔════════════════ AGENT RUNTIME (大脑) ══════════════════════════════════╗  │
│  ║  session.py   多轮会话状态 + 内存仓库（目标/步骤/待审批/上下文）        ║  │
│  ║  tools.py     ToolRegistry（桥接层，9 工具带 L0–L3 风险元数据）         ║  │
│  ║  loop.py      AgentLoop：ReAct 循环（规则兜底 + LLM 规划 + 人在环）     ║  │
│  ║  memory.py    EpisodicMemory：每次写动作沉淀为 Episode（记忆燃料）      ║  │
│  ║  reflection.py Reflector：复盘 Episode → 启发式规则（Phase 2）          ║  │
│  ║  strategy.py  StrategyStore：记忆→可学习策略参数+落盘（Phase 3）        ║  │
│  ║  autonomy.py  AnomalyDetector + AutonomyEngine + APScheduler（Phase 4） ║  │
│  ╚════════════════════════════════════════════════════════════════════════╝  │
│       │                       │                         │                     │
│       │  AgentContext         │                         │                     │
│       ▼                       ▼                         ▼                     │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  ToolRegistry ：平台能力 ↔ Agent 的桥接（read/write + 风险元数据）    │   │
│  │  observe_campaigns / filter_campaigns / simulate_impact /             │   │
│  │  generate_report / pause_campaign / resume_campaign /                 │   │
│  │  adjust_budget / adjust_bid / rotate_creative                         │   │
│  └───────────────────────────────┬──────────────────────────────────────┘   │
├──────────────────────────────────────┼───────────────────────────────────────┤
│  Connectors (身体/护栏)                                                │       │
│  ┌─────────────────────────────────────────────────────────────────┐   │      │
│  │  BaseConnector（auth/pull/normalize/save_ods/save_dwd/apply_action）│  │      │
│  │  ├─ MockMediaConnector  ← 当前 agent_default_platform="mock"      │   │      │
│  │  │    背后 = SimulationEngine（有状态因果模拟，seed 可复现）       │   │      │
│  │  └─ MetaConnector / GoogleConnector / ...（Meta 恢复后切回）       │   │      │
│  │  ConnectorFactory：按 platform 名创建（"mock"/"meta"/...）         │   │      │
│  └─────────────────────────────────────────────────────────────────┘   │      │
├──────────────────────────────────────┼───────────────────────────────────────┤
│  Data Warehouse (四层)  ·  Auth/User/RBAC  ·  SQLite(开发)/PostgreSQL(生产)   │
│  ODS → DWD → DWS → ADS      ·  LLM Router（多模型 + 优雅降级）               │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心架构模块（v2 新增/变更）

### 3.1 Agent Runtime（大脑层）—— 全新模块

路径：`backend/app/services/agent_runtime/`

| 文件 | 职责 | 对应 Phase |
|------|------|-----------|
| `session.py` | `AgentSession` / `AgentStep` / `AgentStepKind` / `AgentStepStatus` / `AgentSessionStore`（进程内单例） | Phase 1 |
| `tools.py` | `ToolRegistry` + `AgentContext` + 9 个工具（读/写，带 L0–L3 风险）；`_write` 先算影响再真实 apply，并落审计 + 沉淀 Episode | Phase 1 |
| `loop.py` | `AgentLoop` ReAct 循环：`start` / `approve` / `send_message` / `reflect` / `learn_strategy`；规则引擎兜底 + LLM 规划；L1/L2 转人在环 | Phase 1 |
| `memory.py` | `Episode` + `EpisodicMemory`（进程内单例、跨会话持久）；`suggest_budget_increase_cap()` 反哺规划 | Phase 2 |
| `reflection.py` | `Reflector.reflect()` 把记忆复盘为「摘要 + 启发式规则」 | Phase 2 |
| `strategy.py` | `StrategyStore`/`StrategyRule`：记忆→可学习策略参数（`budget_increase_cap` / `pause_roi_threshold` / `rotate_when_roi_below`）+ JSON 落盘 | Phase 3 |
| `autonomy.py` | `AnomalyDetector` + `AutonomyEngine.scan()` + `AutonomyStore`（告警流/冷却去重）+ APScheduler 调度 | Phase 4 |

**Agent Loop 主循环（ReAct）**：
```
start(goal) → observe → think/decide →
   ├─ read 工具      → 执行并观察
   ├─ write L0 工具  → 自动执行
   ├─ write L1/L2/L3 → 生成审批步骤(awaiting_approval) → 等待人
   └─ final          → 终态
approve(step) → 批准→续跑 / 驳回→重新规划（记录被驳动作避免重复提议）
```

**决策来源（与 LLM 解耦一致）**：
- 有可用 LLM 且 `agent_use_llm_planning=true`：把工具清单 + 上下文喂给 `LLMRouter`，解析其返回的 ReAct JSON（`{"action","params"}` 或 `{"final_answer"}`），Agent 只「提议」不替人审批。
- 无 LLM / 降级：确定性规则规划器（`_rule_based_decide`）按关键词把目标拆成多步（暂停低 ROI / 给高 ROI 加预算 / 换素材 / 报告），行为一致、不报错。

### 3.2 Tool Registry（桥接层）

每个工具声明：`name` / `description` / `risk_level`(L0–L3) / `side_effect`(read|write) / `params_hint` / `handler`。

| 工具 | 风险 | 副作用 | 说明 |
|------|------|--------|------|
| `observe_campaigns` | L0 | read | 读取账户最新指标概览 |
| `filter_campaigns` | L0 | read | 按 ROI/国家/状态筛选 |
| `simulate_impact` | L0 | read | 预测某动作未来 N 天的 ΔROI/ΔSpend |
| `generate_report` | L0 | read | 账户诊断报告 |
| `pause_campaign` | L1 | write | 暂停 campaign（止损） |
| `resume_campaign` | L1 | write | 恢复 campaign |
| `adjust_budget` | L1 | write | 调整日预算 |
| `adjust_bid` | L2 | write | 调整 AdSet 出价倍率 |
| `rotate_creative` | L0 | write | 轮换素材（重置疲劳，短期提 CTR） |

**安全护栏天然生效**：Agent 不直连媒体，只通过 ToolRegistry 调用 → 风险分级、审计、多租户天然生效。写动作经 `BaseConnector.apply_action` 分发到具体连接器（与连接器解耦）。

### 3.3 Connectors（身体/护栏）—— v2 关键变更

- 新增 **`MockMediaConnector`**（注册为 `"mock"` 渠道）：背后是**有状态因果模拟引擎** `SimulationEngine`，写操作真实修改 campaign 状态、pull 历史反映动作效果 → 形成 动作→指标 的因果闭环（替代 v1 的无状态随机 mock）。当前 `config.agent_default_platform="mock"`（因 Meta 账户被封，作为数据土壤）。
- `BaseConnector.apply_action(action, entity_id, **params)` 通用写动作分发器：Agent 的写工具统一调用它，Meta 恢复后只需在工厂把 `"mock"` 换回 `"meta"`，上层零改动。
- `MockMediaConnector.live_summary()`：基于**实时状态**（而非历史快照）的账户概览，使 Agent 动作后立即看到最新状态（如暂停后该 campaign 立即显示 PAUSED、spend=0），避免基于过期快照重复提议。
- `simulate_impact()` / `simulate_action_impact()`：克隆引擎并施加动作，返回 控制 vs 处理 的每日对比，是「记忆/反思」闭环的核心原料。
- `account_status` 单例字段：主动自治检测器据此判断是否被封/受限（Meta appeal 等）。

### 3.4 主动自治（Phase 4）—— APScheduler 周期巡检

- `AnomalyDetector.detect()`：从实时账户状态检测 5 类异常——**CPI 飙升 / ROI 跌破阈值 / 素材疲劳 / 花费异常 / 账户被封**。ROI 跌破阈值优先采用 Phase 3 已学策略 `pause_roi_threshold`，回退默认 1.0。
- `AutonomyEngine.scan()`：检测→分级处置。L0（换素材）**自动执行**；L1/L2（暂停/调预算）生成「主动提案」进入人在环审批队列（复用 AgentSession/Step 审批流）；仅通知类（花费异常、账户被封）**不自动改动**——主动≠失控。
- `AutonomyStore`：进程内告警流 + 扫描历史；同 (异常类型, campaign) 冷却去重（`agent_autonomy_cooldown_scans`）避免重复打扰。
- `main.py` 用 `lifespan` 在启动时拉起 / 关闭 APScheduler（`agent_autonomy_enabled` / `agent_autonomy_interval_seconds`）。

---

## 4. 四层运营实体模型（沿用 v1）

Campaign → AdGroup → Ad → Creative 四层结构不变（详见 v1 `ARCHITECTURE.md`）。Agent 的写动作最终映射到 campaign 级别的 `pause / budget / bid / rotate`，尚未下钻到 AdGroup/Ad 颗粒（v2.0 增强方向）。

标准状态流：`draft → approved → api_submitted → running → paused → ended`（与 v1 一致）。

---

## 5. 前端架构（v2 新增「智能体控制台」）

路由（`App.jsx`）新增 `/agent`，侧边栏（`MainLayout.jsx`）新增「智能体控制台」入口（RobotOutlined）。

`frontend/src/pages/AgentConsole.jsx` 布局：
- **左：对话区**——输入目标 → 步骤时间线（💭推理 / 👁观察 / ✅已执行 / ⏳待审批 / 🏁结论）；L1/L2 动作内联审批（批准→续跑 / 驳回→重新规划）；多轮追问输入框。
- **右：智能体大脑（Tabs）**——
  - `🧠 智能体大脑`：已学策略（GET `/agent/strategy`）、经验复盘（POST `/agent/reflect`）、「学习策略」「重置策略」按钮。
  - `🛡 主动自治`：监控状态（开/关 + 最近扫描 + 待审批数）、立即巡检、启停调度、告警流（待审批内联批准/驳回、查看关联会话）。
- 数据封装：`frontend/src/api.js` 的 `agentAPI`（覆盖 `/agent/*` 全部端点）。

---

## 6. 后端 API 架构（v2 新增 agent 路由）

FastAPI 路由分层不变（auth/apps/data/intent/llm/connectors/campaign）。**新增** `agent_router`（`prefix=/agent`）：
- 会话：`POST /agent/sessions`、`GET /agent/sessions`、`GET /agent/sessions/{id}`、`POST /agent/sessions/{id}/approve`、`POST /agent/sessions/{id}/message`
- 反思：`POST /agent/reflect`、`POST /agent/sessions/{id}/reflect`
- 策略：`POST /agent/strategy/learn`、`GET /agent/strategy`、`POST /agent/strategy/reset`
- 主动自治：`GET /agent/autonomy/status`、`GET /agent/autonomy/alerts`、`POST /agent/autonomy/scan`、`POST /agent/autonomy/toggle`

数据库初始化、四层数仓、RBAC、数值安全渲染等沿用 v1（详见 `API_REFERENCE_v2.md` / `CHANGELOG.md`）。

---

## 7. 技术栈（v2 变更）

| 层级 | 技术选型 | 状态 | 变更 |
|------|---------|------|------|
| 前端 | React 18 + Vite 5 + Ant Design 5 + ECharts 5 + Axios | ✅ | — |
| 后端 | FastAPI + SQLAlchemy 2.0 + Pydantic 2.0 | ✅ | — |
| 数据库 | SQLite（开发）/ PostgreSQL（生产） | ✅ | — |
| 调度 | **APScheduler** | ✅ 新增 | Phase 4 主动巡检 |
| 认证 | JWT + Passlib | ✅ | — |
| 大模型 | Claude / GPT-4o / DeepSeek / 本地模型（多模型路由 + 优雅降级） | ✅ | Agent Loop 可选 LLM 规划 |
| 模拟引擎 | `SimulationEngine`（有状态因果，seed 可复现） | ✅ 新增 | Phase 0 数据土壤 |

---

## 8. 多租户与权限模型（沿用 v1）

RBAC（admin / optimizer / analyst / finance）+ 用户-App 绑定 + 菜单/操作/数据/字段权限粒度不变。Agent 端点均要求 JWT（`get_current_user` 依赖）。

---

## 9. 当前版本历史（对齐 Agentic 升级）

| 版本 | 日期 | 说明 |
|------|------|------|
| **v1.6.0** | 2026-07-10 | **Phase 4 主动式自治**：APScheduler 周期巡检 + 5 类异常分级处置 + 人在环审批队列 |
| v1.5.0 | 2026-07-10 | 前端「智能体控制台」对接（多轮对话/审批/记忆/策略/复盘） |
| v1.4.0 | 2026-07-10 | Phase 3 策略自演化（StrategyStore 落盘、跨账户迁移） |
| v1.3.0 | 2026-07-10 | Phase 2 记忆与反思（Episodic Memory + Reflection） |
| v1.2.0 | 2026-07-10 | Phase 1 Agent Loop（规划 + ReAct + 多轮 + 人在环） |
| v1.1.0 | 2026-07-10 | Phase 0 Mock 因果模拟引擎 + `mock` 渠道 |
| v1.0.0 | 2026-06-28 | 初体验版本（大盘/详情/素材/告警/认证/CRUD） |

> v1 原版 `ARCHITECTURE.md` 完整保留，记录升级前的「对话式意图驱动控制台」形态，作为演进对照。

---

## 10. 已知风险与 v2.0 远期增强

- **进程内单例重启即失**：AgentSession 仓、EpisodicMemory、AutonomyStore 告警流目前均为进程内单例；生产需落库（会话表 / `EpisodicMemory` 表 / 告警表），与 `ActionLog` 互为补充。
- **策略参数为标量阈值学习**：Phase 3 已交付「可学习策略参数」核心；原规划的「策略 A/B / 元学习优化提示词 / 四层数仓特征」仍为增强方向。
- **真实媒体未接**：当前 `mock` 为确定性模拟，不消耗真实预算；Meta 恢复后改 `config.agent_default_platform="meta"` 即切回真实 Connector，上层零改动。
- **主动汇报升级**：日报 / 异动摘要推送（邮件 / 企微 / 飞书）待做。

---

*文档版本：v2 | 基于 2026-07-10 SmartUA v1.6.0 实际代码 | 配套 `API_REFERENCE_v2.md` / `CONNECTOR_DESIGN_v2.md` / `LLM_ROUTING_v2.md` / `USER_MANUAL_v2.md` / `RELATED_PROJECTS_v2.md`*
