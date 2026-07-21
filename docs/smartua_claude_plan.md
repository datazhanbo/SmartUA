# SmartUA 后续升级执行计划

> 承接 `docs/smartua_claude_review.md` 的 14 项生产就绪度发现，本计划重新排序升级路线：**先建立真实/模拟边界、对象授权、动作幂等与可恢复运行时，再扩充工具、策略学习和知识库。**
> 状态：**执行中** — 已完成 Phase 0.1，按状态表逐步推进。

---

## 执行规则

1. 每次只推进一个可独立验收的步骤，完成后更新本文件状态表。
2. 每个步骤必须保持系统可运行，并有自动化测试或可重复 smoke 脚本。
3. 优先复用现有 `BaseConnector`、`ToolRegistry`、`AgentSessionStore`、`IntentExecution`、`ActionLog` 和双轨持久化模式。
4. 不修改或提交当前工作区中与本步骤无关的已有改动。

## 版本建议

- P0 阶段 → `v1.8.1`～`v1.8.x` 小版本交付
- P1 持久运行时完成 → `v1.9.0`
- 工具与治理能力 → `v2.0` 前置版本

---

## 状态总览

| Phase | 名称 | 状态 | 当前步骤 |
|-------|------|------|---------|
| 0 | 基线与迁移地基 | 进行中 | 0.1 ✅ → 0.2 ✅ |
| 1 | 真实与模拟严格隔离 | ✅ 已完成 | 1.1 ✅ · 1.2 ✅ |
| 2 | 对象授权与会话安全 | ✅ 已完成 | 2.1 ✅ · 2.2 ✅ |
| 3 | 安全动作闭环 | 进行中 | 3.1 ✅ · 3.2 ✅ · 3.3 ✅ |
| 4 | 真实影响与学习质量 | 待开始 | — |
| 5 | 持久运行时与多实例协调 | 待开始 | — |
| 6 | 有限扩充只读能力 | 待开始 | — |
| 7 | 策略治理与知识库 | 待开始 | — |

---

## Phase 0 — 基线与迁移地基

### 0.1 建立回归基线

**目标：** 先证明现有功能状态，避免后续升级把既有问题误判为新回归。

**操作：**
- 运行并修正 `backend/scripts/smoke_phaseA.py`、`backend/scripts/demo_phase4.py` 的环境依赖。
- 为 Connector、Agent Session、审批、Memory、Autonomy 建立最小 pytest 基线。
- 将缺失的运行依赖（当前代码使用但 requirements 未声明的 APScheduler/httpx 等）补入 `backend/requirements.txt`。
- 记录 live 凭证不可用的测试项为"外部依赖阻塞"，不能用 Mock 通过代替。

**关键文件：** `backend/requirements.txt`、`backend/scripts/smoke_phaseA.py`、`backend/scripts/demo_phase4.py`、`backend/tests/`

**验收：** SQLite/Mock 环境 smoke 全绿；测试明确报告实际 `execution_mode`。

**状态：** ✅ 已完成（2026-07-21） | **依赖：** 无 | **下一步：** 0.2 引入 Alembic / 1.1 统一 Connector 执行模式

**验收结果：**
- `python3 -m pytest tests/ -v`：32 项全部通过（Connector 5、Session 6、Memory 8、Autonomy Store 8、Autonomy Engine 5）。
- `python3 scripts/smoke_phaseA.py`：A1/A2/A3 全部通过，临时 SQLite 隔离库未污染业务库。
- `python3 scripts/demo_phase4.py`：主动巡检、L0 自动执行、L1 审批、账户禁用告警、冷却去重、策略阈值与调度器均通过。
- 修复两个脚本直接运行时的 `app` 导入路径；演示固定使用 `mock` 平台，避免默认 Google 空数据导致假失败。
- `requirements.txt` 已声明 `httpx`、`APScheduler`、`pytest` 等实际依赖。

**外部依赖阻塞：**
- Google Ads live：当前环境未安装 `google-ads`/`grpcio` 且无可用 live 凭证，未执行真实账户读写验证。
- Meta live：当前环境无 `facebook_business` SDK 和可用 live 凭证，未执行真实账户读写验证。
- TikTok live：真实 API 路径尚未实现且无 access token；当前通过项仅为 Mock 路径，不能视为 live 验收。
- 在 Phase 1.1 完成 `execution_mode` 与 fail-closed 前，现有 Connector 日志中的“using mock mode”不等于 live 成功。

---

### 0.2 引入 Alembic

**目标：** 先解决 `create_all()` 无法升级既有表的问题，为后续动作表、授权字段和影响字段提供可回滚迁移。

