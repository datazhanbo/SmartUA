"""Tool Pipeline —— 把横切关注点从 AgentLoop 里拆出来。

设计参考 DeepSeek Harness (DSH) 的 waterfall tool pipeline：
    before → execute → after
每个关注点是一个 Middleware，新增 BudgetGuard / PII / MCP 路由等不需要改 AgentLoop。

同步实现，保持与现有代码一致，不引入 asyncio。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.agent_runtime.tools import AgentContext, Tool


@dataclass
class ToolCall:
    """一次工具调用的运行时载体。"""
    name: str
    params: Dict[str, Any]
    tool: "Tool"
    ctx: "AgentContext"
    risk_level: str
    side_effect: str            # "read" | "write"
    trigger: str = "l0"         # "l0" | "approved"
    step_id: Optional[str] = None
    snapshot: Optional[Dict[str, Any]] = None
    predicted_impact: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallResult:
    """统一的工具调用结果。loop 据此构造 AgentStep。"""
    ok: bool
    observation: str
    data: Dict[str, Any] = field(default_factory=dict)
    status: str = "executed"     # executed | denied | error
    denied_reason: Optional[str] = None


class ToolMiddleware:
    """Middleware 基类。三类钩子都可选覆写。

    - before(call) -> Optional[ToolCallResult]：返回 None 继续链；返回结果短路。
    - after(call, result)：逆序调用，用于审计/指标。
    - on_error(call, exc) -> Optional[ToolCallResult]：返回 None 继续抛。
    """

    name: str = "middleware"

    def before(self, call: ToolCall) -> Optional[ToolCallResult]:
        return None

    def after(self, call: ToolCall, result: ToolCallResult) -> None:
        return None

    def on_error(self, call: ToolCall, exc: BaseException) -> Optional[ToolCallResult]:
        return None


class MiddlewareChain:
    """同步 onion 链。

    before 正序：任一 before 返回非 None 即短路，已跑过的 after 仍按逆序触发。
    executor 是最内层（由调用方传入），正常路径返回其结果；异常走 on_error。
    """

    def __init__(self, middlewares: Optional[List[ToolMiddleware]] = None):
        self._middlewares: List[ToolMiddleware] = list(middlewares or [])

    def append(self, mw: ToolMiddleware) -> None:
        self._middlewares.append(mw)

    def reset(self) -> None:
        self._middlewares.clear()

    def __iter__(self):
        return iter(self._middlewares)

    def __len__(self) -> int:
        return len(self._middlewares)

    def execute(self, call: ToolCall,
                executor: Callable[[ToolCall], ToolCallResult]) -> ToolCallResult:
        ran: List[ToolMiddleware] = []
        result: Optional[ToolCallResult] = None

        try:
            for mw in self._middlewares:
                ran.append(mw)
                short = mw.before(call)
                if short is not None:
                    result = short
                    break
            if result is None:
                result = executor(call)
            return result
        except BaseException as exc:
            for mw in reversed(self._middlewares):
                recovered = mw.on_error(call, exc)
                if recovered is not None:
                    result = recovered
                    break
            if result is None:
                raise
            return result
        finally:
            if result is not None:
                for mw in reversed(ran):
                    try:
                        mw.after(call, result)
                    except Exception:
                        # after 钩子失败不影响主路径
                        pass
