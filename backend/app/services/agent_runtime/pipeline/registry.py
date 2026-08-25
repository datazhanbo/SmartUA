"""Middleware 注册表。

新增横切关注点时调 register_middleware()，不需要改 AgentLoop。
测试用 reset_middlewares() 恢复默认。
"""
from __future__ import annotations

from typing import List, Optional

from app.services.agent_runtime.pipeline.base import MiddlewareChain, ToolMiddleware
from app.services.agent_runtime.pipeline.budget_guard import BudgetGuardMiddleware

_extra: List[ToolMiddleware] = []


def default_middlewares() -> List[ToolMiddleware]:
    """默认 middleware 链。顺序：外层 → 内层。"""
    return [BudgetGuardMiddleware(), *_extra]


def register_middleware(mw: ToolMiddleware) -> None:
    """追加一个全局 middleware。主要用于扩展和测试。"""
    _extra.append(mw)


def reset_middlewares() -> None:
    _extra.clear()


def build_chain(middlewares: Optional[List[ToolMiddleware]] = None) -> MiddlewareChain:
    if middlewares is None:
        middlewares = default_middlewares()
    return MiddlewareChain(middlewares)
