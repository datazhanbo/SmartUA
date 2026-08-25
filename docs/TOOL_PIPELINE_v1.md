# Tool Pipeline Middleware v1

> 版本：v1（2026-08-25），配套 SmartUA v1.9.x。
> 变更记录：[changes/2026-08-25-tool-pipeline-middleware.md](changes/2026-08-25-tool-pipeline-middleware.md)。
> 架构总览：[ARCHITECTURE_v4.md](ARCHITECTURE_v4.md) §2.1。

本文档描述 SmartUA Agent Runtime 的工具调用管线：一个同步 onion 模型，把审批、护栏、审计等横切关注点从 `AgentLoop` 拆成可独立注册的 middleware。

---

## 1. 设计目标

- **加一个 middleware 不改 `loop.py`**：横切逻辑通过 `register_middleware()` 追加。
- `loop.py` 只保留 ReAct 编排（think → select tool → observe）和 LLM 决策，不掺杂"能不能调"。
- 与既有资产零冲突：`Dispatcher.dispatch_and_verify` / `AgentActionStore` / `record_execution` / Episode 链接全部原样复用。
- 同步实现，不引入 asyncio 重构（与现有代码风格一致；`_llm_decide` 的异步边界保持不动）。

---

## 2. 核心契约

代码：`backend/app/services/agent_runtime/pipeline/base.py`。

### 2.1 `ToolCall`

一次工具调用的运行时载体：

| 字段 | 说明 |
|------|------|
| `name` / `params` / `tool` / `ctx` | 工具名、参数、`Tool` 对象、`AgentContext` |
| `risk_level` | `L0`/`L1`/`L2`/`L3`，取自 `Tool.risk_level`（经 `RISK_LEVEL_MAP` 覆盖） |
| `side_effect` | `"read"` / `"write"`，取自 `Tool.side_effect` |
| `trigger` | `"l0"` / `"approved"` / `"read"` / `"proposed"`：驱动来源 |
| `step_id` / `snapshot` / `predicted_impact` | 审批与影响回填链路使用 |
| `metadata` | 扩展字段 |

### 2.2 `ToolCallResult`

统一结果，`loop` 据此构造 `AgentStep`：

- `ok`: 是否成功
- `observation`: 写入 step 的文本
- `data`: 结构化返回（含 `blocked_by` / `action_id` / `dispatch` 等）
- `status`: `"executed"` / `"denied"` / `"error"`
- `denied_reason`: 拒绝原因

### 2.3 `ToolMiddleware`

三类钩子，都可选覆写：

```python
class ToolMiddleware:
    name: str = "middleware"

    def before(self, call: ToolCall) -> Optional[ToolCallResult]:
        return None          # None = 继续链；非 None = 短路

    def after(self, call: ToolCall, result: ToolCallResult) -> None:
        ...                  # 逆序调用，用于指标/审计；抛错被吞掉，不影响主路径

    def on_error(self, call: ToolCall, exc: BaseException) -> Optional[ToolCallResult]:
        return None          # None = 继续抛；非 None = 恢复成正常 result
```

### 2.4 `MiddlewareChain.execute(call, executor)`

onion 模型：

```
 before(mw1) → before(mw2) → ... → executor(call)
                                              │
 after(mwN) ← after(mwN-1) ← ... ← after(mw1) ←┘  （finally，逆序，短路/异常也触发）
```

- `before` **正序**：任一返回非 `None` 立即短路，后续 middleware 与 executor 都不执行。
- `executor` 是最内层，由调用方传入（通常是 `executor.execute_tool_call`）。
- 异常路径：`on_error` **逆序**遍历，第一个返回非 `None` 的 middleware 负责恢复；都不恢复则重新抛出。
- `after` 在 `finally` 中对**已经跑过 `before` 的** middleware 逆序触发——即便短路或异常也会触发。`after` 自身抛错被吞掉，不影响主结果。

---

## 3. 默认链与顺序

代码：`pipeline/registry.py`。

```
[BudgetGuard] → [Executor]
```

| 层 | 职责 | 为什么在这个位置 |
|----|------|------------------|
| `BudgetGuardMiddleware` | 写动作且带 `daily_budget` 时，相对增幅超阈值直接 `denied` | 必须在审批/执行之前——超预算别让用户去点批准，也别真打媒体 |
| `Executor`（由 chain 调用方传入，不是注册表项） | 调 `execute_tool_call` → `dispatch_via_action_store` → `Dispatcher.dispatch_and_verify` | 最内层，真干活 |

### 为什么没有独立的 AuditLog middleware

`tool.handler → Dispatcher → record_execution` 已经写 `IntentExecution` + `ActionLog` + Episode 链接（`executor.py` 保持了这条链路）。再包一层 AuditLog middleware 会**双写**。审计在当前实现里是 executor 的内部副作用，不单独抽层；未来加 PII 脱敏、MCP 路由这类纯横切逻辑时，再评估是否补一层。

### 两种驱动方式

`AgentLoop._dispatch` 根据风险分级选择路径：

1. **read / L0 自动写 / 审批通过后执行**：`chain.execute(call, executor)`，全链自动跑。
2. **L1/L2/L3 提议**：loop 先手动遍历 `for mw in chain: short = mw.before(call)` 探测 BudgetGuard 是否拒绝，**通过才冻结快照、建 APPROVAL step**——保证护栏在"打扰用户审批"之前生效。审批回来后 `approve()` 走第 1 种路径（`trigger="approved"`）。

---

## 4. 写一个新 middleware（以 BudgetGuard 为范本）

代码：`pipeline/budget_guard.py`。一个最小 middleware 只需实现 `before`：

