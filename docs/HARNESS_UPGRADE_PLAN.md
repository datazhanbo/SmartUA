# Harness 升级计划

> 基于 2026-08 DeepSeek Harness (DSH) / OpenAI Codex Harness / OpenClaw 三家开源 runtime 的架构调研，对 SmartUA 现有实现的补强建议。
> 创建：2026-08-24
> 状态：P0（#1 Tool Pipeline Middleware、#5 Makefile）于 2026-08-25 完成 ✅；P1 #3（AdSet/Ad 粒度 mock/sandbox 层）于 2026-08-25 完成 ✅；P1 #2（MCP Provider + Skill Loader）于 2026-08-25 完成 ✅；P2 #4 待执行。
> 关联：[ARCHITECTURE_v4.md](ARCHITECTURE_v4.md)、[TOOL_PIPELINE_v1.md](TOOL_PIPELINE_v1.md)、[SKILL_SYSTEM.md](SKILL_SYSTEM.md)、[changes/2026-08-25-tool-pipeline-middleware.md](changes/2026-08-25-tool-pipeline-middleware.md)、[changes/2026-08-25-adset-ad-granularity.md](changes/2026-08-25-adset-ad-granularity.md)、[changes/2026-08-25-mcp-provider-skill-loader.md](changes/2026-08-25-mcp-provider-skill-loader.md)、[CONNECTOR_DESIGN_v3.md](CONNECTOR_DESIGN_v3.md)、[AGENT_ITERATION_ROADMAP.md](AGENT_ITERATION_ROADMAP.md)

---

## 背景

2026 年 8 月，DeepSeek（8/13）和 OpenAI（8/19）先后开源了各自的 agent harness，加上已跑了大半年的 OpenClaw，agent loop 正式商品化。三家的核心共识：**agent runtime（ReAct loop、tool registry、session 管理、审批、沙箱）是基础设施，不是差异化**。

SmartUA 已经有一套自研的 Python harness（`backend/app/services/agent_runtime/`），129 个测试，v3 文档完备，接近生产形态。本计划不是重写，是对照三家的设计做 5 项补强。

**核心判断：不换 runtime，借设计不借代码。** SmartUA 是 Python 后端，DSH/Codex 是 TypeScript 生态，切换成本远大于收益。799 行 `loop.py` + 129 测试是资产不是债。

---

## 升级项

### 1. Tool Pipeline 抽 Middleware（P0） — ✅ 2026-08-25 完成

> 变更说明：[changes/2026-08-25-tool-pipeline-middleware.md](changes/2026-08-25-tool-pipeline-middleware.md)；配套手册：[TOOL_PIPELINE_v1.md](TOOL_PIPELINE_v1.md)。

**现状**：`agent_runtime/loop.py` 的 `AgentLoop`（升级前 799 行）把 L1/L2 审批、风险分级、工具调度、结果验证都写在一个 ReAct while 循环里。`_decide` → `_dispatch` → `_run`，审批通过 `loop.approve`，验证通过 `dispatcher.py::Dispatcher.dispatch_and_verify`。

**问题**：loop 同时负责"调哪个 tool"和"能不能调"，新增一个横切关注点（比如预算护栏、PII 脱敏、MCP tool 路由）就要改 loop。

**DSH 启发**：tool pipeline 是 waterfall——`tools/pre-execute → tools/execute → tools/post-execute`，每个关注点是一个 listener，不改 loop 本身。

**方案（已落地）**：

```
agent_runtime/pipeline/
  ├── base.py          # ToolMiddleware 抽象：before(call) / after(result) / on_error；MiddlewareChain onion
  ├── registry.py      # default_middlewares() / register_middleware() / reset_middlewares() / build_chain()
  ├── risk_level.py    # L0-L3 分级 + read/write 判定
  ├── approval.py      # freeze_snapshot / check_approval（过期+漂移）；从 loop 迁出 _summary_of/_detect_drift
  ├── executor.py      # execute_tool_call / dispatch_via_action_store（仍调 Dispatcher.dispatch_and_verify）
  └── budget_guard.py  # 新增：日预算增幅护栏（agent_budget_max_increase_pct，默认 0.50）
```

默认链：`[BudgetGuard] → [Executor]`。审计未单独抽 middleware——`tool.handler → Dispatcher → record_execution` 已写 IntentExecution + ActionLog + Episode 链接，再包一层会双写（详见 TOOL_PIPELINE_v1.md）。规则兜底规划整体迁到 `agent_runtime/planner.py`（纯函数）。

