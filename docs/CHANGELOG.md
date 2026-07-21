# 更新日志

## 未发布 - 2026-07-21 — 生产升级 Phase 1.2 执行模式在 API / SSE / 前端全链路显示

### Added（新增）

- **`AgentSession` provenance 字段**：新增 `platform / execution_mode / account_id`，直接写入会话对象；`AgentSessionStore.create()` 支持显式传入，`persist()` / `_row_to_session()` 通过 `context_json` 中的保留键 `_provenance` 完成落盘与回读，不引入新表 / 不触发 Alembic 迁移。
- **API 端点 provenance 透传**：
  - `POST /agent/sessions` 先解析目标连接器的 `platform / execution_mode / account_id` 再落库；live 缺凭证/SDK 时抛 `400`，永不静默回退 mock。
  - `GET /agent/sessions/{id}/stream` 的 `snapshot` 与 `status` 事件带 `provenance: {platform, execution_mode, account_id}`。
  - `GET /agent/autonomy/status` 新增 `execution_mode`。
- **审批步骤 provenance 冻结**：`AgentLoop._dispatch()` 生成 `APPROVAL` 步骤时把连接器的 `platform / execution_mode / account_id` 写入 `step.result.provenance`，让"到底作用在哪个账户"随审批一起保存到 DB，事后审计可回放。
- **前端 `ProvenanceTag` 常驻标识**（`frontend/src/pages/AgentConsole.jsx`）：
  - 会话头：Mock/Sandbox/Live 徽标 + 平台 + 账户。
  - 审批卡：从 `step.result.provenance` 读取，永远与 Agent 决策时的目标一致。
  - 执行结果卡（`action` 步骤）：从 Phase 1.1 的 `_decorate_action_result` 装饰读取 `platform / execution_mode / account_id`。
  - 主动巡检状态条：新增 execution_mode 徽标。
- **`tests/test_session_persistence.py`**：新增 `test_session_provenance_persists_across_reload` 与 `test_session_provenance_defaults_are_none`，覆盖持久化回读一致性与 `_provenance` 保留键不外泄。

### Changed（变更）

- **`agent_default_platform` 与 `agent_execution_mode` 分离展示**：前端不再只显示"平台"，而是"平台 + 执行模式"，Mock 数据即使在 Live 模式的服务上也无法冒充真实结果。
- **SSE 客户端合并策略**：`AgentConsole` 在 `snapshot` 事件时会用后端 provenance 覆盖本地缓存，避免用户刷新页面后短暂看到旧值。

### Validation（验证）

- `python3 -m pytest tests/ -v`：56 项全部通过（原 54 项 + 新增 2 项 provenance 持久化断言）。
- `python3 scripts/smoke_phaseA.py`：A1/A2/A3 全部通过。
- `python3 scripts/demo_phase4.py`：主动巡检、L0 自动执行、L1 审批、账户禁用告警、冷却去重、策略阈值、调度器全部通过。
- `npx vite build`：前端构建成功（2456 KB，gzip 791 KB），无 JSX 报错。
- 未做浏览器端到端点击验证（无本机浏览器沙箱访问）；需要 UI 交互回归时可执行 `npm run dev` + 后端 `uvicorn` 后手动过一遍。

### 外部依赖阻塞

- 无新增。Google/Meta live 真实链路仍需真实凭证 + SDK；本轮仍属 Phase 1.1 的验证遗留。

---

## 未发布 - 2026-07-21 — 生产升级 Phase 1.1 Connector 执行模式与 Fail-Closed

### Added（新增）

- **`BaseConnector.supported_modes` / `capabilities`**：所有连接器显式声明支持的执行模式（`mock` / `sandbox` / `live`）与能力（read / write / structure / simulate），构造时按 `execution_mode` 校验，模式不匹配立即抛 `ValueError`。
- **`execution_mode` 参数贯通**：`BaseConnector.__init__` 与 `ConnectorFactory.get_connector` 均要求显式声明；`available_connectors()` 输出补充 `supported_modes` 与 `capabilities`。
- **结果 provenance 装饰**：`_result_meta` / `_decorate_pull_result` / `_decorate_action_result` 三个 hook 在 `execute_pull` 与 `apply_action` 出口自动注入 `platform / execution_mode / account_id / is_mock / verified_at`，Mock 数据与写动作永久留痕。
- **`settings.agent_execution_mode`**：新增 `Literal["mock", "sandbox", "live"]` 全局执行模式（默认 `mock`），生产环境需显式覆盖为 `live` 才会发起真实 API 调用。
- **`tests/test_connectors_execution_mode.py`**：新增 16 项断言，覆盖 supported_modes 声明、unsupported-mode 拒绝、Google/Meta live fail-closed（缺凭证、缺 SDK）、Mock provenance 输出、工厂 metadata 暴露 supported_modes/capabilities。

### Changed（变更）

