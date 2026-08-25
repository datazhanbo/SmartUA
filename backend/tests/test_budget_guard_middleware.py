"""BudgetGuardMiddleware 单元测试。

覆盖：
- read 工具 / 无 daily_budget 的写动作：透传
- 写动作增幅在阈值内：透传
- 写动作增幅超阈值：返回 denied
- 实体缺失（冷启动）：不拦截
- 关闭开关：透传
- 阈值设为 0：任何正增幅都拦截
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app.config import settings
from app.services.agent_runtime.pipeline import (
    BudgetGuardMiddleware, ToolCall,
)


class _C:
    pass


class FakeConnector:
    platform = "mock"
    execution_mode = "mock"
    account_id = "fake"

    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = rows

    def current_summary(self):
        return self._rows


def _ctx(old_budget: float, entity: str = "camp_1"):
    c = _C()
    c.connector = FakeConnector([
        {"campaign_id": entity, "country": "US", "status": "ACTIVE",
         "roi": 1.0, "spend": 100.0, "daily_budget": old_budget, "cpi": 1.0}
    ])
    c.db = None
    return c


def _tool(side_effect: str = "write"):
    from app.services.agent_runtime.tools import Tool, ToolResult

    def _h(params, ctx):
        return ToolResult(observation="ok", data={})

    return Tool(name="adjust_budget", description="", risk_level="L1",
                side_effect=side_effect, params_hint="", handler=_h)


def _call(*, old_budget, new_budget, side_effect="write", entity="camp_1"):
    params = {"entity_id": entity}
    if new_budget is not None:
        params["daily_budget"] = new_budget
    return ToolCall(name="adjust_budget", params=params, tool=_tool(side_effect),
                    ctx=_ctx(old_budget, entity), risk_level="L1",
                    side_effect=side_effect)


@pytest.fixture(autouse=True)
def _restore_settings():
    enabled = settings.agent_budget_guard_enabled
    cap = settings.agent_budget_max_increase_pct
    yield
    settings.agent_budget_guard_enabled = enabled
    settings.agent_budget_max_increase_pct = cap


def test_read_tool_passes_through():
    mw = BudgetGuardMiddleware()
    assert mw.before(_call(old_budget=100.0, new_budget=9999.0, side_effect="read")) is None


def test_write_without_budget_passes_through():
    mw = BudgetGuardMiddleware()
    assert mw.before(_call(old_budget=100.0, new_budget=None)) is None


def test_increase_within_cap_passes_through():
    settings.agent_budget_max_increase_pct = 0.50
    mw = BudgetGuardMiddleware()
    # old=100, new=140 → +40% < 50%
    assert mw.before(_call(old_budget=100.0, new_budget=140.0)) is None


def test_increase_above_cap_denied():
    settings.agent_budget_max_increase_pct = 0.50
    mw = BudgetGuardMiddleware()
    result = mw.before(_call(old_budget=100.0, new_budget=200.0))
    assert result is not None
    assert result.status == "denied"
    assert result.data.get("blocked_by") == "budget_guard"
    assert "BudgetGuard" in result.observation


def test_missing_entity_not_blocked():
    mw = BudgetGuardMiddleware()
    # summary 只有 camp_1，请求 camp_new → _summary_of 返回 None → 透传
    call = _call(old_budget=100.0, new_budget=500.0, entity="camp_new")
    call.ctx = _ctx(100.0, entity="camp_1")
    assert mw.before(call) is None


def test_disabled_switch_passes_through():
    settings.agent_budget_guard_enabled = False
    mw = BudgetGuardMiddleware()
    assert mw.before(_call(old_budget=100.0, new_budget=9999.0)) is None


def test_zero_cap_blocks_any_positive_increase():
    settings.agent_budget_max_increase_pct = 0.0
    mw = BudgetGuardMiddleware()
    result = mw.before(_call(old_budget=100.0, new_budget=101.0))
    assert result is not None
    assert result.status == "denied"