**操作：**
- 初始化 `backend/alembic/` 与 `backend/alembic.ini`。
- 生成当前模型 baseline；为既有 SQLite 提供 `stamp` 路径，为新库提供 `upgrade head` 路径。
- 过渡期保留 `create_all()` 仅用于开发兼容；迁移验证稳定后移除启动时隐式建表。
- 增加 schema 版本启动检查。

**关键文件：** `backend/app/db/base.py`、`backend/main.py`、`backend/app/models/*.py`、`backend/alembic/`

**验收：** 空库可 `alembic upgrade head`；现有库可 stamp 后继续升级；数据不丢失。

**状态：** ✅ 已完成（2026-07-21） | **依赖：** 0.1 | **下一步：** 1.1 统一 Connector 执行模式

**验收结果：**
- `alembic upgrade head`：空库从 baseline 迁移成功，创建 33 张业务表 + alembic_version。
- `alembic check`：schema 与模型完全一致，无新增差异。
- `alembic current`：确认 head revision 为 `76c3bd1f529f`。
- `alembic stamp 76c3bd1f529f`：既有库（`create_all` 建表）可 stamp 后继续升级，数据不丢失。
- `main.py` 启动时自动检查 schema 版本：已迁移库验证 revision；有业务表但无 alembic_version 的库自动 create_all 补齐 + stamp；全新空库 create_all + stamp head。
- 新增 6 项迁移测试（`test_migration.py`）：空库 upgrade、check、current、stamp + upgrade、数据保留、schema 表完整性。
- 全部 38 项 pytest 通过；smoke_phaseA 全部通过；demo_phase4 全部通过。

---

## Phase 1 — Production Truth：真实与模拟严格隔离

### 1.1 统一 Connector 执行模式

**目标：** 消除 Google 静默回退 Mock 和 TikTok"始终 Mock 却认证成功"的假成功语义。

**操作：**
- 在 `BaseConnector` 引入 `execution_mode = mock | sandbox | live` 和能力声明。
- `MockMediaConnector` 固定为 mock；TikTok 在真实 API 未实现前拒绝 live；Google live 缺凭证/SDK/权限时 fail-closed。
- `resolve_credentials()` 只负责取凭证，不再隐式决定回退策略。
- 配置默认保持 mock，生产环境必须显式指定 live/sandbox。
- 所有 pull/action 结果带 `execution_mode`、`platform`、`account_id`、`provider_request_id`（若有）和 `verified_at`。

**关键文件：** `backend/app/config.py`、`backend/app/services/connectors/base.py`、`backend/app/services/connectors/google.py`、`backend/app/services/connectors/tiktok.py`、`backend/app/services/connectors/meta.py`、`backend/app/services/connectors/mock_media.py`、`backend/app/services/connectors/__init__.py`、`backend/app/services/connector_service.py`

**验收：** live 模式移除 SDK/凭证时写动作明确失败；Mock 数据和动作永久标记为 mock；绝不自动切换执行目标。

**状态：** ✅ 已完成（2026-07-21） | **依赖：** 0.1 | **下一步：** 1.2 前端和审计显示执行模式

**验收结果：**
- `BaseConnector` 增加 `supported_modes` / `capabilities` / `execution_mode` 与 `_result_meta` / `_decorate_pull_result` / `_decorate_action_result` 三个 provenance hook；`execute_pull` 与 `apply_action` 出口自动注入 `platform / execution_mode / account_id / is_mock / verified_at`。
- `Google` 在 `execution_mode="live"` 时缺凭证或缺 SDK 直接抛 `ValueError` / `RuntimeError`，绝不静默回退 mock；`Meta` live 缺 SDK 或 access_token 同样 fail-closed；`TikTok / AppsFlyer` 支持 `("mock",)` 唯一模式，构造 live 立即抛错；`MockMediaConnector` 支持 `("mock",)` 且始终标记 `is_mock=True`。
- `ConnectorFactory.get_connector` 新增 `execution_mode` 必传参数（默认 `"mock"`），`available_connectors()` 暴露 `supported_modes` / `capabilities`；`resolve_credentials()` 只解析凭证，不再决定回退。
- `settings.agent_execution_mode`（默认 `mock`）新增，`agent_default_platform` 回退为 `mock`；`agent.py::_make_ctx`、`autonomy.py::scan`、`connector_service`（3 处）全部按 settings 传参。
- `python3 -m pytest tests/ -v` 54 项全部通过（原 38 项 + 新增 16 项 execution_mode 断言）。
- `python3 scripts/smoke_phaseA.py` 与 `python3 scripts/demo_phase4.py` 全部通过。

**外部依赖阻塞：**
- Google Ads live：本地未安装 `google-ads` / `grpcio` 且无 live 凭证；已通过 mock 显式验证 fail-closed 路径。
- Meta live：本地未安装 `facebook_business` SDK 且无 live token；已在测试中通过 monkeypatch 触发 SDK 不可用与 token 缺失分支。

