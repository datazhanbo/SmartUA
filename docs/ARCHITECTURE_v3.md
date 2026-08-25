# SmartUA 系统架构设计文档（v3）

> **版本说明**：本文档为 v3，基于 SmartUA **v1.8.x（2026-07-22）** 的实际代码重写，反映
> 生产升级路线 **Phase 0.1 → 4.3** 完整落地后的系统状态：真实/模拟严格隔离、对象授权、
> 动作实体与状态机（幂等 + 回读 + 对账）、三类影响拆分、延迟回采、Episode 学习门禁。
> v1（`ARCHITECTURE.md`）、v2（`ARCHITECTURE_v2.md`）保留，作为演进对照，本文档不覆盖它们。
>
> 文档路径：`docs/ARCHITECTURE_v3.md`
>
> 配套：`API_REFERENCE_v3.md` / `CONNECTOR_DESIGN_v3.md` / `LLM_ROUTING_v3.md` /
> `USER_MANUAL_v3.md` / `RELATED_PROJECTS_v3.md`。

---

## 1. 定位变化：从「可运行」到「可托付真实预算」

v2 交付的是「Agentic 投放平台」的**可运行原型**：Agent Loop、记忆、策略、主动自治、Mock
因果模拟。v3 的目标不是新增大能力，而是把"可运行"的每一个环节收敛到"可托付真实预算"的
强度：

- 真实 / 模拟严格隔离 —— 永远不把 Mock 结果冒充 live 成功。
- 每个写动作都有唯一实体、幂等键、显式状态机、回读与对账。
- 影响分三类记录（predicted / observed / attributed），事实回采后才纳入策略学习。
- 策略只学**真实 usable 样本**，Mock/predicted 永远无法改动生产规则。
- 对象级授权（app_id 边界）、SSE 短票据认证、schema 版本受 Alembic 管理。

v3 阶段既不接生产多媒体真实凭证，也不上 durable worker（Phase 5.x）—— 这些留给 v1.9/v2.0。
但 v3 之后系统已具备"接入真实凭证即可承担生产责任"的**结构**。

---

## 2. Agent Runtime 布局（v3 新增/变更）

路径：`backend/app/services/agent_runtime/`（v3 新增文件加粗）：

| 文件 | 职责 | 变更 |
|------|------|------|
| `session.py` | AgentSession / Step / Store；response schema 携带 `execution_mode` / `account_id` / `verified_at` | v3 变更 |
| `tools.py` | ToolRegistry + 9 工具；`_write` 现在通过 dispatcher 派发；Episode 记录时带 `execution_mode` / `data_quality` / `usable_for_learning=False` | v3 变更 |
| `loop.py` | AgentLoop ReAct 循环；写工具改走 `_dispatch_via_action_store` 交 dispatcher；`_link_episode_to_action` 把 Episode 与 AgentActionDB 软链 | v3 变更 |
| `memory.py` | Episode dataclass；`usable_episodes()` / `promote_usable_for_learning()` 门禁入口；`impact_kind(window)` 判定 | v3 变更 |
| `reflection.py` | Reflector 摘要（v3 未变；仍读全集 Episode，供 UI 复盘） | 未变 |
| `strategy.py` | StrategyStore；`learn_from_memory` 只读 usable Episode，无样本时**不动 `_rules`** | v3 变更 |
| `autonomy.py` | AnomalyDetector + AutonomyEngine + APScheduler；处置结果也走 dispatcher | v3 变更 |
| **`action_store.py`** | AgentActionDB 幂等键计算 + `mint_or_get` + 状态跳转校验 | Phase 3.1 新增 |
| **`dispatcher.py`** | `Dispatcher.dispatch_and_verify()` / `reconcile()` / `_verify_state` / verified 后 `_enqueue_impact_jobs` | Phase 3.3 + 4.2 新增 |
| **`impact.py`** | ImpactEnvelope + `make_predicted / make_observed / make_attributed` + `metric()` 安全取值 | Phase 4.1 新增 |
| **`impact_collector.py`** | `enqueue_after_verified` / `run_due_jobs`；6 条 job（observed × 3 + attributed × 3）；`_promote_episode` 门禁提权 | Phase 4.2 + 4.3 新增 |

**Agent Loop 一次写动作的完整链路（v3）**：

