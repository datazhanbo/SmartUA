"""审批相关：快照冻结、漂移检测、提案文案、过期校验。

逻辑从 loop.py 迁出，但保留 loop 模块的 re-export（api/v1/agent.py 和测试直接 import）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from app.services.agent_runtime.tools import AgentContext, Tool


_DRIFT_KEYS_NUMERIC = ("roi", "spend", "daily_budget")


def _iso_to_utc(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _summary_of(ctx: "AgentContext", entity_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """取 connector.current_summary() 中匹配 entity_id 的那一行；缺失时返回 None。"""
    if not entity_id:
        return None
    try:
        rows = ctx.connector.current_summary()
    except Exception:
        return None
    for r in rows or []:
        if str(r.get("campaign_id")) == str(entity_id):
            return {
                "roi": r.get("roi"),
                "spend": r.get("spend"),
                "status": r.get("status"),
                "daily_budget": r.get("daily_budget"),
            }
    return None


def _detect_drift(snapshot: Optional[Dict[str, Any]],
                  current: Optional[Dict[str, Any]],
                  pct: float) -> Optional[str]:
    """返回漂移原因（人类可读）；None 表示可继续执行。快照缺失时视为不漂移。"""
    if not snapshot or not current:
        return None
    snap_status = snapshot.get("status")
    cur_status = current.get("status")
    if snap_status and cur_status and str(snap_status) != str(cur_status):
        return f"status 从 {snap_status} 变为 {cur_status}"
    for k in _DRIFT_KEYS_NUMERIC:
        sv, cv = snapshot.get(k), current.get(k)
        if sv is None or cv is None:
            continue
        try:
            sv_f = float(sv); cv_f = float(cv)
        except (TypeError, ValueError):
            continue
        if abs(sv_f) < 1e-9:
            if abs(cv_f) > 1e-9:
                return f"{k} 从 0 变为 {cv_f:.3g}"
            continue
        rel = abs(cv_f - sv_f) / abs(sv_f)
        if rel > pct:
            return f"{k} 从 {sv_f:.3g} 漂移至 {cv_f:.3g}（{rel*100:.1f}% > 阈值 {pct*100:.0f}%）"
    return None


def _propose_text(tool: "Tool", params: Dict[str, Any]) -> str:
    """把 (tool, params) 格式化成一句人类可读的提案文案。"""
    entity = params.get("entity_id") or params.get("campaign_id") or "目标"
    extra = []
    if "daily_budget" in params:
        extra.append(f"预算→{params['daily_budget']}")
    if "bid" in params:
        extra.append(f"出价→{params['bid']}")
    if "status" in params:
        extra.append(f"状态→{params['status']}")
    tail = f"（{', '.join(extra)}）" if extra else ""
    return f"{tool.name} on {entity}{tail}"


def freeze_snapshot(ctx: "AgentContext", params: Dict[str, Any]) -> Dict[str, Any]:
    """L1/L2/L3 提案时冻结实体快照 + 过期时间。"""
    snapshot = _summary_of(ctx, params.get("entity_id"))
    expires_at = (datetime.now(timezone.utc)
                  + timedelta(seconds=settings.agent_approval_ttl_seconds)).isoformat()
    return {"snapshot": snapshot, "expires_at": expires_at}


def check_approval(step, ctx: "AgentContext") -> tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """审批通过前的过期/漂移校验。

    返回 (ok, reason, current_summary)。
    - ok=True：可继续执行
    - ok=False：reason 为 "expired" 或 "drift"，调用方应把 step 标 REJECTED 后重新规划
    """
    entity_id = (step.params or {}).get("entity_id")
    expired_dt = _iso_to_utc(step.expires_at)
    now_dt = datetime.now(timezone.utc)
    if expired_dt is not None and now_dt > expired_dt:
        return False, "expired", None

    current = _summary_of(ctx, entity_id)
    drift = _detect_drift(step.snapshot, current, settings.agent_approval_drift_pct)
    if drift:
        return False, f"drift:{drift}", current
    return True, None, current