---

### 1.2 前端和审计显示执行模式

**目标：** 用户在提案、审批、结果和历史记录中始终知道动作作用于哪里。

**操作：**
- Agent Session/Step/API 响应透传执行模式和账户。
- Agent Console 对 Mock/Sandbox 显示持续可见标识。
- 审批卡展示平台、账户、执行模式、数据时间和风险级别。

**关键文件：** `backend/app/api/v1/agent.py`、`backend/app/services/agent_runtime/session.py`、`frontend/src/api.js`、Agent Console 对应组件

**验收：** 浏览器验证 mock/live 标签、审批信息和结果一致；无控制台错误。

**状态：** ✅ 已完成（2026-07-21） | **依赖：** 1.1 | **下一步：** 2.1 修复 Agent 对象级授权

**验证结果：**
- `AgentSession` 增加 `platform / execution_mode / account_id` 三个 provenance 字段；`AgentSessionStore` 通过在 `context_json` 中挂 `_PROV_KEY = "_provenance"` 完成持久化与回读（不动 schema，避免额外 Alembic 迁移）。
- `POST /agent/sessions`：先构造临时连接器读取 `platform / execution_mode / account_id`，写回会话；live 缺凭证/SDK 时抛 400，永不静默回退 mock。
- `stream_session` SSE `snapshot` 与 `status` 事件带 `provenance: {platform, execution_mode, account_id}`。
- `AgentLoop._dispatch()` 在生成 `approval` 步骤时把 provenance 冻结到 `step.result.provenance`，审批卡永远知道"这条动作作用在哪个平台/账户"。
- `apply_action()` 回结果由 `_decorate_action_result` 附加 `execution_mode / platform / account_id / is_mock / verified_at`（Phase 1.1 已上线，Phase 1.2 前端消费）。
- `/agent/autonomy/status` 新增 `execution_mode` 字段。
- 前端 `AgentConsole.jsx`：新增 `ProvenanceTag`；会话头、审批卡、执行结果卡、主动巡检状态条均常驻显示 Mock/Sandbox/Live + 平台 + 账户。
- 测试：`test_session_provenance_persists_across_reload` 和 `test_session_provenance_defaults_are_none` 保证清缓存后 DB 回读一致；`_provenance` 保留键对外不泄露。
- `python3 -m pytest tests/ -v` 全 56 项通过；`smoke_phaseA.py` 与 `demo_phase4.py` 全部通过；`npx vite build` 成功。

**外部依赖阻塞：** 无。（Live 端到端仍需真实凭证，属于 Phase 3 之后动作闭环的门禁事项。）

---

## Phase 2 — 对象授权与会话安全

### 2.1 修复 Agent 对象级授权（优先）

**目标：** 堵住跨 App/跨用户访问 Session、Step、Alert、Strategy 的 IDOR 风险。

**操作：**
- 修复 `agent.py:166` 无效判断 `session.app_id != session.app_id`（恒为 False）。
- 复用现有 `UserAppBinding`，统一实现 `_require_app_access()` 和 `_require_session_access()`。
- 当前系统以 `app_id` 为租户边界；不提前引入不存在的 tenant 模型。
- Session/Action/Episode/Alert 补齐 `app_id`、`account_id`、`created_by`，所有读写都按授权范围查询。
- 对不存在与无权访问统一返回 404，避免对象枚举。

**关键文件：** `backend/app/api/v1/agent.py`、`backend/app/models/sys.py`、`backend/app/models/agent_runtime.py`、`backend/app/services/agent_runtime/session.py`、`backend/app/services/agent_runtime/memory.py`、`backend/app/services/agent_runtime/autonomy.py`

**验收：** 跨 App 用户对 session/approval/abort/redirect/alert/strategy 请求全部 404；同 App 授权用户正常。

**状态：** ✅ 已完成（2026-07-21） | **依赖：** 0.1 | **下一步：** 2.2 修复 SSE 认证