```
observe → decide (LLM 或规则规划器)
   └─ write L0/L1/L2 → 生成审批步骤 → 人审批（L1/L2）
       └─ approve → _execute_approved_write
              └─ _dispatch_via_action_store
                     └─ Dispatcher.dispatch_and_verify
                            ├─ mint_or_get (幂等键) → AgentActionDB
                            ├─ proposed → approved → dispatching
                            ├─ media_call (包装 tool.handler)
                            ├─ 判定 accepted / failed / unknown
                            ├─ read_state → verify → verified
                            └─ verified 后 _enqueue_impact_jobs (6 条)
              └─ _link_episode_to_action (Episode ↔ Action 软链)
       后台 run_due_jobs (2h/24h/7d 到点)
              └─ 聚合事实表 → observed / attributed envelope
              └─ 写回 AgentActionDB.observed_impact_json / attributed_impact_json
              └─ _promote_episode
                     └─ 门禁：live ∧ completeness>0 ∧ kind ∈ {observed, attributed}
                            → usable_for_learning=True
       StrategyStore.learn_from_memory
              └─ 只读 memory.usable_episodes()
              └─ 无 usable 样本 → 完全不动 _rules
```

---

## 3. 动作实体与状态机（Phase 3.1 → 3.3）

### 3.1 AgentActionDB 表

`agent_actions`（Alembic revision `2ba2dc778e26`）：每个真实写动作的唯一实体，跨 session / step / app / user / account 关联现有 `IntentExecution` 与 `ActionLog`。

关键字段：

- `id` (String32, PK)
- `idempotency_key` (String128, UNIQUE)：`hash(session_id, step_id, tool, params_digest)`。
- `session_id / step_id / app_id / user_id / account_id / entity_id / platform`。
- `tool / action / risk_level / execution_mode / state`。
- `predicted_impact_json`（Phase 4.1：仅存 predicted envelope）。
- `observed_impact_json` / `attributed_impact_json`（Phase 4.1，nullable；Phase 4.2 由 collector 回填）。
- `provider_request_id` / `provider_response_json` / `read_state_snapshot_json`。
- `proposed_at / approved_at / dispatched_at / accepted_at / verified_at / failed_at`。
- `expires_at`（Phase 3.2：审批过期）。
- `error / retry_count`。
- 关联：`intent_execution_id` / `action_log_id`（软链接，Phase 4 继续回填）。

### 3.2 状态机

`proposed → approved → dispatching → accepted → verified | failed | unknown`

- `unknown` 状态**不冒充成功也不冒充失败**：只要没有明确证据说媒体拒绝，就停在 unknown 等 `reconcile()`。
- 相同 idempotency_key 二次调用：直接返回原 action，媒体只调用一次。
- 非法状态跳转：`action_store` 会拒绝。
- 审批过期：`expires_at` 到点后再点批准返回 409；执行前重读实体状态与预算，超过漂移阈值废弃旧动作。

### 3.3 Dispatcher

`Dispatcher.dispatch_and_verify(session, action, media_call, ...)`：

- `media_call` 由 `AgentLoop` 传入 —— 包装 `tool.handler(params, ctx)`；`_record_execution` 仍写 `IntentExecution / ActionLog`。
- `_default_judge` 三分：`success=True → accepted`，`success=False → failed`，其余 → `unknown`。
- `_verify_state`：`update_campaign_status` 严格比对，`update_campaign_budget` 相对差 ≤ 5%，`adjust_bid` / `rotate_creative` 只要 `read_state` 不为 None 即视为 verified（真实效果由 Phase 4 观察）。
- `reconcile()`：批量把 `unknown` 收敛为 `verified / failed`。

**为什么保持同步、不上 durable outbox**：v3 仍是 SQLite 单进程；outbox + worker 会引入两段提交与新的故障模式。Phase 5.2 迁到 PostgreSQL + 多副本时再改。当前实现保证幂等 / 回读 / 对账在同步语义下也成立。

---

## 4. 三类影响 + 延迟回采（Phase 4.1 → 4.2）

### 4.1 ImpactEnvelope

`backend/app/services/agent_runtime/impact.py`：