`AgentLoop._dispatch` 改为构建 `ToolCall` 过 middleware 链；L1/L2/L3 提议路径手动遍历 `mw.before()` 探测 BudgetGuard，通过后才冻结快照建审批 step（护栏在"打扰用户审批"之前生效）。loop 本身只做 ReAct 编排 + LLM 决策。

**验收（实测）**：
- 140 passed（原 129 + 新增 11，既有断言零修改）
- loop.py 从 799 行降到 437 行（<500）
- `tests/test_tool_pipeline.py::test_extensibility_register_middleware_without_loop_changes` 证明 `register_middleware(TracingMiddleware())` 不改 loop.py 即扩展

**未做（刻意保留）**：不引入 asyncio 重构、不改 LLM 调用方式——pipeline 保持同步。

---

### 2. MCP Tool Provider + Skill 分层（P1，Phase B） — ✅ 2026-08-25 完成

> 变更说明：[changes/2026-08-25-mcp-provider-skill-loader.md](changes/2026-08-25-mcp-provider-skill-loader.md)；配套手册：[SKILL_SYSTEM.md](SKILL_SYSTEM.md)。

**现状**：`agent_runtime/tools.py` 的 `ToolRegistry` 静态注册 9 个工具，无动态注册、无 MCP 接入。Skill 文件化（优化师写 `.md` 扩展能力）在 7 月竞品调研里已设计但未实现。

**DSH 启发**：
- Tool 是 `ctx.tools` seam，可以有多个 Provider（内置、MCP、plugin）
- Bundle/Patch 分层：工程师写底层 tool = base bundle，优化师写 `.md` skill = 上层 patch，不是动态注册新 tool

**方案（已落地，目录结构有微调）**：

```
agent_runtime/
  ├── tools.py                  # 内置 13 工具（未拆分）；ToolRegistry 扩展 register/unregister/refresh_provider
  ├── providers/
  │   ├── base.py               # ToolProvider ABC（name + list_tools + close）
  │   ├── static_provider.py    # 内存实现，测试 / 未来内置扩展
  │   └── mcp_provider.py       # MCP streamable-http → Tool 适配器（httpx-only，无 SDK 依赖）
  └── skills/
      └── loader.py             # Skill / SkillStore：.md frontmatter → 默认参数 + system prompt 片段
```

- **MCP Provider**：基于 httpx 实现 JSON-RPC 最小子集（initialize → notifications/initialized → tools/list → tools/call），支持 `Mcp-Session-Id` 与 SSE 响应；工具以 `{provider}__{mcp_name}` 命名空间并入 registry；只读工具走 annotation + 名字前缀判定，写工具默认 L3（可在 `tool_risk` 配置降级）；连接失败 fail-soft 返回 `[]` 不拖垮 AgentLoop。
- **Skill Loader**：`.md` skill 不注册新工具，只给 `target_tool` 合并默认参数（caller 显式参数优先）+ 把正文拼进 system prompt。示例 `scale_winning_campaign.md`、`pause_fatigued_adset.md` 已落 `backend/data/skills/`。
- **AgentLoop 接线**：`__init__` 装载 SkillStore + 按 `settings.agent_mcp_servers` 注册 MCPProvider（幂等）；`_llm_decide` 追加 skill prompt 片段；`_dispatch` 所有路径统一 `skills.apply_params(tool.name, decision.params)`。
- **配置**：`AGENT_MCP_ENABLED / AGENT_MCP_SERVERS / AGENT_SKILLS_ENABLED / AGENT_SKILLS_DIR`。

**验收（实测）**：
- 181 passed（155 → 181，新增 26：skill 10 + mcp 11 + provider-registry 5）
- loop.py 437 → 476 行（仍 <500）
- `ToolRegistry.register_provider / unregister_provider / refresh_providers` 支持运行时挂载/卸载/热刷新，不重启服务
- `docs/SKILL_SYSTEM.md` 写清 frontmatter 规范、skill vs tool 边界、MCP 配置与安全缺省

**未做（刻意保留）**：
- 不做 ClawHub 式的 skill 市场 / skill 与 MCP server 的 UI 管理（改文件 / 配置后重启，或调 `refresh_providers()` / `SkillStore.reload()`）。
- 不引 `mcp` SDK、不实现 stdio / SSE transport / resources / prompts，等真有需要再补。
- 不把 `effective_risk_level` 自动接进 AgentLoop，防止 skill 文件意外把 L2 写成 L0 绕过审批。
- 未接真实第三方 MCP server（AppsFlyer 等）——SPI 与客户端就位，凭证 / 具体 endpoint 后续接。