- **Google Ads live 严格 fail-closed**：凭证不齐或 `google-ads` SDK 不可用时构造直接抛错，不再静默回退 mock；`auth()` 移除“credentials incomplete → mock mode”日志。
- **Meta live 严格 fail-closed**：`execution_mode="live"` 时缺 `facebook_business` SDK 或 `access_token` 直接抛错；`pull_structure` 与 4 个写动作按 `execution_mode` 判定 mock/live，不再基于 SDK 全局标志静默切换。
- **TikTok / AppsFlyer 声明 mock-only**：真实 API 未实现前 `execution_mode="live"` 立刻抛错，杜绝“认证成功但从未接触真实平台”的假成功。
- **`agent_default_platform` 回退为 `mock`**：与执行模式默认 `mock` 对齐，避免真实平台默认；生产环境需在 `.env` 显式指定平台 + `agent_execution_mode="live"`。
- **`agent.py::_make_ctx` / `autonomy.py::scan` / `connector_service`（3 处）**：全部按 `settings.agent_execution_mode` 传参，禁止旧的隐式回退。
- **`resolve_credentials()`**：仅负责解析凭证，不再决定回退策略；文档、`scripts/smoke_phaseA.py`、`scripts/demo_phase4.py`、`scripts/verify_google_live.py`、`tests/test_connector_factory.py`、`tests/test_autonomy_engine.py` 全部改为显式声明 `execution_mode`。

### Validation（验证）

- `python3 -m pytest tests/ -v`：54 项全部通过（原 38 项 + 新增 16 项 execution_mode 断言）。
- `python3 scripts/smoke_phaseA.py`：A1/A2/A3 全部通过；execution_mode 显式声明未破坏 Mock 拉取/结构/影响接地。
- `python3 scripts/demo_phase4.py`：主动巡检、L0 自动执行、L1 审批、账户禁用告警、冷却去重、策略阈值与调度器均通过。
- Google/Meta live 真实链路仍属外部依赖阻塞（无 SDK 与 live 凭证）；本次仅验证 fail-closed 行为。

---

## 未发布 - 2026-07-21 — 生产升级 Phase 0.2 Alembic 数据库迁移

### Added（新增）

- **Alembic 数据库迁移框架**：`backend/alembic/` 初始化，含 `alembic.ini` 和 `env.py`（SQLite 兼容 batch 模式 + `compare_type=True`）。
- **Baseline 迁移 `76c3bd1f529f`**：覆盖全部 33 张 model 表，按依赖顺序生成，含所有索引、唯一约束和复合索引。
- **启动时 Schema 版本检查**（`main.py`）：已迁移库验证 revision；有业务表但无 `alembic_version` 的库自动 `create_all` 补齐 + stamp；全新空库 `create_all` + stamp head。
- **6 项迁移 pytest**（`test_migration.py`）：空库 upgrade head、alembic check、alembic current、stamp + upgrade、数据保留、schema 表完整性。

### Validation（验证）

- `python3 -m pytest tests/ -v`：38 项全部通过（原 32 项 + 6 项迁移）。
- `python3 scripts/smoke_phaseA.py`：全部通过。
- `python3 scripts/demo_phase4.py`：全部通过。

---

## 未发布 - 2026-07-21 — 生产升级 Phase 0.1 回归基线

### Added（新增）

- 新增 32 项 pytest 回归测试，覆盖 Connector Factory、Agent Session 持久化、Episodic Memory、Autonomy Store 与 Autonomy Engine。
- `backend/requirements.txt` 补齐代码和测试实际使用的 `httpx`、`APScheduler`、`pytest` 依赖。

### Fixed（修复）

- 修复 `smoke_phaseA.py` 与 `demo_phase4.py` 直接运行时无法导入 `app` 的路径问题。
- Phase 4 演示显式使用 `mock` 平台，避免默认 Google 无数据造成假失败。

### Validation（验证）

- `python3 -m pytest tests/ -v`：32 项全部通过。
- `python3 scripts/smoke_phaseA.py`：A1 持久化、A2 TikTok 注册、A3 Connector 接地全部通过。
- `python3 scripts/demo_phase4.py`：主动巡检、L0 自动执行、L1 审批、账户禁用告警、冷却去重、策略阈值与调度器全部通过。
- 以上结果仅证明 SQLite/Mock 基线。Google Ads live 因缺少 SDK 与凭证、Meta live 因缺少 SDK 与凭证、TikTok live 因真实 API 尚未实现而阻塞，均未标记为真实链路验收通过。

---

## v1.8.0 - 2026-07-11 — Phase A 真实数据地基（持久化 + 真实渠道 + 真实归因接地）

> 本版本落地「迭代路线图 Phase A」——消除最大工程风险「重启即失」，并把接真实渠道 / 真实归因的代码与护栏备好（Mock 待命，条件一到即切）。这是让 Agent 从"沙盘"走向"真实数据"的地基。

### Added（新增）

- **状态持久化（A1）——双轨存储（内存缓存 + SQLite）**
  - `backend/app/db/base.py`：SQLite 启用 **WAL 日志模式 + `busy_timeout=5000`**，使自有 `SessionLocal` 与请求事务可并发读写（支撑后台 Agent 线程 + 请求线程同时落库）。
  - `backend/app/models/agent_runtime.py`（新增）：5 张持久化表 `AgentSessionDB` / `AgentStepDB` / `EpisodeDB` / `AutonomyAlertDB` / `AutonomyScanDB`，注册进 `Base.metadata`（`main.py` 导入确保 `create_all` 建表）。
  - `session.py`：`AgentSessionStore` 改为双轨——`_cache: Dict` 快路径（SSE 实时推流依赖原地修改）+ SQLite 持久化（`persist()` upsert 会话 + 先删后插步骤；`get/list/delete/clear` 经 DB）。
  - `memory.py`：`EpisodicMemory` 改为双轨——`_eps` 缓存 + `_ensure_loaded()` 从 `EpisodeDB` 载入；`record()` 写库；`clear()` 清表 + 缓存。
  - `autonomy.py`：`AutonomyStore` 改为双轨——`_ensure_loaded()` 载入 scans/alerts；`add_alert()` 写库；审批回写 `_persist_alert()`；`clear()`。
  - `loop.py`：`start/approve/send_message/redirect_run` 经 `_done()` 调 `get_session_store().persist(session)`（try/except 不阻断主流程）；`api/v1/agent.py` 的 `abort`/`redirect`/异常分支补 `persist`。
  - **验收**：重启后端，会话 / 记忆 / 告警全部可读回（消除「重启即失」）。

