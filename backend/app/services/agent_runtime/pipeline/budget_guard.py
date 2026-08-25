"""BudgetGuard —— 写动作预算护栏。

在 tool 进入审批或执行之前拦截 daily_budget 的相对增幅。
确定性规则不交给 LLM 判断。
"""
from __future__ import annotations

import logging
from typing import Optional

from app.config import settings
from app.services.agent_runtime.pipeline.approval import _summary_of
from app.services.agent_runtime.pipeline.base import (
    ToolCall, ToolCallResult, ToolMiddleware,
)

logger = logging.getLogger(__name__)


class BudgetGuardError(RuntimeError):
    pass


class BudgetGuardMiddleware(ToolMiddleware):
    """拦截超阈值的预算增幅。

    控制开关（settings，可经环境变量覆盖）：
      agent_budget_guard_enabled: True
      agent_budget_max_increase_pct: 0.50  （50%）
    """

    name = "budget_guard"

    def before(self, call: ToolCall) -> Optional[ToolCallResult]:
        if not getattr(settings, "agent_budget_guard_enabled", True):
            return None
        if call.side_effect != "write":
            return None
        params = call.params or {}
        new_budget = params.get("daily_budget")
        if new_budget is None:
            return None

        current = _summary_of(call.ctx, params.get("entity_id"))
        if not current:
            return None
        old_budget = current.get("daily_budget")
        try:
            new_f = float(new_budget)
            old_f = float(old_budget) if old_budget is not None else 0.0
        except (TypeError, ValueError):
            return None

        if old_f <= 1e-9:
            # 旧预算缺失或为 0：不拦截（避免冷启动/新建广告组被挡）
            return None

        rel = (new_f - old_f) / old_f
        max_pct = float(getattr(settings, "agent_budget_max_increase_pct", 0.50))
        if rel > max_pct:
            reason = (f"预算增幅 {rel*100:.1f}% 超过护栏 {max_pct*100:.0f}%"
                      f"（{old_f:.2f} → {new_f:.2f}）")
            logger.info("BudgetGuard blocked: %s", reason)
            return ToolCallResult(
                ok=False,
                observation=f"🚫 BudgetGuard：{reason}。已阻止本次写动作，未提交审批/执行。",
                data={"blocked_by": "budget_guard", "reason": reason,
                      "old_budget": old_f, "new_budget": new_f},
                status="denied",
                denied_reason=reason)
        return None