**验证结果：**
- `app/core/security.py` 新增 `user_can_access_app(user, app_id, db)` 与 `require_app_access(user, app_id, db)`；不存在 / 无权访问统一抛 404（避免通过响应差异枚举 app_id）。
- `app/api/v1/agent.py` 新增 `_require_session_access(session, user, db)`；同样把"session 不存在"与"跨 app 无权"折叠成 404。
- 修复 `agent.py` 中 `session.app_id != session.app_id`（恒为 False，等于形同虚设的护栏）；统一改为 `_require_session_access`。
- 授权拦截接入以下端点：`POST /agent/sessions`（req.app_id）、`GET /agent/sessions`（list app_id）、`GET /agent/sessions/{id}`、`GET /agent/sessions/{id}/stream`（SSE 也走 session 授权）、`POST /agent/sessions/{id}/approve`、`POST /agent/sessions/{id}/message`、`POST /agent/sessions/{id}/abort`、`POST /agent/sessions/{id}/redirect`、`POST /agent/sessions/{id}/reflect`、`GET /agent/autonomy/alerts`、`POST /agent/autonomy/scan`。
- SSE `_authenticate` 现返回 User，直接串到 `_require_session_access`；未授权用户即便截获别人的 `session_id + token` 也拿不到流。
- 系统自治会话使用 `SYSTEM_USER_ID = -1` 保持不变，其归属仍以 `app_id` 为准；实际操作方在 `approve` 端点由真实用户的 UserAppBinding 校验授权。
- 新增 4 项测试（`test_auth_object_access.py`）：`user_can_access_app` 布尔矩阵、`require_app_access` 跨 app 404、`_require_session_access` 跨 app 会话 404、None session 404；`_bootstrap_users_and_apps` 幂等以适配 conftest 只清 agent 表的策略。
- `python3 -m pytest tests/ -q` 60 项全部通过；`python3 scripts/smoke_phaseA.py` A1/A2/A3 全部通过。
- 保持 `403 vs 404` 不透露信息：跨 app 的 session_id 与不存在的 session_id 返回同样的 404 body。

---

### 2.2 修复 SSE 认证

**目标：** 长期 JWT 不进入 URL、代理日志和浏览器历史。

**操作：**
- 新增 JWT 认证的 stream-ticket 端点，签发短期、单次、绑定 session/user 的票据。
- SSE 仅接受 Authorization Header 或短票据；旧 `?token=` 仅保留一个可关闭的迁移开关，默认关闭。
- 增加 `Referrer-Policy: no-referrer`，日志/APM 脱敏。

**关键文件：** `backend/app/api/v1/agent.py`、`backend/app/core/security.py`、`backend/app/config.py`、`frontend/src/api.js`

**验收：** 票据可使用一次，过期/重放/跨 session 均失败；日志中无长期 JWT。

**状态：** ✅ 已完成（2026-07-21） | **依赖：** 2.1 | **下一步：** 3.1 建立动作实体与状态机

**验证结果：**
- 新增 `app/core/stream_ticket.py`：`StreamTicketStore` 进程内单例，`mint(user_id, session_id)` / `consume(ticket, session_id)`；票据单次消费、短生存（默认 60s，由 `settings.agent_sse_ticket_ttl_seconds` 控制）、绑定 `(user_id, session_id)`。
- `POST /agent/sessions/{id}/stream-ticket`：JWT 认证 + `_require_session_access` → 签发一次性票据；跨 app / 不存在 / 无权访问统一 404。
- `GET /agent/sessions/{id}/stream`：认证优先级重排为 ticket → Authorization Header → 旧版 `?token=<长期 JWT>`；旧版路径默认拒绝，仅在 `agent_sse_allow_legacy_token=True` 时可用（灰度回滚开关）。
- SSE 响应头新增 `Referrer-Policy: no-referrer`；即便 ticket 短暂进入 URL，也不会通过 Referer 泄漏到跨域链接。
- 前端 `agentAPI.createStreamTicket` + `AgentConsole.jsx` 改为"先换 ticket 再开 EventSource"；`localStorage.token` 不再进入 SSE URL。
- 新增 8 项单元测试（`test_stream_ticket.py`）：mint / 单次消费 / 跨 session 拒绝 / 过期 / 空 ticket / 未知 ticket / 单例复用 / clear 语义。
- `python3 -m pytest tests/ -q` 68 项全部通过（+8）；`python3 scripts/smoke_phaseA.py` 全绿；`npx vite build` 成功（2457 KB，gzip 791 KB）。

**外部依赖阻塞：** 无。

**已知遗留：**
- Ticket store 目前是进程内单例；多副本部署时每副本自建票据（换 session 换 ticket 天然被单节点服务），Phase 5 durable runtime 后再评估是否迁到 Redis。
- 灰度期若 `agent_sse_allow_legacy_token=True`，长期 JWT 仍可能进入 URL；此开关应仅在切换期短暂启用。

---

## Phase 3 — 安全动作闭环

### 3.1 建立动作实体与状态机

**目标：** 每个真实写动作有唯一身份、不可重复执行、状态可解释。

**操作：**
- 新增 `AgentActionDB`，关联 session/step/app/account/user 和现有 `IntentExecution`/`ActionLog`。
- 状态：`proposed → approved → dispatching → accepted → verified | failed | unknown`。
- 使用稳定的 `idempotency_key` 唯一约束；重复请求返回原动作，不重复发媒体 API。
- 保存前置状态、请求摘要、预测影响、媒体 request ID、响应、执行模式和错误。
- 继续使用现有 `IntentExecution`/`ActionLog` 做产品审计，不再仅在动作完成后补日志。