- **真实渠道 Connector（A2）——代码先行、Mock 待命**
  - `backend/app/services/connectors/tiktok.py`（新增）：`TikTokConnector(BaseConnector)` 完整实现（真实 API 路径预留，当前 `access_token` 缺失自动走 Mock）。
  - `connectors/__init__.py`：注册 `tiktok → TikTokConnector`（`ConnectorFactory` 支持）。Meta / Google Connector 抽象路径同已就绪；Meta 账号解封只需 `config.agent_default_platform="meta"`，上层零改动。

- **真实归因接地（A3）——让 observe / detector / rule_engine 在真实数据上可用**
  - `connectors/base.py`：`BaseConnector` 新增三个 Agent 辅助方法的通用实现：
    - `current_summary()`：聚合 `FactMediaDaily` 最新一天（按 `campaign_id` / `country` 分组），`roi` 从 `FactMMPDaily.roi_d7` 取（有则用之，无则 `None`）；`status` 默认 ACTIVE。
    - `account_status()`：默认 `"ok"`。
    - `simulate_impact()`：返回全 0 的 `ImpactEstimation`（7 维，避免无因果引擎时崩溃）。
  - `MockMediaConnector` 用 `SimulationEngine` 覆盖这三者，提供真实因果实现。
  - **roi 安全保护**：检测器 / 规则引擎对 `roi is None` 跳过（真实数据缺 MMP 归因时不误报 ROI 跌破）。
  - **验收**：Meta / TikTok `execute_pull` 成功、`current_summary` 非空；缺 MMP 时 `roi=None` 不崩溃；`account_status` / `simulate_impact` 不报错；`db=None` 时安全返回 `[]`。

- **开发验证**：`backend/scripts/smoke_phaseA.py`（隔离 DB，13 项断言全 PASS：A1 重启可读回 / A2 tiktok 注册 / A3 真实连接器接地）。

### Changed（变更）

- LLM 路由默认策略、SSE 流式展示等沿用 v1.7.0，无回归。

### 真实 Google Ads 链路升级（A2 收尾，接续 09:11）

- **Google Ads 连接器重写为真实 SDK 实现 + Mock 回退**：`connectors/google.py` 的 `GoogleAdsConnector` 现在在「凭证齐全 且 运行环境已装 `google-ads` SDK」时走真实 Google Ads API（`auth` / `pull` / `update_campaign_status` / `update_campaign_budget` / `update_adset_bid` / `rotate_creative` 均有真实 GAQL mutate + Mock 回退）；凭证缺失、或 SDK 不可用（如本沙箱）时**自动回退 Mock**，保证系统不崩、可测试。
- **凭证解析 `resolve_credentials(platform, db, app_id)`**（新增于 `connectors/__init__.py`）：优先 `connector_credentials` 库表（active + verified），回退 `config.google_*`（`config.google_credentials_dict` 属性聚 6 字段）；均无则 `{}` → Mock。
- **接线**：`api/v1/agent.py` 的 `_make_ctx` 与 `agent_runtime/autonomy.py` 的 `scan` 原传空 `credentials={}`（断线），已改为经 `resolve_credentials` 注入；`connector_service._get_default_credentials` 库表无凭证时为 google 回退 `config.google_*`。
- **默认平台切换**：`config.agent_default_platform` → `"google"`（真实链路就绪；缺凭证自动回退 Mock）。`backend/.env.example` 增补 `GOOGLE_*` 凭证段与说明。
- **沙箱硬约束**：本沙箱无法 `pip install google-ads` / `grpcio`（解压 OOM exit 137），故**真实链路仅能在装了 google-ads 的机器上激活**；代码层面已就绪，填凭证 + 装 SDK 即切换。验证（system python3.14，27 项全 PASS）：7 文件 py_compile 通过、空凭证与「凭证齐全但 SDK 缺失」两种情形均正确回退 Mock、`pull` / 四个写动作不崩、6 关键模块 import 全过。

### Fixed（修复）

- 修复「重启即失」：会话 / 记忆 / 告警流 / 扫描历史从进程内单例升级为 SQLite 持久化（与已落盘的 `StrategyStore` JSON 一并消除所有重启丢失风险）。

### Docs（文档）

- `docs/AGENT_ITERATION_ROADMAP.md`：Phase A（A1 / A2 / A3）标记已完成，状态由「规划稿」改为「执行中」。
- `backend/scripts/smoke_phaseA.py`：Phase A 冒烟测试。

---

## v1.7.0 - 2026-07-11 — ark 推理服务对接 & 流式展示 & 外部检索

> 本版本将智能体控制台从「桩式规则引擎」升级为「真实大模型驱动的流式 Agent」，并完成两项关键能力补全：**可打断**、**外部市场检索**。

### Added（新增）