```python
ImpactEnvelope(
    kind: Literal["predicted", "observed", "attributed"],
    metrics: Dict[str, float],
    window: Literal["2h", "24h", "7d"],
    time_zone: Optional[str] = "UTC",
    currency: Optional[str] = "USD",
    source: Optional[str] = None,
    freshness: Optional[str] = None,     # ISO 时间
    completeness: Optional[float] = None,  # None ≠ 0.0
)
```

三个构造器：`make_predicted / make_observed / make_attributed`。observed / attributed 未指定 completeness 时保持 **None**。

**核心不变量**：`completeness = None` 表示"未采到"；`0.0` 表示"采到了但事实数据为零"。禁止用 0.0 冒充"没有观察到" —— Phase 4.3 学习门禁凭此拒绝把"未采到"当有效样本。

### 4.2 三个字段共存

- `AgentActionDB.predicted_impact_json`：动作生效瞬间的模型预测。
- `AgentActionDB.observed_impact_json`：媒体报表回采（FactMediaDaily）。
- `AgentActionDB.attributed_impact_json`：MMP 归因回采（FactMMPDaily）。

`IntentExecution.observed_impact_json / attributed_impact_json` 同步补齐，供产品审计层读取。

### 4.3 延迟回采

`impact_collector.enqueue_after_verified(db, action)`：动作 verified 后生成 6 条 job（observed × 3 + attributed × 3），scheduled_at 精确对齐 `verified_at + {2h, 24h, 7d}`。

`run_due_jobs(db, now=None)`：拾起到点 job，聚合窗口 `pre=[action_day-7, action_day)` 与 `post=[action_day, action_day+window_days)`，日均口径求 delta。写回 AgentActionDB 与 job envelope。

- 事实表 0 行 → envelope 存在但 `metrics={} && completeness=0.0` → job 标记 done（不再重跑）。
- Media 走 FactMediaDaily 聚合，MMP 走 FactMMPDaily 聚合；不同源分别 enqueue 允许各自 SLA。
- `run_due_jobs` 幂等：done 状态不会二次处理。

生产调度：v3 暂由外部（APScheduler / cron / 脚本）周期调用 `run_due_jobs`；Phase 5.2 交给 durable worker。

---

## 5. Episode 学习门禁（Phase 4.3）

### 5.1 Episode 新增字段

`agent_episodes` 表（Alembic revision `a3e6a8c67106`）新增 5 列：

- `execution_mode` (String16, indexed)：`mock / sandbox / live`。
- `data_quality_json` (JSON)：`{impact_kind, execution_mode, completeness, sources[]}`。
- `usable_for_learning` (Boolean, indexed, default False)。
- `evidence_action_ids_json` (JSON)：AgentActionDB.id 列表。
- `action_id` (String32, indexed, FK → `agent_actions.id`)：1-1 软链接。

### 5.2 提权（唯一入口）

`impact_collector._promote_episode(db, action_id, kind, window, envelope)`：

- 覆盖 `Episode.impact_{window}` 为真实 envelope。
- 合并 `data_quality`：更新 `impact_kind` / `completeness` / 追加 sources。
- **门禁**：`execution_mode == "live" ∧ completeness > 0 ∧ kind ∈ {observed, attributed}` → `usable_for_learning=True`；否则只更新 data_quality，**不提权**。

### 5.3 StrategyStore 只读 usable

`StrategyStore.learn_from_memory(memory)`：

- 入口取 `memory.usable_episodes()`（严格 `usable_for_learning=True`）。
- 无 usable 样本 → `StrategyLearnResult(rules=当前rules, learned_keys=[], note="无可用真实样本…")`；**不动 `_rules`**。
- 有 usable 样本 → note 前置 `[usable=N 条真实样本] `。

**边界效果**：即便一整天全跑 Mock，`strategy.all()` 保持上一次真实学到的规则不变。

### 5.4 已知遗留

- `Reflector.aggregate()` 仍读所有 Episode（含 predicted）—— 供 UI 复盘展示。策略学习已严格挡住，但复盘摘要可能出现 predicted 数字。前端在 Phase 6/7 展示时需要用 `data_quality.impact_kind` 做区分显示。

---

## 6. 真实 / 模拟严格隔离（Phase 1.1 → 1.2）

### 6.1 BaseConnector 契约

`BaseConnector.execution_mode ∈ {mock, sandbox, live}`：

