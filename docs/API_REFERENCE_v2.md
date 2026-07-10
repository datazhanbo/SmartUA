# SmartUA API 参考文档（v2）

> **版本说明**：本文档为 v2，基于 SmartUA **v1.6.0** 的实际代码，在原 `API_REFERENCE.md`
> 基础上**新增 Agentic `/agent/*` 全套端点**（Phase 1~4）。v1 原版 `API_REFERENCE.md` 保留，
> 记录升级前的 Campaign/Creative/Data/Intent 端点形态。
>
> 文档路径：`docs/API_REFERENCE_v2.md`

---

## 目录

- [核心概念速查](#核心概念速查)
- [认证](#认证)
- [Campaign API](#campaign-api)
- [Creative API](#creative-api)
- [数据与告警 API](#数据与告警-api)
- [连接器 API](#连接器-api)
- [意图引擎 API](#意图引擎-api)
- [🤖 Agent 对话式投放 API（v2 新增, Phase 1~4）](#-agent-对话式投放-apiv2-新增-phase-14)
  - [会话与多轮](#会话与多轮)
  - [反思端点（Phase 2）](#反思端点phase-2)
  - [策略自演化端点（Phase 3）](#策略自演化端点phase-3)
  - [主动自治端点（Phase 4）](#主动自治端点phase-4)
- [AgentSession / Step / Alert 数据结构](#agentsession--step--alert-数据结构)

---

## 核心概念速查

### 🔑 四层运营实体模型（沿用 v1）
```
Campaign (活动) → AdGroup (广告组) → Ad (广告) → Creative (素材)
```

### 📊 数值类型安全
> ⚠️ 所有数值字段（roi, spend, cpi, ctr…）JSON 序列化后为**字符串**。前端统一用
> `Number(val)` 转换后再渲染，禁止直接 `.toFixed()`（会 NaN 白屏）。

### 🛡️ 操作安全分级（L0–L3，贯穿 Agent 与意图引擎）
| 级别 | 说明 | 执行方式 |
|------|------|---------|
| **L0** | 只读/低风险写 | 自动执行 |
| **L1** | 微调（暂停/调预算） | 人在环审批（批准续跑 / 驳回重规划） |
| **L2** | 重大变更（调出价） | 必须审批，绝不自动 |
| **L3** | 建议类 | 仅生成建议，不执行 |

---

## 认证

所有 API 需 `Authorization: Bearer <access_token>`。基础 URL：`http://localhost:8000/api/v1`。

```http
POST /auth/login
{ "email": "admin@smartua.com", "password": "admin123" }
→ { "access_token": "...", "token_type": "bearer", "expires_at": "..." }
```

> 演示账号：`admin@smartua.com/admin123`、`optimizer1@smartua.com/optimizer123`、
> `analyst1@smartua.com/analyst123`、`finance@smartua.com/finance123`。
> **所有 `/agent/*` 端点均要求 JWT**（受 `get_current_user` 依赖保护）。

---

## Campaign API / Creative API / 数据与告警 API / 连接器 API / 意图引擎 API

> 以下端点与 v1 完全一致（路径、参数、响应均不变），本 v2 仅作索引，详见原 `API_REFERENCE.md`：

- **Campaign**：`GET /campaigns`、`GET /campaigns/{id}`（嵌套 AdGroup→Ad）、`GET /campaigns/{id}/adgroups`、`GET /adgroups/{id}/ads`
- **Creative**：`GET /creatives`、`GET /creatives/{id}`
- **数据/告警**：`GET /data/alerts?app_id=&severity=&status=`、`PUT /data/alerts/{id}/resolve`、`GET /data/dashboard`、`GET /data/campaign-health`
- **连接器**：`GET /connectors/`、`POST /connectors/credentials`、`POST /connectors/pull`、`POST /connectors/sync/dws`、`GET /connectors/runs`
- **意图引擎**：`POST /intent/execute`（单轮「解析→弹窗→执行」遗留流程，保留并存）

---

## 🤖 Agent 对话式投放 API（v2 新增, Phase 1~4）

> 前缀：`/api/v1/agent`。全部需要 JWT。核心类型见文末[数据结构](#agentsession--step--alert-数据结构)。

### 会话与多轮

#### 创建会话并启动 ReAct 循环
```http
POST /agent/sessions
{ "text": "暂停 ROI 低于 0.5 的 campaign，给 ROI 最高的加预算 20%，并轮换表现最差的素材", "app_id": 1 }
```
- 启动后 Agent 自动观察账户 → 规划多步 → 遇到 L1/L2 动作停在 `awaiting_approval`。
- 返回完整 `AgentSession`（含 `steps` 时间线）。`status` 为 `running` 或 `awaiting_approval`。

#### 列出本 app 会话
```http
GET /agent/sessions?app_id=1
→ [ AgentSession, ... ]
```

#### 查看会话详情
```http
GET /agent/sessions/{session_id}
→ AgentSession   # 含 goal / steps / status / context
```

#### 人在环审批（批准→续跑 / 驳回→重规划）
```http
POST /agent/sessions/{session_id}/approve
{ "step_id": "a1b2c3d4", "approved": true, "reason": "同意止损" }
```
- 仅能审批 `kind=approval` 且 `status=proposed` 的步骤。
- 批准且为写工具 → 真实执行并续跑循环；驳回 → 记录被驳动作避免反复提议，重新规划。
- 若该会话由**主动自治**生成，审批会回写关联告警状态（前端告警流随之更新）。

#### 多轮追问 / 追加指令
```http
POST /agent/sessions/{session_id}/message
{ "text": "把刚才加预算的幅度收敛到 10%" }
→ AgentSession   # 追加指令后续跑循环
```

### 反思端点（Phase 2）

#### 全局复盘（基于已沉淀 Episode 记忆）
```http
POST /agent/reflect
→ {
  "summary": "近期共 6 次写动作…止损成功 3 次…",
  "rules": ["ROI<1.0 的 campaign 暂停可止血", "加预算边际递减，增幅应≤10%", "换素材短期提升 CTR", "提价伤 ROI"],
  "episodes_count": 6
}
```
> 前置：`agent_reflection_enabled=true`，否则返回 `503`。

#### 按会话复盘
```http
POST /agent/sessions/{session_id}/reflect
→ { "summary": "...", "rules": [...], "episodes_count": N }
```

### 策略自演化端点（Phase 3）

#### 学习策略（记忆 → 可复用参数 + 落盘）
```http
POST /agent/strategy/learn
→ {
  "learned_keys": ["budget_increase_cap", "pause_roi_threshold"],
  "note": "加预算 6 次，7d 平均ΔROI<0，增幅收敛至 10%；暂停 3 次成功止血，最高 ROI=0.85",
  "rules": {
    "budget_increase_cap":  { "key":"budget_increase_cap", "value":10.0, "confidence":0.6, "n_samples":6, "source":"learned:adjust_budget" },
    "pause_roi_threshold":  { "key":"pause_roi_threshold", "value":0.85, "confidence":0.6, "n_samples":3, "source":"learned:pause_campaign" }
  }
}
```
> 落盘路径：`config.agent_strategy_path`（默认 `backend/data/strategy.json`）。

#### 查看已学策略
```http
GET /agent/strategy
→ { "strategy_path": ".../strategy.json", "rules": { "budget_increase_cap": {...}, ... } }
```
- 规划器（`loop._rule_based_decide`）预算增幅与暂停阈值**优先咨询策略层**，回退记忆收敛，再回退硬编码默认。

#### 重置策略
```http
POST /agent/strategy/reset
→ { "ok": true, "detail": "策略已重置为硬编码默认值" }
```

### 主动自治端点（Phase 4）

#### 主动自治状态
```http
GET /agent/autonomy/status
→ {
  "enabled": true,
  "interval_seconds": 120,
  "last_scan_at": "2026-07-10T21:00:00+00:00",
  "alerts_total": 12,
  "pending": 2,
  "platform": "mock",
  "monitor_app_ids": [1]
}
```

#### 主动自治告警流
```http
GET /agent/autonomy/alerts?app_id=1
→ [
  {
    "id": "a1b2c3d4e5",
    "detected_at": "2026-07-10T21:00:00+00:00",
    "app_id": 1,
    "anomaly": {
      "id": "...", "type": "roi_drop", "title": "camp_ca_003 ROI=0.60 跌破 0.85",
      "severity": "critical", "detail": "ROI 已低于止损阈值 0.85（使用已学策略阈值）",
      "metrics": {"roi": 0.6, "threshold": 0.85, "cpi": 5.2},
      "suggested_tool": "pause_campaign", "suggested_risk": "L1", "rationale": "低 ROI 持续烧钱，暂停止损"
    },
    "status": "pending_approval",   // auto_executed / pending_approval / no_action / approved / rejected
    "session_id": "ff00...", "step_id": "aa11...", "resolution": "等待优化师审批"
  },
  ...
]
```

#### 手动触发一次巡检
```http
POST /agent/autonomy/scan?app_id=1
→ {
  "scanned": true,
  "alerts": [ ... ],
  "summary": { "auto_executed": 1, "pending_approval": 2, "no_action": 1 }
}
```
- 等价于调度器的一次执行；便于演示/测试。L0 异常（如素材疲劳）会**自动执行**换素材。

#### 启停主动自治调度（APScheduler）
```http
POST /agent/autonomy/toggle?enabled=true
→ { "enabled": true, "detail": "主动自治调度已开启" }
```
- 关闭后不再周期巡检，但 `POST /agent/autonomy/scan` 仍可手动触发。

---

## AgentSession / Step / Alert 数据结构

### AgentSession
```json
{
  "id": "ff00aabbcc12",
  "app_id": 1,
  "user_id": 3,
  "goal": "暂停 ROI 低于 0.5 的 campaign…",
  "status": "awaiting_approval",   // running / awaiting_approval / done / failed
  "steps": [ /* AgentStep[] */ ],
  "context": { "summary": [...], "done": [...], "rejected": [...] },
  "created_at": "2026-07-10T20:00:00+00:00",
  "updated_at": "2026-07-10T20:01:00+00:00"
}
```

### AgentStep
```json
{
  "id": "a1b2c3d4",
  "kind": "approval",            // thought / observation / action / approval / final
  "text": "提议暂停 camp_ca_003（止损，L1 需确认）",
  "tool": "pause_campaign",
  "params": {"entity_id": "camp_ca_003"},
  "risk_level": "L1",
  "predicted_impact": {          // 来自 simulate_impact 的对照预测（审批前可见）
    "action": "update_campaign_status",
    "entity_id": "camp_ca_003",
    "delta_roi_first": 0.0,
    "delta_roi_avg7": 0.0,
    "delta_spend_first": 0.0
  },
  "status": "proposed",          // proposed / approved / rejected / executed / failed / done
  "result": { "result": {...}, "impact": { "impact_2h": {...}, "impact_24h": {...}, "impact_7d": {...} } },
  "created_at": "2026-07-10T20:00:30+00:00"
}
```

### AutonomyAlert（见上「告警流」示例）

---

## 常见问题（FAQ，补充 v2）

### Q: `/agent` 和 `/intent` 有什么区别？
A: `/intent/execute` 是 v1 单轮「解析→弹窗→执行」遗留流程；`/agent/*` 是 v2 目标驱动的
多轮 Agent Loop（会规划、会观察后再决策、会回采影响、高风险走人在环）。两者并存。

### Q: Agent 端点为什么返回 401？
A: 所有 `/agent/*` 均要求 JWT。请先 `POST /auth/login` 拿到 token 并在 Header 携带。

### Q: 为什么数值是字符串？
A: 与 v1 一致，SQLAlchemy `DECIMAL` 序列化为字符串避免精度丢失；`mock` 引擎返回的指标
同理，前端用 `Number()` 转换。

### Q: 主动自治为什么默认 120 秒巡检一次？
A: 仅用于开发/演示。生产建议 `agent_autonomy_interval_seconds ≥ 300`（5 分钟），且 L1/L2
动作绝不自动执行，仅推给你审批；L0 仅用于低风险换素材。

---

## 更新日志

| 版本 | 日期 | 说明 |
|------|------|------|
| **v2** | 2026-07-10 | 新增 Agentic `/agent/*` 全套端点（会话/审批/多轮/反思/策略/主动自治）+ 数据结构说明 |
| v1.0 | 2026-06-28 | 原版 API 参考（Campaign/Creative/数据告警/连接器/意图） |

---

*文档版本：v2 | 基于 2026-07-10 SmartUA v1.6.0 | 配套 `ARCHITECTURE_v2.md` / `CONNECTOR_DESIGN_v2.md` / `LLM_ROUTING_v2.md` / `USER_MANUAL_v2.md` / `RELATED_PROJECTS_v2.md`*