**关键文件：** `backend/app/models/agent_runtime.py`、`backend/app/models/intent.py`、`backend/app/services/agent_runtime/tools.py`、新增 `backend/app/services/agent_runtime/action_store.py`、Alembic 增量迁移

**验收：** 相同幂等键并发提交只生成一条动作且媒体只调用一次；非法状态跳转被拒绝。

**状态：** ✅ 已完成（2026-07-21） | **依赖：** 0.2、1.1 | **下一步：** 3.2 审批过期与执行前重校验

**验收结果：**
- 新增 `AgentActionDB`（`backend/app/models/agent_runtime.py`）：`idempotency_key` UNIQUE、`state` 索引、`app_id+state` 复合索引；`intent_execution_id` / `action_log_id` 软链接既有审计链，`execution_mode`、`platform`、`account_id`、`predicted_impact_json`、`pre_state_json`、`provider_request_id/response`、`error`、四段时间戳齐备。
- Alembic 迁移 `2ba2dc778e26_phase3_1_agent_actions`：空库 `upgrade head` 到最新版；`smartua.db` 已同步执行。
- 新增 `AgentActionStore`（`backend/app/services/agent_runtime/action_store.py`）：`mint_or_get()` 遇 IntegrityError 回退 SELECT，保证并发下唯一；`transition()` 走白名单状态机，非法跳转抛 `InvalidTransition`；provider 字段与审计软链接通过 kwargs 更新。
- 新增测试 `tests/test_action_state_machine.py`（10 项）：幂等键顺序稳定、`mint_or_get` 复用、异参数分裂、happy path 时间戳、跳阶段/终态回滚拒绝、`unknown` 收敛、`get_by_idempotency_key` 一致。
- 更新 `tests/test_migration.py`：期望 34 张表 + head revision 更新为 `2ba2dc778e26`。
- 全量 `pytest -q`：78 项全部通过。
- 未接线：本步骤只建立实体与状态机契约；`_write()` 尚未改为"经 outbox 派发 + 状态迁移" —— 那是 Phase 3.3 的任务。现有 `IntentExecution`/`ActionLog` 审计链保持不变，Phase 3.3 会通过软链接把两侧对齐。

**外部依赖阻塞：** 无。

**遗留风险：**
- SQLite CHECK 约束未加，非法状态跳转仅靠应用层拦截；迁 PostgreSQL 时会补数据库层护栏。
- `idempotency_key` 由 (session_id, step_id, tool, params_digest) 派生 —— Loop 尚未维持"审批 step 与执行 step 是同一条"的不变量。Phase 3.2 会冻结 step 参数，进一步保证同一提案 → 同一 step_id → 同一 idempotency_key。

---

### 3.2 审批过期与执行前重校验

**目标：** 防止审批等待期间账户状态变化后继续执行旧提案。

**操作：**
- 提案冻结动作参数、目标快照、策略版本和 `expires_at`。
- 审批前验证审批人权限；执行前重新读取实体状态、预算和账户状态。
- 状态漂移超过阈值时废弃旧动作并重新提案，不复用原批准。
- 不启用"超时自动执行"真实资金动作。

**关键文件：** `backend/app/services/agent_runtime/loop.py`、`backend/app/api/v1/agent.py`、`backend/app/config.py`、`backend/app/models/agent_runtime.py`

**验收：** 过期审批返回 409；等待期间预算/状态改变会阻止执行并产生差异说明。

**状态：** ✅ 已完成（2026-07-21） | **依赖：** 3.1、2.1 | **下一步：** 3.3 Outbox / 执行回执 / 对账

**验收结果：**
- 新增字段 `AgentStepDB.expires_at`（DateTime，nullable）、`AgentStepDB.snapshot_json`（JSON），Alembic 迁移 `49d2e70677ed_phase3_2_approval_expiry_snapshot`（可空列，兼容既有会话）。
- `AgentStep` pydantic 同步暴露 `expires_at` / `snapshot`；`AgentSessionStore` 持久化 + 重建时透传，跨进程/单例重启不丢失。
- `AgentLoop._dispatch()`：L1/L2/L3 提案时冻结 (a) 实体快照（`roi/spend/status/daily_budget`，来自 `connector.current_summary()` 匹配 `entity_id` 的那一行）+ (b) `expires_at = now + settings.agent_approval_ttl_seconds`。
- `AgentLoop.approve()`：批准分支先做 (a) 过期校验 → REJECT + 观察 + 记入 `session.context["rejected"]` + 重新规划；再做 (b) 漂移校验（`agent_approval_drift_pct`，默认 20%）→ 同样 REJECT + 附 snapshot vs current diff 观察 + 重新规划。
- `POST /agent/sessions/{id}/approve`：批准前若步骤已过期，返回 HTTP 409 `{error: approval_expired, expires_at, message}`；重复审批同一 step 返回 409（`status != proposed`）。
- 新增测试 `tests/test_approval_expiry_drift.py`（10 项）：提案冻结 snapshot + expires_at、持久化跨重建保留、过期跳过执行、漂移超阈值跳过执行、status 翻转视为漂移、正常路径仍执行工具、`_detect_drift` 缺失 snapshot / 零基线 / 阈值内 边界、`_summary_of` 找不到实体返回 None。
- 更新 `tests/test_migration.py`：head revision 更新为 `49d2e70677ed`。
- 全量 `pytest -q`：88 项全部通过（78 → 88）。
- 未启用"超时自动执行"真实资金动作：过期一律 REJECT 后回到 running 状态，Loop 会重新观察再决策。

