"""Tool Pipeline middleware chain 测试。

覆盖：
- before/after 按 onion 顺序触发（before 正序，after 逆序）
- before 短路时 executor 不被调用，但已运行 middleware 的 after 仍触发
- executor 抛异常时 on_error 逆序被调用，并可恢复为结果
- 扩展性：注册一个 TracingMiddleware 即可在工具调用前后打点，无需改 loop.py
"""
from __future__ import annotations

from typing import List

import pytest

from app.services.agent_runtime.pipeline import (
    MiddlewareChain, ToolCall, ToolCallResult, ToolMiddleware,
    register_middleware, reset_middlewares, default_middlewares,
)


class _Trace(ToolMiddleware):
    def __init__(self, name, log: List[str], short=False, raise_in_exec=False,
                 recover=False):
        self.name = name
        self.log = log
        self.short = short
        self.raise_in_exec = raise_in_exec
        self.recover = recover

    def before(self, call):
        self.log.append(f"before:{self.name}")
        if self.short:
            return ToolCallResult(ok=False, observation=f"denied by {self.name}",
                                  status="denied")
        return None

    def after(self, call, result):
        self.log.append(f"after:{self.name}")

    def on_error(self, call, exc):
        self.log.append(f"on_error:{self.name}")
        if self.recover:
            return ToolCallResult(ok=False, observation="recovered", status="error")
        return None


def _dummy_call():
    return ToolCall(name="x", params={}, tool=None, ctx=None,  # type: ignore[arg-type]
                    risk_level="L0", side_effect="read")


def test_before_after_onion_order():
    log: List[str] = []
    chain = MiddlewareChain([_Trace("a", log), _Trace("b", log), _Trace("c", log)])
    executed = []

    def executor(call):
        executed.append("exec")
        return ToolCallResult(ok=True, observation="done")

    chain.execute(_dummy_call(), executor)
    assert executed == ["exec"]
    # before 正序 a→b→c；after 逆序 c→b→a
    assert log == ["before:a", "before:b", "before:c", "after:c", "after:b", "after:a"]


def test_before_short_circuits_but_after_still_runs():
    log: List[str] = []
    chain = MiddlewareChain([_Trace("a", log), _Trace("b", log, short=True),
                             _Trace("c", log)])
    executed = []

    def executor(call):
        executed.append("exec")
        return ToolCallResult(ok=True, observation="done")

    result = chain.execute(_dummy_call(), executor)
    assert executed == []                       # b 短路，executor 不跑
    assert result.status == "denied"
    # c.before 未运行 → 只有 a、b 的 after，逆序 b→a
    assert log == ["before:a", "before:b", "after:b", "after:a"]


def test_on_error_invoked_in_reverse_and_can_recover():
    log: List[str] = []

    class _Boom(ToolMiddleware):
        name = "boom"

        def before(self, call):
            return None

    def executor(call):
        raise RuntimeError("kaboom")

    chain = MiddlewareChain([
        _Trace("a", log, recover=False),
        _Trace("b", log, recover=True),   # b 先捕获恢复
        _Trace("c", log, recover=False),
    ])
    result = chain.execute(_dummy_call(), executor)
    assert result.status == "error"
    assert result.observation == "recovered"
    # on_error 逆序：c→b（b 恢复，停止）；after 对已运行的全部逆序触发
    assert "on_error:c" in log
    assert "on_error:b" in log
    assert "on_error:a" not in log


def test_extensibility_register_middleware_without_loop_changes():
    """验收：注册一个 TracingMiddleware 即出现在默认链中，无需改 loop.py。"""
    reset_middlewares()
    try:
        log: List[str] = []

        class TracingMiddleware(ToolMiddleware):
            name = "tracing"

            def before(self, call):
                log.append(f"trace:before:{call.name}")
                return None

            def after(self, call, result):
                log.append(f"trace:after:{call.name}")

        register_middleware(TracingMiddleware())
        names = [mw.name for mw in default_middlewares()]
        assert "tracing" in names
        assert "budget_guard" in names
    finally:
        reset_middlewares()
