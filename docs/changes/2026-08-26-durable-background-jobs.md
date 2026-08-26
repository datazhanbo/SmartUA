# 2026-08-26 — P2 #4：Durable Background Jobs

> 对应 `docs/HARNESS_UPGRADE_PLAN.md` 的 **#4（Durable Background Jobs，P2）**。
> 在 P0 Tool Pipeline + P1 MCP/Skill + AdSet/Ad 粒度之后，把原本进程内的延迟任务统一收敛到 DB。
> 这是 Harness 升级计划的最后一项，P0/P1/P2 至此全部完成。

## 背景与动机

升级前：

- `impact_collector` 的 6 条延迟回采 job（observed/attributed × 2h/24h/7d）已经有自己的专用表
  `agent_impact_jobs`，但**没有进程内调度器自动消费**——只能靠 API `/agent/impact/collect` 或外部 cron 手动触发。
- `autonomy.py` 的周期巡检走 APScheduler `BackgroundScheduler`，job 状态**只在进程内**，
  进程重启会丢失扫描节奏；多实例部署也无法协调。
- 两套机制各自维护，新增一个后台 job 就要再建一张表 + 一个调度入口。

P2 #4 的目标（计划原文）：

> 短期不引入 Celery/Temporal（过度工程），做最小 durable 版本：JobState 表 + APScheduler 启动恢复 pending job，
> 执行后更新状态。不引入 Redis/RabbitMQ——SQLite 够 SmartUA 当前量级。

## 新增 / 变更

### 1. 通用 `agent_jobs` 表（`app/models/agent_runtime.py::JobDB`）

| 字段 | 说明 |
|------|------|
| `id` | 32-char hex |
| `job_type` | `impact_collect` / `autonomy_scan` / 未来扩展 |
| `idempotency_key` | UNIQUE，重入去重 |
| `status` | `scheduled / running / done / failed / cancelled` |
| `scheduled_at / started_at / finished_at` | 调度与执行时间戳 |
| `payload / result` | JSON |
| `attempts / max_attempts` | 崩溃重试计数 |
| `last_error` | Text |
| `app_id` | 可选隔离 |

索引：`(status, scheduled_at)`（due 查询）、`(job_type, status)`、`idempotency_key` UNIQUE。

### 2. Alembic 迁移 `6c0b1d9e4a3f_phase4_4_durable_jobs.py`

- `down_revision = "a3e6a8c67106"`（phase4.3 learning gate）。
- 新建 `agent_jobs`。
- **drop 旧 `agent_impact_jobs` 表**——SmartUA 仍 pre-production，无生产数据需要迁移；
  impact 回采状态统一收敛进 `agent_jobs`，不保留双写。downgrade 会重建旧表结构。
- `tests/test_migration.py` 同步：`_KNOWN_TABLES 36 → 35`（一增一减）、`_HEAD_REVISION = 6c0b1d9e4a3f`。
- `alembic check` 验证：`No new upgrade operations detected.`

### 3. `JobRunner`（`app/services/agent_runtime/jobs.py`，新增）

```python
class JobRunner:
    def register(job_type, handler): ...
    def enqueue(db, job_type, payload, *, scheduled_at, idempotency_key,
                app_id, max_attempts=1) -> Optional[JobDB]: ...
    def recover_stale(db, *, now, timeout=timedelta(minutes=10)) -> int: ...
    def run_pending(db, *, now, limit=50, job_type=None, app_id=None) -> dict: ...
```

- **Handler 签名**：`Callable[[Session, dict], Optional[dict]]`；返回值写 `result`。
- **claim 语义**：单进程内 `_run_one` 先把 job 置 `running` + `attempts += 1` 再 `flush()`，
  同一 tick 内不会被二次拾取。
- **异常路径**：handler 抛错时，`attempts < max_attempts` 回 `scheduled`（下个 tick 重试），
  否则落 `failed`；错误写 `last_error`。
- **Stale recovery**：`started_at < now - timeout` 的 running job 视为进程崩溃遗留，
  有重试次数则复位，无重试次数则落 `failed`。
- **幂等 enqueue**：同 `idempotency_key` 已存在 → `IntegrityError` 被吞，返回 `None`。
- **单例**：`get_job_runner()` / `register_default_handlers()`（注册 `impact_collect` + `autonomy_scan`）
  / `reset_job_runner()`（测试钩子）。

刻意没做（计划明确不做）：多实例并发锁、priority queue、DAG 依赖、Celery/Temporal。

### 4. `impact_collector` 迁到通用 Job

- `enqueue_after_verified` 从写 `AgentImpactJobDB` 改为写 `JobDB`：
  - `job_type="impact_collect"`
  - `payload = {action_id, kind, window}`
  - `idempotency_key = f"impact:{action_id}:{kind}:{window}"`
- 新增 `run_impact_job(db, payload)`：JobRunner handler，封装原来 `_collect_one` +
  Episode 提权逻辑。
- `run_due_jobs` 保留为独立便捷入口（API `/agent/impact/collect` / 外部 cron 用），
  不依赖 JobRunner 单例，内部直接 claim + `run_impact_job`，返回 `{done, empty, failed}`。
- `AgentImpactJobDB` 模型类删除；旧测试改为断言 `JobDB`。

### 5. `autonomy` 迁到 Durable Job

- 新增 `run_autonomy_scan_job(db, payload)`：调 `AutonomyEngine().scan(app_id=...)`，
  返回 `{app_id, elapsed_ms}`。