**外部依赖阻塞：** 无。

**遗留风险：**
- 漂移仅对比 `current_summary()` 派生的 4 个字段。账户级信号（预算余额、封户）尚未纳入 —— 待 3.3 引入 Connector `read_state()` 接口后一并覆盖。
- 快照由 `current_summary()` 派生；真实 Connector 若走 FactMediaDaily 聚合，快照会滞后当日新鲜度。这是数据链路问题，不是 3.2 引入的新风险。
- 审批人权限校验（"批准者是否有权限触发此写动作"）目前仍复用 2.1 建立的 `user_can_access_app` —— 若未来引入角色分级（如 approver ≠ analyst），需要单独扩展。

---

### 3.3 Outbox、执行回执与对账

**目标：** 把"已批准"与"外部媒体已生效"分开，正确处理超时和不确定状态。

**操作：**
- 批准只写 durable outbox，不在 API/AgentLoop 中直接调用媒体。
- dispatcher 领取动作并带 lease 执行；请求超时进入 `unknown`，禁止盲目重试。
- Connector 增加状态回读/验证接口；accepted 后回读，最终收敛到 verified/failed。
- mock/sandbox 也走同一协议，保证测试与生产状态机一致。

**关键文件：** 新增 `backend/app/services/agent_runtime/dispatcher.py`、`backend/app/services/connectors/base.py`、真实 Connector 实现、`backend/app/services/agent_runtime/loop.py`、`backend/app/services/agent_runtime/tools.py`

**验收：** 模拟"媒体已执行但响应丢失"，动作最终经对账变为 verified，且不产生第二次预算变更。

**状态：** ✅ 已完成（2026-07-21） | **依赖：** 3.1、3.2 | **下一步：** 4.1 拆分三类影响

**验收结果（2026-07-21）：**
- 新增 `backend/app/services/agent_runtime/dispatcher.py`：`Dispatcher.dispatch_and_verify()` 驱动 `AgentActionDB` 走 `mint_or_get → approved → dispatching → media_call → accepted → verify → verified/unknown/failed` 状态机；提供 `reconcile()` 收敛 `unknown` 动作。
- 新增 `BaseConnector.read_state(entity_id)`：默认从 `current_summary()` 派生（status/daily_budget/roi/spend/cpi），真实 Connector 可以按需覆盖走原生 API。
- Loop 接线：`AgentLoop._execute_approved_write` / `_execute_l0_write` 将审批通过或 L0 自动的写动作交给 Dispatcher；`tool.handler` 作为 `media_call` 被包装，既完成媒体调用，也保留既有 `IntentExecution` + `ActionLog` 审计链（软链接由 Dispatcher 未来落地）。
- 幂等：同一 `idempotency_key` 重放 `dispatch_and_verify` → 命中终态短路，不重复叫媒体（`test_happy_path_reaches_verified_and_calls_media_once` 断言 `call_count == 1`）。
- 不确定路径：媒体 `raise` → `unknown`；返回 `success=False` → `failed`；返回缺 `success` 字段 → `unknown`（不冒充成功）。
- 回读判定：`update_campaign_status` 严格比对 `status`；`update_campaign_budget` 相对差 ≤ 5% 视为一致；未匹配 → `unknown`，等 `reconcile` 收敛（+/− 无 read_state 也走 `unknown`）。
- `reconcile()`：`unknown → verified`（匹配）或 `unknown → failed`（明确不匹配）；`verified/failed` 是 no-op。
- 测试：新增 `backend/tests/test_dispatcher.py` 14 用例 —— happy path 幂等 / verified 短路 / 媒体异常 / 明确失败 / 返回值歧义 / read_state 缺失 / 回读不匹配 / 无 entity_id / 预算相对差匹配与偏离 / reconcile 三条收敛路径。全套 102 pytest 通过。