---

### 3. AdSet/Ad 粒度 Connector（P1，Phase B） — ✅ 2026-08-25 mock/sandbox 层完成

> 变更说明：[changes/2026-08-25-adset-ad-granularity.md](changes/2026-08-25-adset-ad-granularity.md)。
> 本轮交付 mock/sandbox 端到端（Definition + Mock Provider + Consumer 工具 + 测试）；live 凭证接入为后续子项。

**现状**：Connector 抽象在 `connectors/base.py`（`apply_action` / `read_state` / `save_ods` / `save_dwd` / `execute_pull`），实现有 mock_media、meta、google、tiktok、appsflyer。`execution_mode ∈ mock/sandbox/live` 隔离已到位。但工具粒度只到 Campaign，无 AdSet/Ad 层。真实媒体凭证未接通（默认 mock，Meta 被封拒写，TikTok/Google 代码就绪未 live）。

**DSH 启发**：seam 必须同时设计 Definition / Provider / Consumer 三层；fs 和 subprocess 共享 execution world，切 provider 时一起切。

**方案**：

Definition 层（`connectors/base.py` 新增接口）：
```python
class AdSetReader(Protocol):
    def get_adsets(self, campaign_id: str) -> list[AdSet]: ...
    def get_adset_metrics(self, adset_id: str, date_range: str) -> Metrics: ...

class AdSetWriter(Protocol):
    def pause_adset(self, adset_id: str) -> Result: ...
    def update_adset_bid(self, adset_id: str, bid: float) -> Result: ...

class AdReader(Protocol):
    def get_ads(self, adset_id: str) -> list[Ad]: ...
    def evaluate_creative(self, ad_id: str) -> CreativeHealth: ...
```

Provider 层：MockMediaConnector 先实现（sandbox/mock mode 下跑通），MetaConnector 等 live 凭证就绪再补。

Consumer 层：`builtin/` 新增 4 个工具——`observe_adsets`(L0)、`adjust_adset_bid`(L2)、`evaluate_creative`(L0)、`pause_adset`(L1)。这些在 7 月竞品调研文档 `project/smartua/sug-round2-竞品-bid-skill-enhancement.md` 里已经设计好，直接落地。

**验收**：
- mock/sandbox mode 下 4 个新工具端到端跑通
- 测试：test_connectors_execution_mode.py 扩展覆盖 AdSet/Ad 粒度
- live mode 下 Meta Connector 对未实现的方法显式 raise NotImplementedError（fail-closed）

**顺序**：先 mock 实现 + 测试 → 再接 live 凭证。execution_mode 隔离已经在了，别浪费——先在 sandbox 里验证逻辑，碰真实 API 是最后一步。

**完成情况（2026-08-25）**：
- ✅ 模拟引擎新增 AdSet/Ad 状态，每个 campaign seed 2 AdSet × 2 Ad；修复 `update_adset_bid` 误改 campaign 的潜在 bug。
- ✅ `BaseConnector.apply_action` 新增 `update_adset_status`，未实现的连接器 fail-closed 返回 `success=False`（不抛异常）。
- ✅ 4 个工具落地：`observe_adsets`(L0)、`evaluate_creative`(L0)、`pause_adset`(L1) 新增；`adjust_bid`(L2) 即计划中的 `adjust_adset_bid`，修正为真正作用于 AdSet。
- ✅ `loop.py` 零改动（新增工具直接注册，pipeline/BudgetGuard 自动生效）；155 passed（140 + 15 新增）。
- ⏳ live 凭证：Meta/TikTok adset 写仍为 mock 占位；Google `update_adset_status` 待补；下一轮接入。
- ⏳ 前端 AdSet/Ad 视图、planner 对低 ROI/fatigued adset 的自动提议为后续项。

---

### 4. Durable Background Jobs（P2）

**现状**：impact 回采（6 条延迟 job，predicted/observed/attributed 三类影响）靠进程内 APScheduler，`autonomy.py` 的 `AnomalyDetector` + `AutonomyEngine` 也是 120s 扫描进程内调度。进程重启 job 状态丢失，无法多实例。

**OpenClaw 启发**：heartbeat 是核心原语，但 OpenClaw 的 heartbeat 状态也是文件级持久化。DSH 有 `ctx.jobs` background work seam。

**方案**：短期不引入 Celery/Temporal（过度工程），做最小 durable 版本：