- **火山引擎方舟（Volcengine Ark）推理服务对接**
  - `config.py` 新增 `ark_api_key / ark_model / ark_base_url`（默认 `https://ark.cn-beijing.volces.com/api/v3`）；`get_llm_providers_config()` 注册 `ark` provider（priority=1，capabilities 含 complex_intent / strategy_analysis / creative_generation / fast_response），并将 `campaign.optimize_batch`、`creative.rotate` 首选路由到 ark（分别降级 claude / gpt4）。
  - `router.py` 新增 `ArkProvider`：基于 `httpx.AsyncClient` 调 `{base_url}/chat/completions`，Bearer 鉴权，解析 `choices[0].message.content` 与 `reasoning_content`；注册进 `provider_classes`；经本地代理出网、超时放宽（`timeout=120~180s`，支持推理模型长思考）。
  - `main.py` lifespan 启动期即 `get_llm_router(...)` 初始化——修复此前 router 仅在 llm 端点命中时才初始化、导致 Agent Loop 永远落到规则兜底的漏洞。
  - 端到端真实调用验证通过（Endpoint `ep-xxxx`，`usage.reasoning_tokens=4243` 证实为推理模型）。

- **智能体思考过程流式展示（SSE）**
  - 后端新增 `GET /agent/sessions/{id}/stream`（`StreamingResponse text/event-stream`）：连接即推 `snapshot` + `status`，之后每 0.3s 增量推 `step` / `status` / `end`，安全上限 ~30min 防连接泄漏；token 经 query 兼容 EventSource（无法自定义 Header）。
  - Agent Loop 后台线程化（`_spawn_loop` + `threading.Thread(daemon=True)`）：`create_session / approve_step / send_message` 立即返回 `status=running`，前端经 SSE 实时拉步骤——解决 axios 10s / Vite 120s 超时导致的「启动失败」。
  - 思考过程实时流式：`AgentStepKind` 新增 `REASONING`（🧠），`ArkProvider.chat_completion` 支持 `stream=True` 逐行解析 OpenAI SSE 的 `reasoning_content` / `content` delta；`loop.py` 累积进 `REASONING` 步骤并实时定稿；前端 `StepView` 新增 `reasoning` 分支（紫色卡片、可滚动、思考中 Spin），SSE `step` 事件按 id 原地合并更新支持文本增长。
  - `vite.config.js` 代理 `/api` 关闭缓冲（`cache-control: no-transform` + `x-accel-buffering: no`），保证 SSE 逐条下发。

- **外部市场检索能力**
  - 新增 `market_research` 工具（Tool Registry，L0 / read）：真实网络检索（经代理 DuckDuckGo）优先 + 内置 `BENCHMARK_DB` 行业基准库兜底，覆盖 品类 × 国家 × 渠道 的 CPI / CPA / ROAS。
  - system prompt 强约束：凡涉及行业基线 / 竞品 CPI / 市场调研 / benchmark，**必须第一步调用 `market_research`**，禁止只依赖平台内部账户数据（带 few-shot）。

- **可打断 & 中途改向（人机协作 steering）**
  - `AgentSession` 新增 `abort_requested` / `pending_redirect` 字段。
  - 思考中可即时「停止」：`loop.py` 在流式 token 间做细粒度 `abort_requested` 检查（下一个 token 即 `aclose()` 退出），终态「已根据您的指示中断」。
  - 运行中发新消息走「改向继续」：`redirect_run()` 中断旧 Loop → 注入「🔀 用户中途改向」步骤 → 以新目标续跑。
  - 新增 API：`POST /agent/sessions/{id}/abort`、`POST /agent/sessions/{id}/redirect`。
  - 前端输入区在 `running` 时显示红色「停止」+「改向继续」按钮。

### Changed（变更）

- LLM 路由默认策略：ark 作为首选 provider，规则引擎仅作最终兜底。
- 智能体控制台数据流：由 2.5s 轮询升级为 SSE 实时流式。

### Fixed（修复）

- 修复「启动智能体」前端报「启动失败」：同步跑完整 Agent Loop 触发前端 axios 10s 超时；改为后台线程 + 立即返回 running。
- 修复方舟 `reasoning_content` 被丢弃（仅抓 `content`），导致看不到 agent 思考过程：补齐流式 Reasoning 链路。
- 修复 `abort` 不即时生效：旧 Loop 卡在单次长推理调用，改为流式 token 级细粒度中断检查。
- 前端热修复：`App.jsx` 补 `import AgentConsole`；`BrainOutlined`（不存在）→ `AimOutlined`；`api.js` 删除重复 `approve` shorthand 避免模块加载白屏。

### Docs（文档）

- `docs/AGENTIC_AD_PLATFORM_UPGRADE.md`：Agentic 平台升级方案（Phase 0~4）。
- `docs/SCALING_UPGRADE.md`：多用户并发扩展实施清单。
- `backend/.env` 加入 `.gitignore`（含方舟 Key，避免误提交）。
---

## v1.6.0 - 2026-07-10

> 本期核心：**Phase 4 主动式自治（Proactive Autonomy）**。Agent 从"人召唤才动"升级为
> "主动守护"——APScheduler 周期巡检账户，检测异常后按 L0-L3 分级自主处置：低风险自动执行、
> 高风险推给你审批、账户被封主动告警。复用 Phase 1~3 全部能力（Tool Registry / 记忆 / 策略），
> 是「进化成熟态」的收口。

### ✨ 新功能