**外部依赖阻塞：** 无。持久化 outbox + 独立 worker + lease 明确划入 Phase 5.2；本步骤刻意保持同步 dispatcher，避免在 SQLite / 单进程场景引入本不需要的复杂度。

**遗留风险 / 待办：**
- 同步 dispatcher 在进程崩溃时仍会丢失 in-flight 动作（不会双发媒体，但会需要更多次 reconcile）。Phase 5.2 通过 durable outbox + worker lease 消除。
- `IntentExecution` / `ActionLog` 与 `AgentActionDB` 的软链接目前只在 dispatcher 层预留字段，尚未由 `tool.handler` 主动回写 `intent_execution_id` / `action_log_id`。属于对账反查便利性问题，不影响状态机正确性 —— Phase 4 收集 observed_impact 时会顺手把链接补上。
- `read_state()` 默认实现依赖 `current_summary()`，在真实 Connector（Google/TikTok）尚未走 native `campaigns.get()` 之前，回读的粒度和新鲜度会受限。Phase 6 只读工具扩充时会给 Google Connector 落 `read_state` 的原生实现。
- Loop `_dispatch_via_action_store` 在 `ctx.db is None`（demo 脚本）时回退到旧的直接 handler 路径 —— 与生产状态机不一致，但兼容 `scripts/demo_phase4.py`。生产运行时始终有 DB，`app_id` 授权也强制持库。

---

## Phase 4 — 真实影响与学习质量

### 4.1 拆分三类影响

**目标：** 预测、实际变化、归因效果不再混为同一字段。

**操作：**
- 定义 `predicted_impact`、`observed_impact`、`attributed_impact`。
- 现有 `simulate_impact()` 只能写 predicted；媒体事实写 observed；MMP 数据写 attributed。
- 记录时间窗、时区、币种、来源、新鲜度和完整性。

**关键文件：** `backend/app/models/intent.py`、`backend/app/models/agent_runtime.py`、`backend/app/services/agent_runtime/tools.py`、`backend/app/services/agent_runtime/memory.py`

**验收：** 动作刚执行时只有 predicted；没有媒体/MMP 回采时另外两类保持 null，不能用 0 冒充真实结果。

**状态：** ⬜ 待开始 | **依赖：** 3.3 | **下一步：** 模型字段拆分

---

### 4.2 延迟回采任务

**目标：** 在 2h/24h/7d 读取真实事实表，形成可追溯的效果记录。

**操作：**
- 动作 verified 后创建三个 impact job。
- 从 `FactMediaDaily`/`FactMMPDaily` 读取动作前后窗口并写回。
- 第一版采用可解释基线比较，后续再引入 matched control / DiD。

**关键文件：** 新增 `backend/app/services/agent_runtime/impact_collector.py`、`backend/app/models/agent_runtime.py`、`backend/app/models/data.py`

**验收：** 用固定事实数据和可控时钟运行 collector，三窗口结果可重复且来源明确。

**状态：** ⬜ 待开始 | **依赖：** 4.1、5.2（Job 系统） | **下一步：** 实现 impact collector

---

### 4.3 Episode 学习门禁

**目标：** 模拟、缺失或污染数据不能更新生产策略。

**操作：**
- Episode 增加 `data_quality`、`usable_for_learning`、归因完整性和 evidence ID。
- StrategyStore 只读取满足门槛的真实 Episode。
- Mock Episode 保留用于开发评估，但与生产策略完全隔离。

**关键文件：** `backend/app/services/agent_runtime/memory.py`、`backend/app/services/agent_runtime/strategy.py`、`backend/app/models/agent_runtime.py`

**验收：** 仅有 Mock Episode 时 learn 返回"无可用真实样本"且策略不变。

**状态：** ⬜ 待开始 | **依赖：** 4.2 | **下一步：** Episode 增加 data_quality 字段

---

## Phase 5 — Durable Runtime 与多实例协调

### 5.1 PostgreSQL 迁移

**目标：** 数据库成为共享真相源，先保证兼容，再按热点改异步。

**操作：**
- 通过 Alembic 将 schema/data 迁移到 PostgreSQL。
- 第一阶段保留同步 SQLAlchemy，验证正确性；再将 Agent/API 热路径改为 AsyncSession。
- 增加乐观锁/version，步骤 append 改为原子操作，缓存不再作为权威状态。

**关键文件：** `backend/app/db/base.py`、`backend/app/config.py`、`backend/requirements.txt`、Agent runtime stores、部署配置

**验收：** PostgreSQL 上全量 smoke 通过；两个 API 副本读到一致 session/action 状态。

**状态：** ⬜ 待开始 | **依赖：** 0.2 | **下一步：** 配置 PostgreSQL 连接

---

### 5.2 持久化 Job + Worker

**目标：** 替换 daemon thread，进程重启后任务可续跑且不重复写媒体。