- 新建 `jobs/models.py`：`JobState` 表（job_id、job_type、status、scheduled_at、started_at、finished_at、payload、result、attempts）
- `jobs/scheduler.py`：APScheduler 启动时从 DB 恢复 pending job，执行后更新状态
- 现有 `impact_collector.py` 的 6 条回采 job 和 `autonomy.py` 的扫描 job 改为走 JobState

**验收**：
- 进程重启后 pending job 自动恢复执行
- 测试：test_jobs_persistence.py（新建）模拟 job 执行中 kill → 重启 → job 继续
- 不引入 Redis/RabbitMQ——SQLite 够 SmartUA 当前量级

**不做**：多实例并发锁、job priority queue、DAG 依赖——等真有第二个客户实例再考虑。

---

### 5. 0 手动步骤启动（P2，Vibe Coding 铁律 #4） — ✅ 2026-08-25 完成

**现状（升级前）**：无 Makefile/Docker，启动靠 `uvicorn main:app`，前端另起。新环境上手需要读 README 猜步骤。

**已落地（仓库根 `Makefile`）**：

```makefile
setup:      # 装后端依赖 + alembic upgrade head + seed(init_campaign_data + init_alerts) + 前端 npm install
dev:        # 并行起后端 :8000 + 前端 :5173（vite proxy 已配）；用 & 并行而非 concurrently
dev-backend / dev-frontend:   # 分开起
test:       # 后端 pytest -v
db-reset:   # 清库 + alembic upgrade head + 重新 seed
```

README 顶部已加 Quick Start 段落，写清每条命令做了什么，并说明 `make dev` 用 `&` 并行（Ctrl-C 后若 uvicorn 未退出，`pkill -f uvicorn`，或用 `make dev-backend` / `make dev-frontend` 分开跑）。

**验收（实测）**：`make -n setup/dev/test/db-reset` 四个 target dry-run 全部通过；`make setup && make dev` 可起全栈。

---

## 优先级与排期建议

| 顺序 | 升级项 | 优先级 | 预估 | 状态 |
|------|--------|--------|------|------|
| 1 | Tool Pipeline Middleware | P0 | 2-3 天 | ✅ 2026-08-25 完成 |
| 5 | Makefile 启动 | P2 | 半天 | ✅ 2026-08-25 完成 |
| 3 | AdSet/Ad 粒度 Connector | P1 | 3-4 天 | ✅ mock/sandbox 层 2026-08-25 完成（live 待接） |
| 2 | MCP Provider + Skill Loader | P1 | 3-5 天 | ✅ 2026-08-25 完成（httpx-only streamable-http；文件 skill） |
| 4 | Durable Jobs | P2 | 2-3 天 | ⏳ 待执行（#1/#2/#3 后 job 触发逻辑更清晰） |

**建议执行顺序**：~~#1 → #5（同日）~~ ✅ → ~~#3~~ ✅ → ~~#2~~ ✅ → #4。#1 是地基，不拆后面加什么都往 799 行 loop 里堆。

---

## 明确不做的事

- ❌ **不把 loop 换成 DSH/Codex**：Python 后端切 TS 生态成本远大于收益，799 行 loop + 129 测试是资产
- ❌ **不引入 LangGraph/LangChain**：SmartUA 的自研 loop 已经能跑，加框架只会增加抽象层
- ❌ **不做微服务拆分**：当前 SQLite + 单进程足够，微服务是运营出问题后的解法
- ❌ **不做 agent team / 多 agent 并行**：AGENT_ITERATION_ROADMAP Phase D 的内容，当前阶段 Skill（无状态文档加载）比子 Agent（有状态、有 token 成本）更合适——"能用 Skill 解决的事就不要再开一个 Agent"（腾讯 Harness 文章判断）
- ❌ **不做实时流式 agent 输出到前端的重构**：现有 SSE `stream_ticket.py` 够用，等前端有真实交互需求再改

---

## 参考

- 本仓库学习笔记：`/Users/hezan/Documents/hezan/collection/DeepSeek-Harness-学习笔记.md`
- DSH 架构：https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md
- Codex Harness：https://developers.openai.com/blog/codex-as-a-platform
- OpenClaw 架构：https://bibek-poudel.medium.com/how-openclaw-works-understanding-ai-agents-through-a-real-architecture-5d59cc7a4764
- 腾讯 Harness 实战：`/Users/hezan/Documents/hezan/collection/从Vibe Coding到Harness—— 一套大仓AI工程化实战.md`
- SmartUA 竞品调研：`/Users/hezan/Documents/hezan/project/smartua/sug-round2-竞品-bid-skill-enhancement.md`
