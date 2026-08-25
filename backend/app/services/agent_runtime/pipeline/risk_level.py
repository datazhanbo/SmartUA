"""风险分级与读/写判定。事实源仍是 Tool.risk_level / Tool.side_effect。"""
from __future__ import annotations

from typing import Any, Dict


def is_read_tool(tool) -> bool:
    return getattr(tool, "side_effect", None) == "read"


def is_l0_auto(tool) -> bool:
    return (not is_read_tool(tool)) and getattr(tool, "risk_level", "L2") == "L0"


def needs_approval(tool) -> bool:
    """L1/L2/L3 写工具需要人在环审批。"""
    return (not is_read_tool(tool)) and getattr(tool, "risk_level", "L2") in ("L1", "L2", "L3")


def provenance_of(ctx) -> Dict[str, Any]:
    return {
        "platform": getattr(ctx.connector, "platform", None),
        "execution_mode": getattr(ctx.connector, "execution_mode", None),
        "account_id": getattr(ctx.connector, "account_id", None) or None,
    }
