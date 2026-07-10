# SmartUA 多用户并发升级方案（SCALING_UPGRADE）

> 配套：`ARCHITECTURE_v2.md` / `API_REFERENCE_v2.md` / `CONNECTOR_DESIGN_v2.md`
> 状态：**当前（v1.6.0）架构满足单团队日常使用，本文件是"何时、如何"做横向扩展的实施清单。**
> 原则：**当前工程架构已经够用，本文件仅在用户规模/并发超出单进程 SQLite 时启用。**

---

## 0. 一句话结论

当前是 **「单进程 uvicorn + SQLite + 进程内内存单例」** 的小团队架构。
它能舒适支撑 **约 10–30 人同时在线**（个位数~十位数并发写），且前端已无状态、可随意加 CDN。

要做到"很多用户并发"，**唯一的核心改造是把 SQLite + 内存单例换成 PostgreSQL + 外部化状态**，之后后端即可水平加 worker。其余（限流、缓存、调度分布式化）都是在那之后的增强。

---

## 1. 当前架构能力边界（代码实证）

| 维度 | 现状 | 代码位置 |
|------|------|---------|
| 数据库 | **SQLite 单文件** | `config.py:8` → `sqlite:///./smartua.db` |
| ORM 会话 | **同步** `SessionLocal`（阻塞事件循环） | `db/base.py:6-12`，`get_db()` 返回同步 `Session` |
| SQLite 并发 | 写串行（一次一个写事务），读可数十~上百并发 | `db/base.py:8` 仅对 sqlite 放开 `check_same_thread` |
| Agent 记忆 | **进程内单例** | `memory.py:115-124`（`_memory`） |
| 策略 | 单例 + **已落盘 JSON**（多进程各持副本） | `strategy.py:165-173` + `config.py:54-56` |
| 会话状态 | **进程内单例** | `session.py:118-125`（`_session_store`） |
| 主动自治告警/扫描 | **进程内单例** | `autonomy.py:414-418`（`_autonomy_store`） |
| 模拟引擎（投放状态） | **进程内单例**（全局单账户） | `mock_media.py:22-28`（`get_sim_engine`） |
| 巡检调度 | APScheduler **内存 JobStore**（不跨进程） | `autonomy.py:373-379`（`BackgroundScheduler()` 默认 `MemoryJobStore`） |
| 前端 | 无状态（JWT 存 localStorage），SPA 构建产物可上 CDN | `frontend/src/api.js` |

### 1.1 并发能力量化

| 场景 | 量级 | 说明 |
|------|------|------|
| 只读大盘/健康度 | 数十 ~ 上百并发 | SQLite 读不受写锁影响 |
| 日常投放操作（建会话/审批） | **10–30 人舒适** | 写串行但量级低，体验无感 |
| 主动自治巡检（120s 一轮） | 单进程即可 | 无外部写入压力 |
| 临界点 | >30 人同时写 / 写竞争激烈 | SQLite 写锁排队，P95 延迟上升 |
| 硬上限 | 多开 worker | 内存单例分叉 → 学到的策略、告警去重、会话状态各管各的 |

### 1.2 三大瓶颈（按影响排序）

1. **状态在内存** → 不能水平扩容（加 worker 即状态分叉）。
2. **同步 ORM 会话** → `async def` 路由里若用 `db: Session = Depends(get_db)`，会阻塞事件循环，并发量被单进程 CPU 锁死。
3. **SQLite 写串行** → 写竞争激烈时吞吐封顶。

---

## 2. 何时启用升级（决策阈值）

| 信号 | 触发动作 |
|------|---------|
| 日常同时在线 > 30 人，且写操作开始排队 | 启动 **P0** |
| P95 接口延迟随用户数线性上升 | 启动 **P0 + P1** |
| 需要零停机发布 / 多副本高可用 | 启动 **P1**（容器化） |
| 主动自治告警出现重复提案 | 启动 **P2**（调度分布式化） |
| LLM 调用频繁 429 / 成本飙升 | 启动 **P3**（并发治理） |
| 大盘查询成为热点 | 启动 **P4**（缓存） |

