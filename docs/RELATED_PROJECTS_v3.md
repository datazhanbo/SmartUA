# SmartUA 相关开源项目参考（v3）

> **版本说明**：本文档为 v3，基于 SmartUA **v1.8.x（2026-07-22）**。v2（`RELATED_PROJECTS_v2.md`）
> 已列出 Agentic / 多智能体 / 自治调度 / 强化学习 / 归因等大方向；v3 未替换 v2 内容，仅**补充**
> 生产升级路径（Phase 0.1 → 5.x 展望）需要的开源参考——数据库迁移、幂等状态机 / outbox、
> 事件驱动回采、审计与合规。
>
> v1 / v2 保留，作为演进对照。
>
> 文档路径：`docs/RELATED_PROJECTS_v3.md`

---

## 1. 数据库迁移与 schema 版本（Phase 0.2 已用）

| 项目 | 地址 | 用途 |
|-----|------|------|
| **Alembic** | https://github.com/sqlalchemy/alembic | v3 的 schema 迁移 backbone；SmartUA `backend/alembic/` 使用中 |
| **Atlas** | https://github.com/ariga/atlas | 声明式 schema 管理，未来跨引擎（PostgreSQL vs SQLite）参考 |

**可借鉴**：v3 已固定 revision chain `76c3bd1f529f → 2ba2dc778e26 → 49d2e70677ed → eaa540e8896a → 6aff1c23d194 → a3e6a8c67106`；Phase 5.1 PostgreSQL 迁移会继续沿用。

---

## 2. 幂等状态机 / Outbox 模式（Phase 3.3 → 5.2）

| 项目 | 地址 | 相关度 |
|-----|------|-------|
| **Temporal** | https://github.com/temporalio/temporal | Workflow + 状态机 + retry 的行业标杆；Phase 5.2 durable worker 的目标形态 |
| **dbos-transact** | https://github.com/dbos-inc/dbos-transact-py | Transactional workflow（Python），把状态机与数据库事务耦合 |
| **transactional-outbox 模式** | Chris Richardson 的模式描述 | Phase 5.2 outbox 表 + lease worker 的理论依据 |
| **sqlalchemy_events / sqlalchemy_utils** | https://github.com/kvesteri/sqlalchemy-utils | 无 outbox 前的轻量事件钩子替代 |

**可借鉴**：v3 的 `AgentActionDB` + `Dispatcher.dispatch_and_verify` + `reconcile()` 是同步版
outbox；Phase 5.2 要引入 durable worker + lease 时会向 Temporal / dbos 靠拢。

---

## 3. 事件驱动 / 延迟任务（Phase 4.2 → 5.2/5.4）

| 项目 | 地址 | 相关度 |
|-----|------|-------|
| **APScheduler** | https://github.com/agronholm/apscheduler | v2 已用（主动巡检）；v3 用来周期调用 `run_due_jobs` |
| **arq** | https://github.com/samuelcolvin/arq | Redis-backed 异步 Python worker；轻量替代 |
| **Celery** | https://github.com/celery/celery | 传统 Python 任务队列；Phase 5.2 的备选 |
| **RQ (Redis Queue)** | https://github.com/rq/rq | 最简单的 Redis 队列；小规模 Phase 5.2 |
| **Litestar 的 SAQ** | https://github.com/tobymao/saq | 现代 async 任务队列 |

**可借鉴**：v3 `impact_collector` 目前依赖外部调度器周期调 `run_due_jobs`；Phase 5.2 会改成
持久化 job queue + 独立 worker + lease 消费。Phase 5.4 独立调度需要"多副本不重复投递"，
APScheduler + PostgreSQL leader lock 是最小成本方案。

---

## 4. 审计 / 合规（Phase 4.3 → 6/7）

| 项目 | 地址 | 相关度 |
|-----|------|-------|
| **OpenLineage** | https://github.com/OpenLineage/OpenLineage | 数据血缘标准；`data_quality.sources[]` 已经在同构思路 |
| **DataHub** | https://github.com/datahub-project/datahub | 元数据管理；Phase 6 只读工具扩充时可对接 |
| **OpenTelemetry** | https://github.com/open-telemetry/opentelemetry-python | 结构化追踪；Phase 5.4 可观测性核心组件 |
| **Prometheus** | https://github.com/prometheus/prometheus | 指标；Phase 5.4 SLO |
| **Alertmanager** | https://github.com/prometheus/alertmanager | 告警路由；主动自治外部通道 |

**可借鉴**：v3 Episode `evidence_action_ids_json` 是最小血缘；Phase 6/7 反思和策略变更需要
完整血缘时可对接 OpenLineage / DataHub。

---

## 5. 沿用 v2 的方向

以下方向 v2 已详列，v3 未变，请直接参考 `RELATED_PROJECTS_v2.md`：

- AI Agent / 多智能体框架（LangGraph / AutoGen / CrewAI / DSPy 等）
- 自治调度（APScheduler / Prefect / Airflow）
- 强化学习 / 出价优化（Ray RLlib / Stable-Baselines3 / Prophet / Gymnasium）
- 广告投放 / 归因（GrowthBook / AdServe / Matomo / PostHog）
- 数据管道 / CDP（Airflow / Dagster / dbt / RudderStack）

---

## 6. SmartUA 阶段对照（v3 更新）

| SmartUA 能力（Phase） | 对应开源范式 | v3 实现 |
|----------------------|-------------|---------|
| Agent Loop（P1） | LangGraph 有状态图 + interrupt | `AgentLoop` + `AgentSession` |
| 记忆 / 反思（P2） | LLM Memory / Experience Replay | `EpisodicMemory` + `Reflector` |
| 策略自演化（P3） | DSPy / RL 策略 | `StrategyStore`（v3 已加学习门禁） |
| 主动自治（P4） | APScheduler + 监控告警 | `AutonomyEngine` + `AnomalyDetector` |
| **execution_mode 契约（P1.1/1.2）** | Feature Flags + 环境隔离 | `BaseConnector.execution_mode` fail-closed |
| **对象授权 / SSE 短票据（P2.x）** | RBAC + 短生命周期 token | `_require_app_access` + stream-ticket 端点 |
| **动作幂等状态机（P3.1/3.3）** | Outbox / Temporal Workflow | `AgentActionDB` + `Dispatcher` + `reconcile` |
| **审批过期 / 状态漂移（P3.2）** | 乐观锁 + 前置校验 | `expires_at` + 执行前重读 |
| **三类影响 + 延迟回采（P4.1/4.2）** | 事件源 + 事实表回填 | `ImpactEnvelope` + `impact_collector` |
| **Episode 学习门禁（P4.3）** | 数据质量守门员 | `usable_for_learning` + `data_quality` |

---

*文档版本：v3 | 基于 2026-07-22 SmartUA v1.8.x 实际代码 | 配套 `ARCHITECTURE_v3.md` / `API_REFERENCE_v3.md` / `CONNECTOR_DESIGN_v3.md` / `LLM_ROUTING_v3.md` / `USER_MANUAL_v3.md`*