**Phase 4 — 主动式自治（Proactive Autonomy）**：
- 🛡 `backend/app/services/agent_runtime/autonomy.py`：
  - `AnomalyDetector`：从实时账户状态检测 5 类异常——**CPI 飙升 / ROI 跌破阈值 / 素材疲劳 /
    花费异常 / 账户被封（Meta appeal 等）**。ROI 跌破阈值**优先采用 Phase 3 已学策略**
    （`pause_roi_threshold`），回退默认 1.0，体现"处置质量随经验提升"。
  - `AutonomyEngine.scan()`：检测→分级处置。L0（如换素材）**自动执行**；L1/L2（如暂停/调预算）
    生成一条"主动提案"进入**人在环审批队列**（复用 AgentSession/Step 审批流）；仅通知类
    （花费异常、账户被封）**不自动改动**，留给人工判断——主动≠失控。
  - `AutonomyStore`：进程内告警流 + 扫描历史 + 调度配置；同 (异常类型, campaign) **冷却去重**
    （`agent_autonomy_cooldown_scans`），避免每轮重复提案。
  - APScheduler `BackgroundScheduler` 接入（`start_scheduler` / `stop_scheduler`），周期巡检。
- 🌐 `backend/app/api/v1/agent.py` 新增主动自治端点：
  `GET /agent/autonomy/status`（调度状态）、`GET /agent/autonomy/alerts`（告警流）、
  `POST /agent/autonomy/scan`（手动巡检）、`POST /agent/autonomy/toggle`（启停调度）。
  审批端点 `/agent/sessions/{id}/approve` 回写关联告警状态，前端告警流随之更新。
- ⚙️ `config.py` 新增 Phase 4 开关：`agent_autonomy_enabled` / `agent_autonomy_interval_seconds`
  / `agent_autonomy_cooldown_scans` / `agent_fatigue_threshold_days` / `agent_monitor_app_ids`。
- 🖥 `frontend/src/pages/AgentConsole.jsx`：右侧「智能体大脑」升级为 **Tabs**，新增
  「🛡 主动自治」页——监控状态（开/关 + 最近扫描 + 待审批数）、立即巡检、启停调度、
  告警流（待审批内联批准/驳回、查看关联会话）。`frontend/src/api.js` 新增 `autonomy*` 方法。
- 🧪 `scripts/demo_phase4.py`：端到端演示（疲劳自动轮换 / ROI 跌破待审批 / 账户被封告警 / 冷却去重 /
  数据驱动阈值自适应 / 调度器可用性）。
- 🧪 `scripts/test_autonomy_http.py`：真实 HTTP 调用链验证（登录→状态→巡检→审批→告警流→启停）。

### 🔧 架构优化
- ✅ `SimulationEngine` 新增 `account_status` 单例字段（被封/恢复），使"账户被封"状态在多次
  `get_connector` 间持久（修复早期 per-实例丢失的 bug）。`live_summary()` 补 `creative_age` /
  `daily_budget` 字段，供疲劳/花费检测使用。
- ✅ 安全护栏在主动场景同样生效：任何写动作都走 Risk 分级，L1/L2 绝不自动执行。

### ⚠️ 风险与权衡
- 主动自治默认开启（`agent_autonomy_enabled=True`），间隔 120s 仅用于演示；生产建议 ≥300s。
- L0 仅用于低风险动作（当前为换素材）；暂停/调预算/调出价一律人工确认，绝不自动。
- 告警流与会话仓目前为进程内单例，重启即失；生产需落库（与 EpisodicMemory 同批补齐）。

---

## v1.5.0 - 2026-07-10

> 本期核心：**把 Phase 1~3 的后端能力真正接到交互界面**。新增「智能体控制台」页面，
> 优化师可在浏览器里用自然语言给 Agent 下目标、在页面上审批高风险动作、查看记忆/策略/复盘——
> 至此 SmartUA 从"能跑后端的 agent"变成"人能用起来的 agent"。

### ✨ 新功能

**前端对接 Agent Loop（智能体控制台）**：
- 🖥 `frontend/src/pages/AgentConsole.jsx`：**多轮 Agent 对话 UI**
  - 启动目标 → 步骤时间线（💭推理 / 👁观察 / ✅已执行 / ⏳待审批 / 🏁结论）
  - **L1/L2 动作内联审批**（批准→续跑 / 驳回→重新规划），对应后端 `/agent/sessions/{id}/approve`
  - 多轮追问输入框（对应 `/agent/sessions/{id}/message`）
  - 右侧「智能体大脑」面板：**已学策略**（GET `/agent/strategy`）、**经验复盘**（POST `/agent/reflect`）、
    「学习策略」/「重置策略」按钮（对应 `/agent/strategy/learn`、`/agent/strategy/reset`）
- 🔌 `frontend/src/api.js`：新增 `agentAPI`（10 个方法，完整覆盖 `/agent/*` 端点）
- 🧭 `frontend/src/App.jsx` + `components/MainLayout.jsx`：注册 `/agent` 路由与侧边栏「智能体控制台」导航项

### 🐛 修复
- 修复 `_record_execution` 向 `IntentExecution` 误传不存在的 `approval_required` 字段导致
  **审批 L1 动作时 500**（前端点「批准执行」即触发）。该 bug 由端到端 HTTP 调用链验证发现并修复。

### ⚠️ 说明
- 旧 `IntentCenter`（单轮「解析→弹窗→执行」）保留并存，作为遗留流程入口。
- 运行需：后端 `uvicorn main:app --port 8000` + 前端 `npm run dev`（Vite 代理 `/api → :8000`），
  且需先用有效账号登录（Agent 端点均要求 JWT）。

---

## v1.4.0 - 2026-07-10

> 本期核心：把 Phase 2 的「经历」编译成**可学习、可迁移、可持久**的策略参数，
> 让规划器从"硬编码默认值"升级为"数据驱动的策略"——这标志着「进化能力」正式收口
> （经验 → 记忆 → 策略 → 跨账户/跨进程复用）。

