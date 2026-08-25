# SmartUA API 参考文档（v3）

> **版本说明**：本文档为 v3，基于 SmartUA **v1.8.x（2026-07-22）** 的实际代码。v2
> （`API_REFERENCE_v2.md`）交付了 `/agent/*` Phase 1~4 端点；v3 在其之上**保持向下
> 兼容**契约，并新增：
> - AgentSession / Step 携带 `execution_mode` / `account_id` / `verified_at` 全链路可见。
> - Step (write) `dispatch: {state, action_id, observation}` 状态机可见。
> - Action 详情三份 envelope（`predicted / observed / attributed`）独立字段。
> - `stream-ticket`（SSE 短票据）、`actions/reconcile`（对账）、`impact/collect`（回采）三个新端点。
> - `agent/strategy/learn` 门禁化返回体。
>
> v1（`API_REFERENCE.md`）、v2（`API_REFERENCE_v2.md`）保留，作为演进对照。
>
> 文档路径：`docs/API_REFERENCE_v3.md`

---

## 目录

- [核心概念（v3 增量）](#核心概念v3-增量)
- [认证](#认证)
- [SSE 一次性票据（Phase 2.2 新增）](#sse-一次性票据phase-22-新增)
- [🤖 Agent 端点（v3 变更点）](#-agent-端点v3-变更点)
  - [会话与多轮](#会话与多轮)
  - [动作对账（Phase 3.3 新增）](#动作对账phase-33-新增)
  - [延迟回采（Phase 4.2 新增）](#延迟回采phase-42-新增)
  - [策略学习门禁（Phase 4.3 变更）](#策略学习门禁phase-43-变更)
- [数据结构（v3 补充字段）](#数据结构v3-补充字段)
- [其他端点（沿用 v1 / v2）](#其他端点沿用-v1--v2)
- [错误码](#错误码)

---

## 核心概念（v3 增量）

### execution_mode 全链路可见
所有 `/agent/*` 端点返回的 Session / Step / Alert / Action / Strategy 结果都包含
`execution_mode ∈ {mock, sandbox, live}` 字段。前端凭此持续显示徽标。**混淆 Mock / live
的行为在 v3 明确否决**。

### 幂等键（Phase 3.1）
每个真实写动作有 `idempotency_key = hash(session_id, step_id, tool, params_digest)`；
相同键并发提交只生成一条 AgentActionDB，媒体只调用一次。

### 三类影响
- `predicted_impact`：动作瞬间的模型预测（写完即有）。
- `observed_impact`：媒体报表回采（Phase 4.2，2h/24h/7d 到点写回）。
- `attributed_impact`：MMP 归因回采（同上）。
- 未采到时保持 **`null`**；采到但事实数据为零 → `completeness=0.0`。**禁止用 0 冒充**。

### 学习门禁（Phase 4.3）
`POST /agent/strategy/learn` 只学 `usable_for_learning=True` 的 Episode（live + observed/attributed + completeness>0）。仅有 mock/predicted 时 rules 不变、note 明确说明。

### 状态机（Phase 3.3）
`AgentActionDB` 走 `proposed → approved → dispatching → accepted → verified | failed | unknown`。Step (write) 结果里的 `dispatch.state` 与 `dispatch.observation` 就是这套状态机的暴露面。

---

## 认证

所有 API 需 `Authorization: Bearer <access_token>`。基础 URL：`http://localhost:8000/api/v1`。

```http
POST /auth/login
{ "email": "admin@smartua.com", "password": "admin123" }
→ { "access_token": "...", "token_type": "bearer", "expires_at": "..." }
```

> 演示账号沿用 v2。所有 `/agent/*` 端点均要求 JWT，且 v3 增加**对象级授权**（Phase 2.1）：
> 用户对无权访问的 session / action / alert 一律返回 **404**（不返回 403，避免对象枚举）。

---

## SSE 一次性票据（Phase 2.2 新增）

**背景**：v2 的 SSE 使用 `?token=<jwt>` 携带长期 JWT，会进入 URL / 代理日志 / 浏览器历史。
v3 明确禁止长期 JWT 出现在 URL。

### 申请短票据

```http
POST /agent/sessions/{session_id}/stream-ticket
Authorization: Bearer <access_token>

→ {
  "ticket": "st_abcdef1234...",
  "expires_at": "2026-07-22T12:34:56+00:00",
  "ttl_seconds": 60,
  "session_id": "ff00aabbcc12"
}
```

- 票据**短期**（默认 60s，`agent_sse_short_ticket_ttl_seconds` 可配）、**单次**、**绑定 session/user**。
- 使用一次或过期后自动失效；跨 session 使用直接拒绝。

### 使用短票据订阅 SSE

```http
GET /agent/sessions/{session_id}/stream?ticket=st_abcdef1234...
Accept: text/event-stream
```

- 也支持 `Authorization: Bearer <access_token>` 直连（服务器信任 JWT）。
- 兼容开关 `agent_sse_allow_legacy_query_token`（默认 `false`）：设置为 true 时允许 `?token=<jwt>` 作为迁移过渡；生产 **必须关闭**。

响应头：`Referrer-Policy: no-referrer`（防止 SSE URL 通过 referer 泄露）。

---

## 🤖 Agent 端点（v3 变更点）

### 会话与多轮

#### 创建会话
```http
POST /agent/sessions
{ "text": "...", "app_id": 1 }
```
返回 AgentSession（新增字段见 [数据结构](#数据结构v3-补充字段)）。

#### 查看 / 列出 / 消息 / 审批
沿用 v2 契约。审批（`POST /agent/sessions/{id}/approve`）在 v3 增加两条校验：

1. **审批过期**（Phase 3.2）：若 `expires_at` 已过，返回 `409 Conflict` + `{"error": "approval_expired", "expires_at": "..."}`。
2. **状态漂移**：审批瞬间重读实体状态与预算；漂移超过阈值时返回 `409 Conflict` + `{"error": "state_drifted", "drift": {...}}`，前端需重新提案。

批准后：Agent 通过 Dispatcher 派发；Step (write) 的 `data` 追加：

```json
"dispatch": {
  "state": "verified",
  "action_id": "act_ab12cd34...",
  "observation": {"status": "PAUSED", "daily_budget": 0}
}
```

### 动作对账（Phase 3.3 新增）

**用途**：把 `unknown` 状态的动作收敛为 `verified / failed`；默认关闭，需 admin。

```http
POST /agent/actions/reconcile
{ "app_id": 1, "max_actions": 200 }

→ {
  "scanned": 12,
  "verified": 4,
  "failed": 1,
  "still_unknown": 7
}
```

- `still_unknown > 0` 表示 read_state 仍无法定夺；建议下次继续调用直到收敛。
- 调用者必须持有 `admin` 或 `optimizer` 角色 + 对应 app_id 授权。

### 延迟回采（Phase 4.2 新增）

**用途**：触发一次 `run_due_jobs`，把 2h/24h/7d 到点的 impact job 从事实表回采。默认关闭，
需 admin。

```http
POST /agent/impact/collect
{ "app_id": 1, "limit": 200 }

→ {
  "done": 4,     // 事实表有数据
  "empty": 2,    // 事实表 0 行，envelope 落 completeness=0.0
  "failed": 0
}
```

- 生产：由外部调度器（APScheduler / cron）周期调用，无需手动触发。
- 幂等：done 状态的 job 不会二次处理。

### 策略学习门禁（Phase 4.3 变更）

```http
POST /agent/strategy/learn
→ {
  "learned_keys": ["budget_increase_cap", "pause_roi_threshold"],
  "note": "[usable=6 条真实样本] 加预算 6 次，7d 平均ΔROI<0，增幅收敛至 10%；暂停 3 次成功止血，最高 ROI=0.85",
  "rules": { ... }
}
```

**无 usable 真实样本时**（仅 mock / predicted-only）：

```http
→ {
  "learned_keys": [],
  "note": "无可用真实样本：仅有 Mock/Sandbox 或 predicted-only Episode，策略保持不变.",
  "rules": { /* 保持上一次真实学到的规则不变 */ }
}
```

- `rules` **不会**被清空，也不会回归到硬编码默认。
- 前端应用 note 前缀 `[usable=N 条真实样本]` 判定是否发生了真实学习。

`GET /agent/strategy` / `POST /agent/strategy/reset` 沿用 v2 契约。

---

## 数据结构（v3 补充字段）

### AgentSession
```json
{
  "id": "ff00aabbcc12",
  "app_id": 1,
  "user_id": 3,
  "goal": "...",
  "status": "awaiting_approval",
  "execution_mode": "mock",          // v3 新增
  "platform": "mock",                // v3 新增
  "account_id": "acct_mock_1",       // v3 新增
  "steps": [ /* AgentStep[] */ ],
  "context": { ... },
  "created_at": "2026-07-22T09:00:00+00:00",
  "updated_at": "2026-07-22T09:01:00+00:00"
}
```

### AgentStep
```json
{
  "id": "a1b2c3d4",
  "kind": "action",                     // thought / observation / action / approval / final
  "text": "已暂停 camp_ca_003",
  "tool": "pause_campaign",
  "params": {"entity_id": "camp_ca_003"},
  "risk_level": "L1",
  "execution_mode": "mock",             // v3 新增
  "account_id": "acct_mock_1",          // v3 新增
  "expires_at": "2026-07-22T09:15:00+00:00",  // v3 新增（仅 approval kind）
  "predicted_impact": {                 // v3：明确 kind=predicted 的 envelope
    "kind": "predicted",
    "metrics": {"delta_roi": 0.0, "delta_spend": -100.0},
    "window": "24h",
    "completeness": 1.0,
    "source": "simulate_impact/mock"
  },
  "status": "executed",
  "result": {
    "result": {...},
    "impact": {
      "impact_2h":  { "kind": "predicted", "metrics": {...}, "completeness": 1.0, "source": "simulate_impact/mock" },
      "impact_24h": { "kind": "predicted", "metrics": {...}, "completeness": 1.0, "source": "simulate_impact/mock" },
      "impact_7d":  { "kind": "predicted", "metrics": {...}, "completeness": 1.0, "source": "simulate_impact/mock" }
    }
  },
  "dispatch": {                         // v3 新增（Phase 3.3）
    "state": "verified",
    "action_id": "act_ab12cd34...",
    "observation": {"status": "PAUSED", "daily_budget": 0},
    "verified_at": "2026-07-22T09:02:15+00:00"
  },
  "created_at": "2026-07-22T09:02:00+00:00"
}
```

### AgentActionDB（暴露给管理端点 / 详情视图）
```json
{
  "id": "act_ab12cd34...",
  "idempotency_key": "ik_...",
  "session_id": "ff00aabbcc12",
  "step_id": "a1b2c3d4",
  "app_id": 1,
  "user_id": 3,
  "account_id": "acct_mock_1",
  "entity_id": "camp_ca_003",
  "platform": "mock",
  "tool": "pause_campaign",
  "action": "update_campaign_status",
  "risk_level": "L1",
  "execution_mode": "mock",
  "state": "verified",
  "predicted_impact": {  "kind": "predicted",  ... },
  "observed_impact":   {  "kind": "observed",   ... } | null,
  "attributed_impact": {  "kind": "attributed", ... } | null,
  "read_state_snapshot": {"status": "PAUSED", "daily_budget": 0},
  "provider_request_id": "sim_call_42",
  "expires_at": "2026-07-22T09:15:00+00:00",
  "proposed_at":   "2026-07-22T09:01:50+00:00",
  "approved_at":   "2026-07-22T09:02:00+00:00",
  "dispatched_at": "2026-07-22T09:02:05+00:00",
  "accepted_at":   "2026-07-22T09:02:10+00:00",
  "verified_at":   "2026-07-22T09:02:15+00:00",
  "failed_at": null,
  "error": null,
  "retry_count": 0,
  "intent_execution_id": 15,
  "action_log_id": 42
}
```

### ImpactEnvelope（用于 predicted / observed / attributed）
```json
{
  "kind": "observed",              // predicted | observed | attributed
  "metrics": {
    "delta_spend": 12.3,
    "delta_impressions": 4200,
    "delta_clicks": 84,
    "delta_installs": 3.5,
    "delta_cpi": -0.02,
    "delta_ctr": 0.001
  },
  "window": "24h",                 // 2h | 24h | 7d
  "time_zone": "UTC",
  "currency": "USD",
  "source": "fact_media_daily",    // simulate_impact/mock | fact_media_daily | appsflyer_mmp | ...
  "freshness": "2026-07-22T11:00:00+00:00",
  "completeness": 1.0              // null=未采到 | 0.0=采到但事实数据零 | (0,1]=部分/完整
}
```

**核心不变量**：
- `completeness = null` 表示"未采到"。
- `completeness = 0.0` 表示"采到了但事实数据为零"。
- 消费方（策略学习 / 复盘）**必须**区分这两种情况；禁止用 0 冒充没观察到。

### AutonomyAlert
沿用 v2；`anomaly` payload 额外携带 `execution_mode` 与 `account_id`；若处置生成动作，
`session_id / step_id` 关联的 Step 会带 `dispatch` 字段。

---

## 其他端点（沿用 v1 / v2）

- Campaign / Creative / 数据告警 / 连接器 / 意图引擎：全部沿用 v1（详见 `API_REFERENCE.md`）。
- Agent 反思 / 策略查看 / 主动自治 status/alerts/scan/toggle：沿用 v2（详见 `API_REFERENCE_v2.md`）。
- LLM 路由：`GET /api/v1/llm/status` / `POST /api/v1/llm/test-route`（详见 `LLM_ROUTING_v3.md`）。

---

## 错误码

| HTTP | 语义 | 出现场景 |
|------|------|---------|
| 401 | 未认证 | 缺少 / 无效 JWT |
| 404 | 不存在或无权访问（Phase 2.1）| 跨 app 访问 session / action / alert / strategy |
| 409 | 冲突 | `approval_expired` / `state_drifted` / 幂等键复用不同参数 |
| 422 | 参数错误 | schema 校验失败 |
| 500 | 服务端错误 | Connector fail-closed（缺凭证 live 请求）/ dispatcher 判定失败 |

---

## 更新日志

| 版本 | 日期 | 说明 |
|------|------|------|
| **v3** | 2026-07-22 | Phase 0.1 → 4.3：execution_mode 全链路 / 对象授权 / SSE 短票据 / 幂等状态机 / 三类影响 / 学习门禁 |
| v2 | 2026-07-10 | Agentic `/agent/*` 全套端点（会话/审批/多轮/反思/策略/主动自治） |
| v1.0 | 2026-06-28 | 原版 API 参考 |

---

*文档版本：v3 | 基于 2026-07-22 SmartUA v1.8.x 实际代码 | 配套 `ARCHITECTURE_v3.md` / `CONNECTOR_DESIGN_v3.md` / `LLM_ROUTING_v3.md` / `USER_MANUAL_v3.md` / `RELATED_PROJECTS_v3.md`*