- MockMediaConnector 固定 `mock`（永不 live）。
- TikTok 在真实 API 未实现前 **拒绝 live**（`resolve_credentials` fail-closed）。
- Google live 缺凭证 / SDK / 权限时 **fail-closed** —— 明确抛错，绝不静默回退 mock。
- `resolve_credentials()` 只取凭证，不再决定回退策略。
- 默认 config `agent_default_platform="mock"`，生产环境必须**显式**指定 live。

所有 pull / action 结果携带 `execution_mode / platform / account_id / provider_request_id / verified_at`。

### 6.2 UI / API / SSE 全链路显示执行模式

- `AgentSession` / `AgentStep` / API 响应透传 `execution_mode` / `account_id`。
- Agent Console 对 Mock / Sandbox 显示**持续可见**的标签。
- 审批卡展示平台、账户、执行模式、数据时间、风险级别。

**为什么这样做**：v2 的"Meta 账户被封 → 静默切 Mock"是 v3 明确否决的语义。用户必须始终知道动作作用于哪里，混淆真实 / 模拟就等于把系统拿去承担 v3 不承担的风险。

---

## 7. 对象授权与 SSE 认证（Phase 2.1 → 2.2）

### 7.1 对象级授权

`agent_router` 全部端点走 `_require_app_access()` / `_require_session_access()`：

- 复用现有 `UserAppBinding`；`app_id` 是租户边界。
- Session / Action / Episode / Alert 都补齐 `app_id / account_id / created_by`，读写严格按授权范围查询。
- 对不存在与无权访问统一返回 404，避免对象枚举。
- 修复 v2 `session.app_id != session.app_id` 无效判断。

### 7.2 SSE 一次性票据

- 新增 stream-ticket 端点，JWT 认证签发**短期、单次、绑定 session/user** 的票据。
- SSE 仅接受 Authorization Header 或短票据；旧 `?token=` 仅保留一个可关闭的迁移开关，默认关闭。
- 增加 `Referrer-Policy: no-referrer`，日志 / APM 脱敏。
- 效果：长期 JWT 永不出现在 URL、代理日志、浏览器历史里。

---

## 8. Alembic 迁移链（v3 完整状态）

```
76c3bd1f529f_baseline_snapshot_from_current_models
     ↓
2ba2dc778e26_phase3_1_agent_actions
     ↓
49d2e70677ed_phase3_2_approval_expiry_and_precheck
     ↓
eaa540e8896a_phase4_1_split_impact_into_observed_and_attributed
     ↓
6aff1c23d194_phase4_2_agent_impact_jobs
     ↓
a3e6a8c67106_phase4_3_episode_learning_gate     ← HEAD
```

- 表数量：v2 baseline 33 → v3 HEAD 35（新增 `agent_actions` 与 `agent_impact_jobs` 两张表，本次 4.3 只加列不加表）。
- 空库 `alembic upgrade head` / 现有库 `stamp + upgrade` / `alembic check` / 数据保留：全部通过 `backend/tests/test_migration.py` 验证。

---

## 9. 后端 API 结构（v3 增量）

`agent_router` 端点保持向下兼容 v2 契约，返回 payload 新增字段：

- Session / Step：`execution_mode` / `account_id` / `verified_at`。
- Step (write)：`dispatch: {state, action_id, observation}`（Phase 3.3 起）。
- Action detail：`predicted_impact` / `observed_impact` / `attributed_impact` 三份 envelope 独立字段。
- Alert / Autonomy：`execution_mode` / `account_id` 透传。

新增：

- `POST /agent/sessions/{id}/stream-ticket`（Phase 2.2，SSE 短票据）。
- `POST /agent/actions/reconcile`（Phase 3.3，管理侧收敛 unknown 状态；默认关闭，需 admin 权限）。
- `POST /agent/impact/collect`（Phase 4.2，触发 `run_due_jobs`；默认关闭，需 admin 权限）。

**未开放**：v3 不新增只读工具、不接生产多媒体 live、不上通用 `shell_tool` / 动态 MCP 自动注册。这些进入 Phase 6/7 门禁通过后再开放。

详见 `API_REFERENCE_v3.md`。

---

## 10. 前端架构（v3 变更点）

`frontend/src/pages/AgentConsole.jsx`：