### ✨ 新功能

**Phase 3 — 策略自演化（Strategy Self-Evolution）**：
- 🎯 `backend/app/services/agent_runtime/strategy.py`：
  - `StrategyRule` + `StrategyStore`：从 Episode 记忆**挖掘**可学习参数
    （`budget_increase_cap` 加预算增幅上限 / `pause_roi_threshold` 暂停阈值 / `rotate_when_roi_below` 换素材触发下限），
    每条带 `confidence`（依样本量）+ `n_samples` + `source`。
  - `advise(key, default)`：规划器查询接口，无/低置信度时优雅回退默认（不阻塞主流程）。
  - **落盘持久化**（JSON）：解决 Phase 2「重启即失」风险，策略可跨进程、跨账户迁移。
- 🔗 `loop._rule_based_decide`：预算增幅与暂停阈值**优先咨询策略层**，回退 Phase 2 记忆收敛，再回退硬编码默认。
- 🌐 `backend/app/api/v1/agent.py` 新增策略端点：
  `POST /agent/strategy/learn`（记忆→策略+落盘）、`GET /agent/strategy`、`POST /agent/strategy/reset`。
- ⚙️ `config.agent_strategy_path`：策略落盘路径，默认 `backend/data/strategy.json`。
- 🛠 `scripts/demo_phase3.py`：演示「多账户累积 → learn 策略 → 模拟重启+新账户迁移」全链路。

### 🔧 架构优化
- ✅ `_budget` 工具把增幅 `_pct` 透传进 Episode，供策略层挖掘「历史最优增幅」（数据闭环打通）。
- ✅ `AgentContext` 新增 `strategy` 字段，`__init__` 导出 `StrategyStore/StrategyRule/StrategyLearnResult/get_strategy`。

### ⚠️ 风险与权衡
- 当前策略参数为**标量阈值**学习（而非原规划中的"策略 A/B / 元学习优化提示词 / 四层数仓特征"），
  后者仍列为后续增强方向；Phase 3 已交付"可学习策略参数"这一核心收口。
- 策略置信度随样本量线性增长（封顶 1.0 @5 样本），样本过少时仍回退默认，避免过拟合噪声。

---

## v1.3.0 - 2026-07-10

> 本期核心：把 Agent Loop 的"记忆/反思空壳"填上，让系统**记住并复盘、越做越准**
> （Phase 2 记忆 + 反思闭环）。这是把"进化能力"彻底补回来的最后一环。

### ✨ 新功能

**Phase 2 — 记忆与反思（Episodic Memory + Reflection）**：
- 🧠 `backend/app/services/agent_runtime/memory.py`：
  - `Episode`：单次写动作的完整经历（目标 / 动作 / `pre_state` 动作前快照 / `impact_2h/24h/7d_json` / 结果）。
  - `EpisodicMemory`：进程内单例、**跨会话持久**——正是「跨任务学习」的载体（本周 A 账户踩的坑，下周 B 账户仍能调用）。聚合出 per-action 统计，并给出 `suggest_budget_increase_cap()` 等决策修正。
- 🔍 `backend/app/services/agent_runtime/reflection.py`：`Reflector.reflect()` 把 Episode
  复盘为「自然语言摘要 + 启发式规则」（止损 / 预算边际递减→增幅收敛≤10% / 素材疲劳短期提振 /
  提价伤 ROI），规则引擎兜底、可选 LLM 增强。
- 🔁 **闭环关键**：`loop._rule_based_decide` 的预算分支 consult 记忆，当历史加预算 7d 平均 ΔROI
  转负时**自动收敛增幅**；`AgentLoop.reflect()` 新增复盘入口。
- 🌐 `backend/app/api/v1/agent.py`：新增 `POST /agent/reflect`（全局复盘）、
  `POST /agent/sessions/{id}/reflect`（按会话复盘）。
- 🛠 `scripts/demo_phase2.py`：场景A 多目标执行→沉淀 Episode；场景B 复盘提取规则；场景C
  新账户+类似目标→规划器 consult 记忆把预算增幅从 +20% 收敛到 +10%（验证"越做越准"）。

### 🔧 架构优化
- ✅ 写动作执行后由 `tools._write` **自动沉淀 Episode**（`AgentContext.memory` 注入），对上层透明。
- ✅ `config.agent_reflection_enabled`：可一键关闭记忆/反思（降级到 Phase 1 行为）。

### ⚠️ 风险与权衡
- 记忆目前为进程内单例，重启即失；生产需落库为 `EpisodicMemory` 表（与 `ActionLog` 互为补充：
  审计看"做了什么"，记忆看"做得好不好、下次怎么改"）。
- 反思规则为确定性抽取（可解释、可复现）；接入 LLM 生成自然语言复盘为可选增强，未阻塞主流程。

---

## v1.1.0 - 2026-07-10

> 本期核心：在 Meta 账户被封（今日新号直接触发 appeal）的现实约束下，先把"进化能力"缺失的
> **数据土壤**补回来——用有状态因果模拟引擎替代无状态随机 mock，使"动作→指标"存在真实因果链，
> 为 Agent Loop（Phase 1）与记忆/反思闭环（Phase 2）提供可复现、可量化、可被 Agent 动作影响的
> 连续数据。

### ✨ 新功能

**Agentic 升级评审与路线图**：
- 📄 `docs/AGENTIC_AD_PLATFORM_UPGRADE.md`：澄清 SmartUA 当前定位是
  "**意图驱动的投放控制台**"而非 agentic platform；给出 Phase 0~4 升级方案
  （真实闭环 → Agent Loop → 记忆反思 → 策略自演化 → 主动自治）。