- `enqueue_autonomy_scan_jobs()`：按 interval 做时间桶 idempotency_key
  `f"autonomy:scan:{app_id}:{bucket}"`，为每个 `agent_monitor_app_ids` 入队一条。
- `start_scheduler()` 改造：APScheduler 不再直接跑业务逻辑，只起两个 tick：
  - `autonomy_enqueue`：每 `agent_autonomy_interval_seconds` 调一次 enqueue（启动时立即补一次）。
  - `job_runner_tick`：每 `agent_jobs_tick_seconds`（默认 30s）调一次
    `recover_stale` + `run_pending(limit=100)`（启动时立即补一次）。
- **重启行为**：启动瞬间先做一次 `recover_stale + run_pending`，离线期间到点的
  impact job / 上次未跑完的 autonomy scan 立刻被拾起。

### 6. 配置（`app/config.py`）

```python
agent_jobs_tick_seconds: int = 30
agent_jobs_stale_minutes: int = 10
```

`main.py` lifespan：启动时 `register_default_handlers()`，再 `start_scheduler()`；
关闭时 `stop_scheduler()`。不再依赖 `agent_autonomy_enabled` 才启动调度——JobRunner
是基础设施，impact 回采也需要它；autonomy 自己仍然只在 `agent_autonomy_enabled=true`
时入队。

（注：本轮把 lifespan 的 autonomy gate 去掉，让 job runner 始终起来；autonomy 的 enqueue
本身仍受配置控制，不违反"主动巡检开关"的承诺。）

## Rationale

- **为什么自己写而不接 Celery/Temporal**：SmartUA 单进程 + SQLite，Celery 要 broker（Redis/RabbitMQ），
  Temporal 要 server，两者都是"运营出问题后的解法"。当前阶段 DB 表 + APScheduler tick
  是最小足够的 durable 子集，计划已经明确划线。
- **为什么把 `agent_impact_jobs` 直接 drop 而不是双写**：这张表上线才一个 phase（4.2），
  没有生产数据；保留双写会让两条 job 系统并存到永远，反而违背"收敛"。一次性 drop 是
  正确的 schema 决策，downgrade 路径也保留了。
- **为什么 `run_due_jobs` 不直接走 JobRunner 单例**：API / cron 触发路径需要独立于
  进程内单例，测试也更容易隔离；让它自己 claim + 调 handler，避免引入"先 register 再
  run"的顺序依赖。
- **为什么 autonomy 用时间桶去重**：APScheduler 多实例 / 重复启动可能同时 enqueue。
  时间桶 key 让同一 interval 内只入队一条，幂等约束兜底。
- **为什么 `max_attempts` 默认 1**：impact 回采的"无事实数据"是正常空结果不是错误，
  不需要重试；真正的 handler 异常（DB 锁、临时网络）才值得重试，调用方按需传 2~3。

## 测试

新增 `tests/test_jobs_persistence.py`（13 用例）：

1. `test_enqueue_and_run_happy_path` — 完整 scheduled→running→done 生命周期
2. `test_not_due_yet_is_skipped` — 未到点跳过
3. `test_idempotent_enqueue` — 同 key 不重复
4. `test_missing_handler_marks_failed` — 未注册 handler 落 failed
5. `test_handler_exception_failed_after_max_attempts` — 重试耗尽
6. `test_done_jobs_are_not_reprocessed` — done 不重跑
7. `test_recover_stale_resets_running_job` — 崩溃 running 复位
8. `test_recover_stale_marks_failed_after_max_attempts` — 崩溃 + 无重试 → failed
9. **`test_restart_picks_up_pending_jobs`** — 核心 durable 承诺：新 JobRunner 实例拾起 pending
10. **`test_impact_jobs_survive_runner_restart`** — impact 端到端，新 runner 跑完 6 条回采
11. `test_impact_jobs_are_idempotent_across_restarts` — enqueue 重入幂等
12. `test_register_default_handlers_idempotent` — 注册幂等
13. `test_autonomy_scan_handler_invokes_engine` — monkeypatch AutonomyEngine

既有 `test_impact_collector.py` / `test_episode_learning_gate.py`：`AgentImpactJobDB` → `JobDB`，
断言从 `j.kind` 改成 `j.payload["kind"]`。

全量：

```
cd backend && python3 -m pytest -q
# 194 passed
```

（P1 #2 完成时 181；本轮 +13 → 194。）

迁移：

```
DATABASE_URL=sqlite:////tmp/x.db alembic upgrade head   # 7 revisions OK
DATABASE_URL=sqlite:////tmp/x.db alembic check          # No new upgrade operations detected.
```

## 已知遗留 / 非目标

- **多实例并发**：两个进程同时 claim 同一 job 仍可能双跑。SQLite 单实例 + WAL 是当前部署形态，
  等真有第二个实例再加 `SELECT ... FOR UPDATE` 或 `claim_token` 字段。
- **无 priority / DAG**：`ORDER BY scheduled_at ASC LIMIT n` 足够；impact 和 autonomy 互不依赖。
- **autonomy enqueue 仍在应用进程内**：如果所有 Web 进程都挂了，没人 enqueue 也没人 tick。
  生产形态建议至少一个常驻进程开 `agent_autonomy_enabled=true`（或外部 cron 调 `/agent/impact/collect`）。
- **`agent_autonomy_enabled` 开关语义微调**：JobRunner tick 总是启动（基础设施），
  但 autonomy enqueue 仍受开关控制；文档/配置同步更新到 `USER_MANUAL_v4.md` §9。