- Session 头部持续显示当前 `execution_mode` / `platform` / `account_id` 徽标（Mock 用醒目色，live 用中性色）。
- 步骤时间线的写动作卡展示：`predicted → observed → attributed` 三档结果并列（未回采时显式标记"未观察"，禁止空 metric 冒充 0）。
- 审批卡展示：审批过期倒计时 + 状态漂移提示 + `expires_at` 明文。
- 主动自治面板 Alert 列表新增 execution_mode 徽标；处置结果引用回原 action 的 dispatch state。
- SSE：改用 short-lived ticket；旧 `?token=` fallback 默认关闭。

详见 `USER_MANUAL_v3.md`。

---

## 11. 配置与部署要点（v3 变更）

- `agent_default_platform`：**默认 mock**。生产环境必须显式指定 live 且完成 Google 凭证配置。
- `agent_action_approval_ttl_seconds`：审批过期窗口（Phase 3.2）。
- `agent_impact_collector_run_interval_seconds`：外部调度器调用 `run_due_jobs` 的间隔建议值。
- `agent_sse_short_ticket_ttl_seconds`：SSE 短票据有效期。
- `agent_sse_allow_legacy_query_token`：兼容开关，默认 `false`。
- `alembic upgrade head` 是启动前置步骤；`create_all()` 仅在测试路径保留。

详见 `USER_MANUAL_v3.md` §"配置对照"。

---

## 12. v3 已知遗留 / 下一步

- **未接生产多媒体真实凭证**：Google live 已具备 fail-closed 路径，但真实凭证由运维配置后再切；TikTok 直到真实 API 上线之前禁 live；Meta 恢复后可切回。
- **单进程 collector**：`run_due_jobs` 需外部周期调用；多副本情况下的重复回采要等 Phase 5.2/5.4 的 durable worker + 独立调度。
- **Reflection 未加门禁**：见 §5.4。
- **PostgreSQL 迁移未开始**：v3 仍是 SQLite；Phase 5.1 将做 schema + 数据迁移，AsyncSession 逐步替换热路径。
- **策略 A/B / 回滚 / 版本历史**：Phase 5.3 交付；v3 的 `StrategyStore` 仍是 JSON 单例。

---

## 13. v3 版本历史（对齐 Production Truth 路线）

| 版本 | 日期 | 说明 |
|------|------|------|
| **v1.8.x** | 2026-07-22 | **Phase 4.3** Episode 学习门禁（只学 usable 真实样本） |
| v1.8.x | 2026-07-22 | Phase 4.2 延迟回采（observed / attributed 从事实表回填） |
| v1.8.x | 2026-07-21 | Phase 4.1 三类影响拆分（predicted / observed / attributed） |
| v1.8.x | 2026-07-21 | Phase 3.3 Dispatcher + 状态回读 + reconcile |
| v1.8.x | 2026-07-21 | Phase 3.2 审批过期与执行前重校验 |
| v1.8.x | 2026-07-21 | Phase 3.1 动作实体与幂等状态机 |
| v1.8.x | 2026-07-21 | Phase 2.2 SSE 一次性票据 |
| v1.8.x | 2026-07-21 | Phase 2.1 对象级授权（IDOR 修复） |
| v1.8.x | 2026-07-21 | Phase 1.2 execution_mode 在 API / SSE / 前端全链路显示 |
| v1.8.x | 2026-07-21 | Phase 1.1 Connector `execution_mode` + fail-closed live |
| v1.8.x | 2026-07-21 | Phase 0.2 Alembic 数据库迁移 |
| v1.8.x | 2026-07-21 | Phase 0.1 回归基线 |
| v1.8.0 | 2026-07-11 | Phase A 真实数据地基（持久化 + 真实渠道 + 真实归因接地） |
| v1.7.0 | 2026-07-11 | ark 推理服务对接 + 流式展示 + 外部检索 |
| v1.6.0 | 2026-07-10 | Phase 4 主动式自治（v2 anchor） |

> v1 / v2 原版文档保留，作为演进对照，本文档不覆盖它们。

---

*文档版本：v3 | 基于 2026-07-22 SmartUA v1.8.x 实际代码 | 配套 `API_REFERENCE_v3.md` / `CONNECTOR_DESIGN_v3.md` / `LLM_ROUTING_v3.md` / `USER_MANUAL_v3.md` / `RELATED_PROJECTS_v3.md`*
