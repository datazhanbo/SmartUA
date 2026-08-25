# 2026-08-25 — P0 升级：Tool Pipeline Middleware + Makefile

> 对应 `docs/HARNESS_UPGRADE_PLAN.md` 的 **#1（Tool Pipeline Middleware）** 与 **#5（Makefile）**。
> 本次只做 P0；MCP/Skill（#2）、AdSet/Ad（#3）、Durable Jobs（#4）下一轮。

## 背景与动机

`agent_runtime/loop.py` 在升级前有 799 行，把 L1/L2 审批、风险分级、工具调度、结果验证、Episode 回填全堆在一个 ReAct while 循环里。每加一个横切关注点（预算护栏、PII、MCP 路由）都要改 loop，回归风险大。

参考 DeepSeek Harness（DSH）的 waterfall tool pipeline 思路——`before → execute → after`，每个关注点是一个插件——把工具管线抽成 middleware 链。目标：

- **新增一个 middleware（如 BudgetGuard）不改 `loop.py`**；
- `loop.py` 降到 500 行以内，只保留 ReAct 编排 + LLM 决策；
- 现有测试（升级前 129 个）全绿，不修改任何既有断言。

## 新增 / 变更

### 1. 新包 `app/services/agent_runtime/pipeline/`

| 文件 | 职责 |
|------|------|
| `base.py` | `ToolCall` / `ToolCallResult` dataclass、`ToolMiddleware` ABC（`before/after/on_error`）、`MiddlewareChain.execute()` 同步 onion 链 |
| `registry.py` | `default_middlewares()` 工厂 + `register_middleware()` / `reset_middlewares()` / `build_chain()`；**验收"加 middleware 不改 loop"的关键** |
| `risk_level.py` | `is_read_tool` / `is_l0_auto` / `needs_approval` / `provenance_of`，事实源仍是 `Tool.risk_level` / `Tool.side_effect` |
| `approval.py` | `freeze_snapshot` / `check_approval`（过期 + 漂移校验）；从 loop 迁出 `_summary_of` / `_detect_drift` / `_DRIFT_KEYS_NUMERIC` / `_iso_to_utc` |
| `executor.py` | `execute_tool_call` / `dispatch_via_action_store`；内部仍调 `Dispatcher.dispatch_and_verify`，保留无 DB 兜底直调 `tool.handler`、`ctx.db.commit()` 语义、Episode 链接 |
| `budget_guard.py` | `BudgetGuardMiddleware`：写动作且带 `daily_budget` 时，相对增幅超过 `agent_budget_max_increase_pct`（默认 0.50）直接 denied，不进审批 |

**Middleware 顺序**（`default_middlewares()`）：

```
[BudgetGuard] → [Executor]
```

- BudgetGuard 挡在审批/执行之前——超预算别让用户去审批；
- Executor 是最内层，真调 tool 或 dispatcher；
- 审计/Episode 回填沿用既有 `tool.handler → Dispatcher → record_execution` 链路，不重复包一层 AuditLog middleware（避免双写 IntentExecution/ActionLog）。

**两种驱动方式**：

1. read / L0 自动写 / 审批通过后执行：`chain.execute(call, executor)`，全链自动跑；
2. L1/L2/L3 提议：loop 先手动遍历 `mw.before(call)` 探测 BudgetGuard 是否拒绝，通过才冻结快照建 APPROVAL step——保证护栏在"打扰用户审批"之前生效。

### 2. 新文件 `app/services/agent_runtime/planner.py`

把规则引擎兜底规划（暂停低 ROI / 给高 ROI 加预算 / 换素材 / 出报告）及配套解析函数（`extract_roi_threshold` / `extract_pct` / `extract_country` / `extract_json` / `final_summary` / 工具相关 `propose_text`）从 loop 整体迁出，保持纯函数。`loop._decide` 仍优先 LLM、异常/不可用时调 `planner.rule_based_decide`。`Decision` 用懒导入避免循环引用。

### 3. `loop.py` 薄壳化

- `__init__`：`self.registry = get_tool_registry()` + `self.chain = build_chain()`；
- `_dispatch`：查 tool → 构 `ToolCall` → 走 chain（read/L0）或手动 before 探测 + 冻结提议（L1/L2/L3）；
- `approve`：薄壳，过期/漂移委托 `check_approval`，通过后构 `trigger="approved"` 的 ToolCall 走 chain；
- `_llm_decide` 完全不动（不改 LLM 调用方式）；
- 保留向后兼容 re-export：`_summary_of / _detect_drift / _DRIFT_KEYS_NUMERIC / _iso_to_utc` 仍可从 `loop` import（`api/v1/agent.py::approve_step` 和 `test_approval_expiry_drift.py` 依赖）。

### 4. 配置（`app/config.py`）

新增：

```python
agent_budget_guard_enabled: bool = True
agent_budget_max_increase_pct: float = 0.50
```

可经 `AGENT_BUDGET_GUARD_ENABLED` / `AGENT_BUDGET_MAX_INCREASE_PCT` 环境变量覆盖。

### 5. Makefile（仓库根）

`make setup` / `make dev` / `make test` / `make db-reset`，外加 `dev-backend` / `dev-frontend`。用 `&` 并行而非 `concurrently`，不引入新 npm 依赖。

### 6. README Quick Start

顶部加 `make setup / make dev / make test / make db-reset` 四条命令及一行说明。

## 验证

- `cd backend && pytest -v`：**140 passed**（原 129 + 新增 11），既有断言零修改；
- `wc -l app/services/agent_runtime/loop.py`：**437 行**（升级前 799，目标 <500）；
- 新增 `tests/test_tool_pipeline.py`：onion 顺序、before 短路不跑 executor 但 after 仍触发、on_error 逆序恢复、**`register_middleware(TracingMiddleware())` 不改 loop.py 即扩展**；
- 新增 `tests/test_budget_guard_middleware.py`：read 透传、无预算透传、阈值内透传、超阈 denied、冷启动实体缺失不拦、开关关闭透传、阈值 0 全拦；
- `make -n setup/dev/test/db-reset` 四个 target dry-run 通过。

## 风险与约束（执行结果）

- **事务归属原样保留**：dispatcher 不 commit、`dispatch_via_action_store` 内 `ctx.db.commit()`、Episode 链接自开 `SessionLocal`，迁移时未改；
- **无 DB 兜底保留**：`ctx.db is None` 时直调 `tool.handler`（demo/脚本依赖）；
- **向后兼容**：re-export shim 兜住 `api/v1/agent.py` 与测试对 loop 私有函数的 import。

## 已知遗留（下一轮）

- `agent_runtime/autonomy.py::handle_anomaly` 仍绕过 `_dispatch` 直调 `tool.handler`，未接 middleware——主动巡检触发的写动作目前不走 BudgetGuard；
- 同步 409 路径（`api/v1/agent.py::approve_step`）与 `loop.approve` 仍是双实现，已共用 `check_approval` 但未合并入口；
- 审计未抽成独立 middleware：当前复用 tool/dispatcher 内既有 `record_execution`，未来若要 PII/MCP 路由再评估是否补一层 AuditLog。