```python
from app.config import settings
from app.services.agent_runtime.pipeline.base import ToolMiddleware, ToolCall, ToolCallResult
from app.services.agent_runtime.pipeline.risk_level import is_read_tool


class BudgetGuardMiddleware(ToolMiddleware):
    name = "budget_guard"

    def before(self, call: ToolCall) -> Optional[ToolCallResult]:
        if not settings.agent_budget_guard_enabled:
            return None
        if is_read_tool(call.tool):
            return None

        new_budget = call.params.get("daily_budget")
        if new_budget is None:
            return None

        old_budget = self._current_budget(call)
        if old_budget is None or old_budget <= 1e-9:
            return None  # 冷启动 / 实体缺失不拦

        rel = (float(new_budget) - old_budget) / old_budget
        if rel > settings.agent_budget_max_increase_pct:
            return ToolCallResult(
                ok=False,
                status="denied",
                observation=(
                    f"预算护栏：日预算 {old_budget:.2f} → {float(new_budget):.2f}，"
                    f"增幅 {rel:.0%} 超过上限 {settings.agent_budget_max_increase_pct:.0%}。"
                ),
                data={
                    "blocked_by": "budget_guard",
                    "old_budget": old_budget,
                    "new_budget": float(new_budget),
                    "increase_pct": rel,
                    "max_increase_pct": settings.agent_budget_max_increase_pct,
                },
                denied_reason="budget_guard",
            )
        return None
```

注册（**不改 loop.py**）：

```python
from app.services.agent_runtime.pipeline import register_middleware

register_middleware(BudgetGuardMiddleware())  # 或任何新的 ToolMiddleware 子类
```

`AgentLoop.__init__` 调 `build_chain()`，后者读 `default_middlewares()`——注册表的全局 `_extra` 会被织入。测试用 `reset_middlewares()` 还原。

### 扩展验收

`backend/tests/test_tool_pipeline.py::test_extensibility_register_middleware_without_loop_changes` 注册一个 `TracingMiddleware`（在 before/after 里 append 日志），断言它出现在 `default_middlewares()` 中并按 onion 顺序触发，全程不修改 `loop.py`。

---

## 5. 与 dispatcher / action_store 的边界

```
loop._dispatch
  └─ ToolCall
     └─ chain.execute
        └─ executor.execute_tool_call            # pipeline/executor.py
           ├─ ctx.db is None → 直调 tool.handler（demo/脚本兜底，保留）
           └─ dispatch_via_action_store
              ├─ AgentActionDB.mint_or_get       # 幂等键 + 状态机
              ├─ Dispatcher.dispatch_and_verify  # 真打媒体 / 回读 / 对账
              │    └─ tool.handler → record_execution（IntentExecution/ActionLog/Episode）
              └─ ctx.db.commit()                 # 事务边界原样保留
```

- **事务归属不变**：dispatcher 不 commit；`dispatch_via_action_store` 内 `ctx.db.commit()`；Episode 链接自开 `SessionLocal`。
- **幂等不变**：`idempotency_key = hash(session_id, step_id, tool, params_digest)`，二次调用返回原 action，媒体只打一次。
- **无 DB 兜底保留**：`ctx.db is None` 直调 `tool.handler`，middleware 仍生效（BudgetGuard 在 before 阶段，不依赖 DB）。
- **状态机不变**：`proposed → approved → dispatching → accepted → verified | failed | unknown`，middleware 不碰状态流转。

---

## 6. 风险分级的事实源

`pipeline/risk_level.py` 只做判定，不持有事实：

- `is_read_tool(tool)`：`tool.side_effect == "read"`
- `is_l0_auto(tool)`：`tool.risk_level == "L0"`
- `needs_approval(tool)`：`tool.risk_level in {"L1","L2","L3"}`
- `provenance_of(tool)`：返回 risk_level 来源（工具定义 / `RISK_LEVEL_MAP` 覆盖）

`Tool.risk_level` / `Tool.side_effect`（`tools.py`）是唯一事实源；middleware 不另立配置。

---

## 7. 配置

`backend/app/config.py`：

| 环境变量 | 默认 | 说明 |
|----------|------|------|
| `AGENT_BUDGET_GUARD_ENABLED` | `true` | BudgetGuard 总开关 |
| `AGENT_BUDGET_MAX_INCREASE_PCT` | `0.50` | 单次日预算增幅上限（相对值，0.50 = 50%） |

阈值设为 0 时，任何正向增幅都会被拦（`test_budget_guard_zero_cap_blocks_any_increase`）；冷启动（old budget ≤ 0 或实体缺失）不拦。

---

## 8. 测试

| 文件 | 覆盖 |
|------|------|
| `tests/test_tool_pipeline.py` | onion 顺序、before 短路但 after 仍触发、on_error 逆序恢复、`register_middleware` 不改 loop 即扩展 |
| `tests/test_budget_guard_middleware.py` | read 透传、无预算透传、阈值内透传、超阈 denied、冷启动实体缺失不拦、开关关闭透传、阈值 0 全拦 |

既有 129 个测试（审批漂移、幂等状态机、execution_mode 隔离、impact envelope 等）零修改通过；总计 140 passed。

---

## 9. 已知遗留

- `agent_runtime/autonomy.py::handle_anomaly` 主动巡检触发的写动作仍直调 `tool.handler`，未走 pipeline——BudgetGuard 对自治触发的写动作暂不生效。下一轮接入。
- 同步 409 路径（`api/v1/agent.py::approve_step`）与 `loop.approve` 共用 `check_approval` 但未合并入口；行为一致，仍是两份薄壳。
- 审计未抽成独立 middleware（见 §3）；未来若引入 PII/MCP 路由等纯横切逻辑再评估。