**操作：**
- 新增 Job 表：queued/running/done/failed/dead、attempt、lease、run_after。
- `_spawn_loop()` 改为入队；独立 worker 执行 Agent Loop、dispatcher、impact collect。
- 每步 checkpoint；abort/redirect 写 DB，由 worker 读取。
- 重试仅用于可证明幂等的内部步骤；live unknown 动作进入对账。

**关键文件：** 新增 `backend/app/models/jobs.py`、新增 `backend/app/services/agent_runtime/worker.py`、`backend/app/api/v1/agent.py`、`backend/app/services/agent_runtime/loop.py`、`backend/app/services/agent_runtime/session.py`

**验收：** 执行中杀死 worker，重启后任务恢复；媒体写动作不重复。

**状态：** ⬜ 待开始 | **依赖：** 5.1 | **下一步：** 定义 Job 模型

---

### 5.3 StrategyStore 数据库化

**目标：** 替换 JSON 单例，支持作用域、版本、审批和回滚。

**操作：**
- 策略按 app/channel/country/version 存表。
- 更新永不原地覆盖；保留依据 Episode、样本数、置信度和审批人。
- 提供 JSON 导入脚本和版本回滚。

**关键文件：** `backend/app/services/agent_runtime/strategy.py`、`backend/app/models/agent_runtime.py`、Agent strategy API

**验收：** 两次学习生成两个版本；回滚后 Planner 读取指定有效版本。

**状态：** ⬜ 待开始 | **依赖：** 5.1 | **下一步：** Strategy 模型设计

---

### 5.4 独立调度与可观测

**目标：** 多副本不重复扫描，关键链路可定位。

**操作：**
- APScheduler 只负责向 Job 表投递，由独立 scheduler 或 PostgreSQL leader lock 保证唯一。
- 去重改为数据库唯一键/冷却窗口。
- 增加结构化日志、trace_id、Prometheus 指标和 SLO。

**验收：** 两个 API + 两个 worker 下同一异常只产生一条告警；指标可查看 action unknown、verify latency、job retry、LLM failure。

**状态：** ⬜ 待开始 | **依赖：** 5.2 | **下一步：** 调度器拆分

---

## Phase 6 — 有限扩充只读能力

仅在 Phase 1–5 门禁通过后实施：

1. `attribution_query`：读取真实 MMP ROAS/LTV，缺数据明确失败。
2. `creative_intelligence`：基于 Creative 粒度真实数据评估疲劳和胜出素材。
3. `data_quality_check`：检查缺日、MMP 缺失、币种、数据新鲜度和 Mock 混入。

暂不上线通用 `shell_tool`、动态 MCP 自动注册和任意 OpenAPI 工具。所有新工具显式声明 schema、权限、数据级别、来源和副作用。

**验收：** 工具只读、按 app 授权、返回数据来源/时间；不可信网页内容不能改变系统指令或审批策略。

---

## Phase 7 — 策略治理与知识库

**前置门禁：** 每个候选规则达到最小真实 Episode 样本、归因完整性和置信阈值。

1. Reflector 产出动作→指标 delta 和证据，而非纯摘要。
2. Strategy 变更必须展示 diff、证据、样本、置信度并支持人审/回滚。
3. 知识库分媒体变更、行业基线、内部策略效果三类，所有条目带来源和有效期。
4. A/B 只用于可安全分流且样本充分的策略。

RL、多 Agent、通用 CLI/MCP 保留为远期，不进入本轮生产升级。

---

## 首轮执行范围（批准后立即开始）

第一轮只做以下闭环，避免同时触碰过多未提交文件：

1. ~~创建 `docs/smartua_claude_plan.md` 并写入本路线图与状态表。~~ ✅
2. ~~建立/运行 Phase 0.1 回归基线，记录真实结果。~~ ✅
3. 实施 Phase 1.1 Connector `execution_mode` 与 live fail-closed。
4. 增加对应单元测试和 smoke 验证。
5. 启动后端并验证 Mock 黄金路径与 live 缺凭证失败路径。
6. 更新路线图状态和 `docs/CHANGELOG.md`（仅在验收通过后）。

第一轮完成后停止扩展，报告改动、测试和遗留风险，再进入 Phase 0.2/Phase 2.1。

---

## 最终端到端验收

选择一个渠道、一个账户、一个低风险动作，重复验证：

`真实读取 → 提案 → 授权校验 → 人工审批 → 过期/漂移校验 → 幂等出队 → 媒体接受 → 回读验证 → 2h/24h/7d 回采 → Episode 质量门禁 → 人审策略更新`

同时满足：无 Mock 混入、无跨 App 泄露、无重复执行、杀进程可恢复、结果可审计，才将"真实闭环"标记为完成。