> 当前阶段：**均未达到**，保持现状即可。本文件留作扩容剧本。

---

## 3. 分阶段升级方案（实施清单）

### P0 — 状态外置：SQLite → PostgreSQL + 异步会话

**目标**：让后端进程变为无状态，为多 worker 扫清障碍。

#### 3.0.1 数据库切换到 PostgreSQL（含 async）

- 改动 `config.py:8`：
  ```python
  # 旧
  database_url: str = "sqlite:///./smartua.db"
  # 新（env 可覆盖）
  database_url: str = "postgresql+asyncpg://user:pass@localhost:5432/smartua"
  ```
- 改 `db/base.py:1-12` 为异步：
  ```python
  from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
  engine = create_async_engine(settings.database_url, echo=False)
  SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
  ```
- `get_db()` 改为 `async def`，路由依赖同步会话的 `agent.py` 等改为 `async def` 并用 `async with db`。
- 依赖：`pip install asyncpg`（已有 `psycopg`/pg upsert 抽象在 `connectors/base.py:150` 已就绪）。

#### 3.0.2 内存单例外置为 DB 表

| 单例 | 落库方案 | 数据模型已具备？ |
|------|---------|----------------|
| `EpisodicMemory`（`memory.py:115`） | 新增 `episodes` 表（session_id, tool, action, params, impact_json, reward, ts）；`add()` 写表，`suggest_*()` 查表聚合 | Episode dataclass 已定义 ✅ |
| `AgentSessionStore`（`session.py:118`） | 新增 `agent_sessions` / `agent_steps` 表；`create()`/`append_step()` 写表 | AgentSession/AgentStep 已定义 ✅ |
| `AutonomyStore`（`autonomy.py:414`） | 新增 `autonomy_alerts` / `autonomy_scans` 表；`add_alert()`/`mark_resolved()` 写表 | AutonomyAlert dataclass 已定义 ✅ |
| `StrategyStore`（`strategy.py:165`） | 从 JSON 文件改为 `strategy_rules` 表 + **行锁/UPSERT**，避免多进程写竞争 | `_rules` 已是 dict，迁移成本低 ✅ |
| `SimulationEngine`（`mock_media.py:22`） | 按 `app_id` 维度存投放状态（现全局单账户，多租户必须隔离）；真实 Meta 恢复后此引擎退居 Mock | `seed_demo_account()` 已按账户建模 ✅ |

> 落库后，`get_*` 单例可改为「进程内读缓存 + DB 为真相源」，既保留单例 API 又共享状态。

#### 3.0.3 验证
- 单进程起服务，制造 2 个 Agent 会话并发写，重启进程后状态仍在（证明落库）。
- 跑 `scripts/demo_phase2.py` / `demo_phase4.py` 仍全绿。

---

### P1 — 多进程 / 容器化部署

**目标**：水平扩容，多副本共享同一份真相（依赖 P0 完成）。

- 启动方式改为：
  ```bash
  gunicorn main:app -k uvicorn.workers.UvicornWorker -w 4 --bind 0.0.0.0:8000
  # 或容器 + K8s HPA
  ```
- 同步 ORM 调用若未全改 async，用 `run_in_threadpool` 包裹，避免阻塞事件循环。
- 环境变量化所有 `config.py` 的 agent 开关（`agent_autonomy_enabled` / `interval` / `monitor_app_ids` 等，`config.py:58-68`），便于按环境调参。
- 前端：`vite build` 产物部署到对象存储 + CDN，无需改代码（已无状态）。

#### 验证
- 起 4 个 worker，压测 `/api/v1/agent/sessions`（并发建会话），确认无状态分叉、DB 无重复主键冲突。

---

### P2 — 调度器分布式化

**目标**：避免多 worker 各跑各的扫描导致告警重复。