- 明确核心架构思想：**平台做"身体+护栏"，Agent Loop 做"大脑"，Tool/Skill Registry 做桥接**。

**Phase 0 — 真实执行数据土壤（Mock 因果模拟引擎）**：
- 🧪 `backend/app/services/simulation/engine.py`：有状态因果模拟引擎。预算饱和（边际 ROI 递减）、
  素材疲劳、换素材短期提振、提价伤 ROI 等因果效应均可解释、可复现（seed）、可量化。
- 🔌 `backend/app/services/connectors/mock_media.py`：注册为 `mock` 渠道的 `MockMediaConnector`。
  写操作**真实修改模拟状态**，拉取历史会反映动作效果 → 形成因果闭环。
- 🔁 `ConnectorFactory` 新增 `"mock"` 渠道。Meta 账户恢复后只需把工厂里的 `"mock"` 换回 `"meta"`，
  上层 Agent Loop 与意图引擎零改动（Connector 抽象的价值）。
- 🛠 `scripts/demo_mock_media.py`：独立验证"暂停/加预算/换素材"三类动作的因果效果。

### ⚠️ 风险与权衡
- 本期仅补数据土壤；Agent Loop（规划/ReAct/多轮/人在环）为 Phase 1（见 v1.2.0），
  记忆/反思为 Phase 2（见 v1.3.0）。
- `mock` 渠道为开发期数据土壤，所有"真实执行"均为确定性模拟，不消耗真实预算；
  回采影响基于日粒度模拟，2h 影响为线性外推近似。

---

## v1.2.0 - 2026-07-10

> 本期核心：把"单轮解析器"升级为"会规划、会多轮、会等人在环确认"的 **Agent Loop（Phase 1）**，
> 进化引擎就位。（记忆/反思空壳仍留待 v1.3.0。）

### ✨ 新功能

**Phase 1 — Agent Loop（进化的引擎）**：
- 🧠 `backend/app/services/agent_runtime/`：
  - `session.py`：多轮会话状态（目标 / 步骤 / 待审批项 / 上下文），内存会话仓库。
  - `tools.py`：Tool/Skill Registry，把"观察/筛选/预测影响/暂停/调预算/调出价/换素材/报表"
    封装为带 L0-L3 风险元数据的工具；写工具真实执行并回填 `impact_2h/24h/7d_json`。
  - `loop.py`：ReAct 风格循环 `think → select tool → (execute | propose) → observe → think again`；
    **规则引擎兜底**（无 LLM 自动降级）+ LLM 规划路径；**L1/L2 高风险动作走人在环审批**，
    批准后续跑，驳回后重新规划。
- 🌐 `backend/app/api/v1/agent.py`：多轮 Agent 对话 API
  （`POST /agent/sessions`、`.../approve`、`.../message`、`GET /agent/sessions/{id}`）。
- 🛠 `scripts/demo_agent_loop.py`：模拟"模糊目标 → 拆多步 → L1 审批 → 真实执行 → 观察 →
  回采影响 → 终态"的完整闭环。

### 🔧 架构优化
- ✅ LLM 解耦 + 优雅降级原则贯穿 Agent Loop（无 API Key 时走规则引擎，不报错）。
- ✅ 真实执行与审计解耦：无 DB / 无第三方包时 demo 仍可运行（审计写库为可选项）。
- ✅ `BaseConnector.apply_action(action, entity_id, **params)` 通用写动作分发器：Agent Loop
  的写工具统一调用它（而非具体连接器方法），与连接器彻底解耦；Meta 接回时上层零改动。
- ✅ `SimulationEngine.live_summary()`：基于实时状态（而非历史快照）的账户概览，使 Agent
  能在动作后立即看到最新状态（如暂停后该 campaign 立即显示 PAUSED、spend=0），避免基于
  过期快照重复提议。

### ⚠️ 风险与权衡
- 本期 Agent Loop 的"记忆/反思"仍是空壳（v1.3.0 待做）；多轮会话目前为进程内内存仓库，
  重启即失（生产需落库 + 接 Episodic Memory）。
- `mock` 渠道为开发期数据土壤，所有"真实执行"均为确定性模拟。

---

## v1.0.0 - 2026-06-28

### ✨ 新功能

**前端页面**：
- 🎯 Dashboard 投放大盘页面完整实现
  - 4个统计卡片（今日花费、整体ROI、安装量、活跃Campaign）
  - ROI 趋势图表（ECharts）
  - 告警列表（支持查看详情、标记已处理）
  - Campaign 数据表格（支持排序、过滤）
  - 告警详情弹窗（含影响分析、建议动作）

- 📊 Campaign 详情页（四 Tab 结构）
  - 概览：Campaign 统计卡片 + 趋势图 + AdGroup 列表
  - AdGroup 详情：AdGroup 统计 + 广告列表表格
  - 广告创意：创意卡片网格 + 素材优化操作
  - 设置：Campaign 完整配置信息

- 🎬 素材管理页面
  - 4个统计卡片（素材总数、总花费、平均ROI、总安装量）
  - 素材列表表格（支持按类型、设计师、状态筛选）
  - 素材详情弹窗（含效果指标、关联 AdGroup）
  - 类型标签页筛选（全部/视频/图片/试玩/轮播）

**后端 API**：
- 🔐 完整认证系统
  - JWT Token 登录
  - RBAC 权限模型（admin/optimizer/analyst/finance）
  - 用户-应用绑定（多租户）