- APScheduler 切换为共享 JobStore（Postgres/Redis）+ leader 选举：
  ```python
  # autonomy.py:378 由
  _scheduler = BackgroundScheduler()
  # 改为
  _scheduler = BackgroundScheduler(
      jobstores={"default": SQLAlchemyJobStore(url=settings.database_url)},
      executors={"default": ThreadPoolExecutor(1)},
  )
  ```
- 或把"主动巡检"从 web 进程剥离：独立 worker / Celery beat / K8s CronJob 调用 `POST /agent/autonomy/scan`。
- 冷却去重（`agent_autonomy_cooldown_scans`，`config.py:64`）改为 **DB 行级计数**，跨进程生效。

#### 验证
- 起 2 副本，观察同一异常只产生 1 条告警（去重跨进程生效）。

---

### P3 — LLM 并发治理（关键，最易被忽略）

**事实**：Agent Loop 每轮都打 LLM（`agent_use_llm_planning`，`config.py:50`），多用户并发时是**最大外部瓶颈**。

- 加 **Redis 令牌桶限流 + 每用户配额 + 请求队列**：
  ```python
  # loop.py 调 LLM 前走限流器
  await limiter.acquire(user_id, tokens=1)
  ```
- 复用现有多模型路由做降级（LLM_ROUTING_v2.md）；必要时同步调用走异步。
- 给 `agent_max_steps`（`config.py:48`）设并发上限，防止单用户占满 LLM 配额。

#### 验证
- 50 并发会话同时发起，LLM 调用被限速且按配额排队，无 429 风暴。

---

### P4 — 缓存与可观测

- **Redis 缓存**：大盘/健康度查询（读多写少），`connectors/base.py` 的 pg upsert 已为落库铺路。
- **DB 连接池**：asyncpg 自带；调大 `pool_size`。
- **可观测**：Prometheus 指标 + 结构化日志 + Agent Loop 链路追踪（`session.py` 的 step 已带 kind/status，天然适合 trace）。

---

## 4. 升级后能力量级

| 阶段 | 并发能力 | 主要瓶颈 |
|------|---------|---------|
| 当前（SQLite + 单进程） | ~10–30 人舒适，无法横向扩展 | 内存单例 + 写锁 |
| P0（PG + 状态外置） | 单进程吞吐提升，已可加 worker | 单进程 CPU |
| P0 + P1（多 worker） | 数百 ~ 上千并发在线 | DB 容量 / LLM 配额 |
| + P3 / P4（限流 + 缓存） | 数千级 | LLM API 速率 / PG 容量 |

---

## 5. 前端说明

前端已是无状态 SPA（JWT 存 localStorage，`frontend/src/api.js`）：
- 扩容只需把 `vite build` 产物（`dist/`）部署到对象存储 + CDN，headers 配好 `Cache-Control` 即可；
- 无需任何代码改动，不受后端 worker 数影响。

---

## 6. 落地顺序建议

```
P0（状态外置）  ──►  P1（多 worker 容器化）  ──►  P2（调度分布式）
                                              └──►  P3（LLM 治理）  ──►  P4（缓存/可观测）
```

- **不要提前做 P1+**：在 P0 完成前加 worker 只会让状态分叉、引入更难查的 bug。
- **P3 可与 P1 并行**：LLM 治理与状态外置互不依赖，且并发一上来立刻就是瓶颈。
- 当前（v1.6.0）**无需任何动作**，保持 SQLite + 单进程即可。

---

## 7. 最小可落地验证脚本（P0 完成后）

建议新增 `scripts/verify_scaling.py`：
1. 启 1 进程，并发建 2 个 Agent 会话并各写 5 步；
2. 重启进程，`GET /agent/sessions/{id}` 验证状态仍在（落库成功）；
3. 起 4 worker，并发 20 次 `POST /agent/sessions`，验证无主键冲突、无状态分叉。

---

_文档基于 SmartUA v1.6.0 实际代码核对撰写，所有 `文件:行号` 引用均可在仓库中定位。_