- 📦 Campaign 完整 CRUD
  - Campaign → AdGroup → Ad 嵌套返回
  - 支持按状态、媒体、国家筛选
  - 所有数值字段 Decimal 精确计算

- 🎨 Creative 素材管理 API
  - 完整 CRUD
  - 支持标签、设计师、类型管理
  - 表现分 + 趋势指标

- ⚠️ 告警系统 API
  - ROI 下降、CPI 上升、花费异常告警
  - 告警详情含影响 Campaign 列表
  - 建议动作自动生成
  - 标记已处理接口

### 🔧 架构优化

**数据一致性**：
- ✅ 前端无本地 Mock 数据原则落地
- ✅ 所有 Demo 数据在数据库初始化层生成
- ✅ 四层实体状态标签体系统一
- ✅ 数值字段安全渲染标准化（Number() + isNaN()）

**API 设计**：
- ✅ Campaign API 嵌套返回完整层级，避免 N+1 请求
- ✅ Decimal 类型统一序列化为字符串，前端安全转换
- ✅ 空状态友好处理（草稿 Campaign、空 AdGroup 等）

**开发工具**：
- ✅ 数据库一键初始化脚本 `init_db.py`
- ✅ 密码重置工具 `reset_password.py`
- ✅ 告警数据初始化脚本 `init_alerts.py`

### 📝 文档

- ✅ README.md 快速开始指南更新
- ✅ ARCHITECTURE.md 系统架构设计文档
- ✅ API_REFERENCE.md API 参考文档
- ✅ CONNECTOR_DESIGN.md 连接器设计文档

### 🐛 Bug 修复

- 修复前端白屏问题：API 数值字段安全处理
- 修复 Campaign 详情页空白状态：空 AdGroup 友好展示
- 修复语法错误：JSX 括号匹配问题
- 修复数值渲染错误：NaN 统一显示为 `-`

### 📦 技术栈

**前端**：
- React 18 + Vite 5
- Ant Design 5
- ECharts 5
- Axios

**后端**：
- FastAPI 0.109
- SQLAlchemy 2.0
- Pydantic 2.0
- SQLite (开发) / PostgreSQL (生产)
- Passlib (密码哈希)
- JWT (认证)

---

## v0.2.0 - 2026-06-27

### ✨ 新功能

- 连接器系统骨架设计
- 意图引擎骨架实现
- 四层数仓架构设计
- 操作安全分级矩阵设计

---

## v0.1.0 - 2026-06-27

### ✨ 新功能

- 初始项目骨架
- 系统架构设计文档
- API 路由骨架

---

## 开发路线图（对齐 Agentic 升级 Phase 0~4）

### ✅ v1.1.0 (已完成, 2026-07-10)
- [x] 定位评审与 Phase 0~4 路线图
- [x] Mock 因果模拟引擎 + `mock` 渠道（替代无状态随机 mock）
- [x] Agent Loop（规划 + ReAct + 多轮 + 人在环）

### ✅ v1.2 / v1.3 / v1.4 / v1.5 (已完成) — Phase 1~3 + 前端对接
- [x] Phase 1 Agent Loop（规划 + ReAct + 多轮 + 人在环）
- [x] Phase 2 记忆与反思（Episodic Memory + Reflection）
- [x] Phase 3 策略自演化（StrategyStore 落盘、跨账户迁移）
- [x] 前端「智能体控制台」对接（多轮对话 / 审批 / 记忆 / 策略 / 复盘）

### ✅ v1.7.0 (已完成, 2026-07-11) — Ark 推理对接 & 流式展示 & 外部检索
- [x] 火山方舟 Ark 推理服务对接（router provider + 启动期初始化）
- [x] SSE 实时流式思考过程（reasoning_content 逐 token 呈现）
- [x] 外部市场检索 market_research 工具（真实检索 + 基准库兜底）
- [x] 可打断 & 中途改向（abort / redirect 人机协作 steering）

### ✅ v1.8.0 (已完成, 2026-07-11) — Phase A 真实数据地基
- [x] 状态持久化（A1）：会话 / 记忆 / 告警流 双轨存储落库 SQLite，重启不丢
- [x] 真实渠道 Connector（A2）：TikTokConnector 实现 + 注册；Meta / Google 路径就绪，Mock 待命
- [x] 真实归因接地（A3）：BaseConnector.current_summary / account_status / simulate_impact 通用实现，缺 MMP 时 roi=None 安全
- [x] smoke_phaseA.py 13 项断言全 PASS

### ✅ v1.6.0 (已完成, 2026-07-10) — Phase 4 主动式自治
- [x] APScheduler 周期巡检 + 5 类异常检测（CPI/ROI/疲劳/花费/账户被封）
- [x] 分级处置：L0 自动执行、L1/L2 人在环审批、仅通知不自动改动
- [x] 主动汇报（告警流 + 监控面板）+ ROI 阈值数据驱动（复用 Phase 3 策略）
- [x] 冷却去重，避免重复打扰

### ⏳ v2.0 (远期) — 生产化与增强
- [x] Episodic Memory / 会话仓 / 告警流落库（已在 v1.8.0 完成：双轨 SQLite 持久化，重启不丢）
- [ ] 主动汇报升级：日报 / 异动摘要推送（邮件 / 企微 / 飞书）
- [ ] Meta 账户恢复后切回真实 Connector（上层零改动）
- [ ] 四层数仓 ODS/DWD/DWS/ADS + ClickHouse 加速
- [ ] 策略 A/B + 元学习（自优化提示词/启发式）
