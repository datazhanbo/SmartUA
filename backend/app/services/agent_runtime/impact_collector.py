"""Phase 4.2 / 4.4 —— 延迟回采：从事实表读真实变化，写回 observed / attributed。

流程（单进程、同步；由 Durable JobRunner tick 驱动）：

1. `enqueue_after_verified(db, action)` —— dispatcher 把动作推进到 `verified` 时调用，
   在通用 `agent_jobs` 表里生成 6 条 job（`impact_collect`，
   payload=`{action_id, kind, window}`）：{observed, attributed} × {2h, 24h, 7d}。
2. JobRunner 到点后调 `run_impact_job(db, payload)`：
   - 计算「动作前基线窗口」和「动作后观测窗口」在 FactMediaDaily / FactMMPDaily 上的
     聚合指标，二者相减得到 delta。
   - 写入 `AgentActionDB.observed_impact_json` / `attributed_impact_json`（本次 window 的
     envelope 覆盖旧值：同一 window 的 24h envelope 是"最新的 24h 观察"）。
   - Job 落 `done` 并把 envelope 写进 `result` 字段。
3. 找不到事实数据 → envelope 仍写入，但 `metrics={}` 且 `completeness=0.0`；job 标记
   `done`（不是失败：只是当前没数据，不代表以后没有 —— 但同 window 只回采一次，避免抖动）。
   **这是 Phase 4.1 定的核心不变量：没有观察到就是没有观察到，禁止用 0 冒充有效果。**

时钟通过 `now` 参数注入，测试可任意伪造。生产由 APScheduler tick 定期调
`JobRunner.run_pending(job_type="impact_collect")`；`run_due_jobs` 保留为便捷入口，
供外部 cron / API 直接触发。
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.agent_runtime import AgentActionDB, JobDB
from app.services.agent_runtime.impact import make_attributed, make_observed

logger = logging.getLogger(__name__)


# window → (窗口时长, 基线时长)。基线固定 7 天，观测窗口就是名字里那段时间。
_WINDOW_SPECS: Dict[str, timedelta] = {
    "2h":  timedelta(hours=2),
    "24h": timedelta(hours=24),
    "7d":  timedelta(days=7),
}
_BASELINE = timedelta(days=7)

_JOB_KINDS = ("observed", "attributed")
_JOB_TYPE = "impact_collect"


# --------------------------------------------------------------------------- #
# Enqueue（verified 时触发）
# --------------------------------------------------------------------------- #
def enqueue_after_verified(db: Session, action: AgentActionDB,
                            now: Optional[datetime] = None) -> List[JobDB]:
    """Verified 动作触发六条 impact job（observed × 3 + attributed × 3）。

    - 无 entity_id → 跳过（回采查不到事实表关键字段）。
    - 已存在同 idempotency_key 的 job → 跳过（幂等）。
    """
    if not action.entity_id:
        logger.info("skip enqueue for action %s (no entity_id)", action.id)
        return []

    now = now or datetime.utcnow()
    base_time = action.verified_at or action.accepted_at or now

    created: List[JobDB] = []
    for kind in _JOB_KINDS:
        for window, dur in _WINDOW_SPECS.items():
            idem = f"impact:{action.id}:{kind}:{window}"
            job = JobDB(
                id=uuid.uuid4().hex[:32],
                job_type=_JOB_TYPE,
                idempotency_key=idem,
                status="scheduled",
                scheduled_at=base_time + dur,
                payload={
                    "action_id": action.id,
                    "kind": kind,
                    "window": window,
                },
                app_id=action.app_id,
                attempts=0,
                max_attempts=1,
            )
            db.add(job)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                # 已有 job（重入）：跳过，不重复创建
                continue
            created.append(job)
    return created


# --------------------------------------------------------------------------- #
# JobRunner handler
# --------------------------------------------------------------------------- #
def run_impact_job(db: Session, payload: Dict[str, Any]) -> Dict[str, Any]:
    """JobRunner 入口：跑一条 impact_collect job，返回 {action_id, kind, window, envelope, has_data}。"""
    action_id = payload["action_id"]
    kind = payload["kind"]
    window = payload["window"]
    now = datetime.utcnow()

    action = db.query(AgentActionDB).filter(AgentActionDB.id == action_id).first()
    if action is None:
        raise LookupError(f"action row missing: {action_id}")

    envelope, has_data = _collect_one(db, action, kind=kind, window=window, executed_at=now)

    if kind == "observed":
        action.observed_impact_json = envelope
    else:
        action.attributed_impact_json = envelope

    db.flush()

    # Phase 4.3 —— 回填到 Episode（若存在关联）并按门禁提权 usable_for_learning
    if has_data:
        _promote_episode(db, action.id, kind=kind, window=window, envelope=envelope)

    return {
        "action_id": action_id,
        "kind": kind,
        "window": window,
        "has_data": has_data,
        "envelope": envelope,
    }


# --------------------------------------------------------------------------- #
# 便捷入口：外部 cron / API 直接触发到点 job
# --------------------------------------------------------------------------- #
def due_jobs(db: Session, now: Optional[datetime] = None,
             limit: int = 200,
             app_id: Optional[int] = None) -> List[JobDB]:
    """挑出到点的、还没执行完的 impact_collect job。"""
    now = now or datetime.utcnow()
    q = db.query(JobDB).filter(
        JobDB.job_type == _JOB_TYPE,
        JobDB.status == "scheduled",
        JobDB.scheduled_at <= now,
    )
    if app_id is not None:
        q = q.filter(JobDB.app_id == app_id)
    return q.order_by(JobDB.scheduled_at.asc()).limit(limit).all()


def run_due_jobs(db: Session, now: Optional[datetime] = None,
                 limit: int = 200,
                 app_id: Optional[int] = None) -> Dict[str, int]:
    """跑一遍到点的 impact_collect job，返回 {done, empty, failed}。

    独立于 JobRunner 单例使用，供 API / cron 直接触发。
    """
    now = now or datetime.utcnow()
    stats = {"done": 0, "empty": 0, "failed": 0}
    for job in due_jobs(db, now=now, limit=limit, app_id=app_id):
        # claim
        job.status = "running"
        job.started_at = now
        job.attempts = (job.attempts or 0) + 1
        db.flush()
        try:
            result = run_impact_job(db, job.payload or {})
        except Exception as e:
            logger.exception("impact job %s raised", job.id)
            job.status = "failed"
            job.finished_at = now
            job.last_error = f"{type(e).__name__}: {e}"
            stats["failed"] += 1
            db.flush()
            continue
        job.status = "done"
        job.finished_at = now
        job.result = result
        stats["done" if result.get("has_data") else "empty"] += 1
        db.flush()
    return stats


# --------------------------------------------------------------------------- #
# Episode 提权（Phase 4.3）
# --------------------------------------------------------------------------- #
def _promote_episode(db: Session, action_id: str, *, kind: str,
                     window: str, envelope: Dict[str, Any]) -> None:
    """把回采到的真实 envelope 写回 Episode.impact，并按门禁把 usable_for_learning 置为 True。

    - impact 挂到 `impact_{window}` 键（与 tools._compute_impact 落的 predicted 同键覆盖）；
    - execution_mode != "live" 或 completeness == 0 → 不提权，只更新 data_quality；
    - 一个 action 通常对应 1 条 Episode；对齐多条时全部同步。
    - 单独失败不阻塞主 collector 流程。
    """
    try:
        from app.models.agent_runtime import EpisodeDB
        rows = db.query(EpisodeDB).filter(EpisodeDB.action_id == action_id).all()
        if not rows:
            return
        completeness = float(envelope.get("completeness") or 0.0)
        for r in rows:
            impact = dict(r.impact_json or {})
            impact[f"impact_{window}"] = envelope
            dq = dict(r.data_quality_json or {})
            dq["impact_kind"] = kind
            dq["completeness"] = completeness
            sources = list(dq.get("sources") or [])
            src = envelope.get("source")
            if src and src not in sources:
                sources.append(src)
            dq["sources"] = sources
            r.impact_json = impact
            r.data_quality_json = dq
            if (r.execution_mode == "live"
                    and completeness > 0
                    and kind in ("observed", "attributed")):
                r.usable_for_learning = True
        db.flush()
    except Exception:
        logger.exception("promote episode after collect failed for action %s", action_id)


# --------------------------------------------------------------------------- #
# 核心：读事实表 → 计算 delta → 生成 envelope
# --------------------------------------------------------------------------- #
def _collect_one(db: Session, action: AgentActionDB, *, kind: str, window: str,
                 executed_at: datetime) -> Tuple[Dict[str, Any], bool]:
    action_time = action.verified_at or action.accepted_at or action.created_at
    action_day = action_time.date()
    window_dur = _WINDOW_SPECS[window]
    # FactMediaDaily / FactMMPDaily 是日粒度，所以窗口都按日对齐：
    #   pre  = [action_day - 7, action_day)  —— 严格早于动作当天
    #   post = [action_day, action_day + ceil(window_days)]  —— 含动作当天
    from math import ceil
    post_days = max(1, ceil(window_dur.total_seconds() / 86400))
    pre_start = action_day - _BASELINE
    pre_end = action_day
    post_start = action_day
    post_end = action_day + timedelta(days=post_days)

    if kind == "observed":
        source_id = _fact_media_source(action.platform)
        post_metrics, post_rows = _aggregate_media(
            db, action, post_start, post_end, source_id)
        pre_metrics, pre_rows = _aggregate_media(
            db, action, pre_start, pre_end, source_id)
        if pre_rows == 0 and post_rows == 0:
            return _empty_envelope(kind, window,
                                    source=source_id or "fact_media_daily",
                                    freshness=executed_at), False
        pre_days = max(1, (pre_end - pre_start).days)
        post_days = max(1, (post_end - post_start).days)
        delta = _delta_media(pre_metrics, post_metrics, pre_days, post_days)
        completeness = _completeness(pre_rows, post_rows)
        return make_observed(delta, window=window,
                             source=source_id or "fact_media_daily",
                             currency="USD",
                             completeness=completeness), True

    # attributed
    post_metrics, post_rows = _aggregate_mmp(
        db, action, post_start, post_end)
    pre_metrics, pre_rows = _aggregate_mmp(
        db, action, pre_start, pre_end)
    if pre_rows == 0 and post_rows == 0:
        return _empty_envelope(kind, window, source="appsflyer_mmp",
                                freshness=executed_at), False
    pre_days = max(1, (pre_end - pre_start).days)
    post_days = max(1, (post_end - post_start).days)
    delta = _delta_mmp(pre_metrics, post_metrics, pre_days, post_days)
    completeness = _completeness(pre_rows, post_rows)
    return make_attributed(delta, window=window, source="appsflyer_mmp",
                           currency="USD",
                           completeness=completeness), True


def _fact_media_source(platform: Optional[str]) -> str:
    """把 connector.platform 映射到 fact 表的 source_platform 值。"""
    if not platform:
        return ""
    p = str(platform).lower()
    if p in ("google", "google_ads"):
        return "google"
    if p in ("meta", "facebook"):
        return "meta"
    if p in ("tiktok", "tiktok_ads"):
        return "tiktok"
    if p == "mock":
        return "mock"
    return p


def _aggregate_media(db: Session, action: AgentActionDB,
                     start_day: date, end_day: date,
                     source_platform: str) -> Tuple[Dict[str, Any], int]:
    """在 FactMediaDaily 上按 (app_id, source_platform, campaign_id, date∈[start_day, end_day)) 聚合。"""
    from app.models.data import FactMediaDaily
    from sqlalchemy import func

    q = db.query(
        func.coalesce(func.sum(FactMediaDaily.spend_usd), 0),
        func.coalesce(func.sum(FactMediaDaily.impressions), 0),
        func.coalesce(func.sum(FactMediaDaily.clicks), 0),
        func.coalesce(func.sum(FactMediaDaily.media_installs), 0),
        func.count(FactMediaDaily.id),
    ).filter(
        FactMediaDaily.app_id == action.app_id,
        FactMediaDaily.campaign_id == action.entity_id,
        FactMediaDaily.date >= start_day,
        FactMediaDaily.date < end_day,
    )
    if source_platform:
        q = q.filter(FactMediaDaily.source_platform == source_platform)
    row = q.one()
    spend, impressions, clicks, installs, n = row
    return {
        "spend": float(spend or 0),
        "impressions": int(impressions or 0),
        "clicks": int(clicks or 0),
        "installs": int(installs or 0),
    }, int(n or 0)


def _aggregate_mmp(db: Session, action: AgentActionDB,
                   start_day: date, end_day: date) -> Tuple[Dict[str, Any], int]:
    """在 FactMMPDaily 上按 (app_id, campaign_id, date∈[start_day, end_day)) 聚合。"""
    from app.models.data import FactMMPDaily
    from sqlalchemy import func

    row = db.query(
        func.coalesce(func.sum(FactMMPDaily.attributed_installs), 0),
        func.coalesce(func.sum(FactMMPDaily.revenue_usd), 0),
        func.coalesce(func.sum(FactMMPDaily.cost_usd), 0),
        func.avg(FactMMPDaily.roi_d7),
        func.count(FactMMPDaily.id),
    ).filter(
        FactMMPDaily.app_id == action.app_id,
        FactMMPDaily.campaign_id == action.entity_id,
        FactMMPDaily.date >= start_day,
        FactMMPDaily.date < end_day,
    ).one()
    installs, revenue, cost, roi_d7, n = row
    return {
        "installs": int(installs or 0),
        "revenue": float(revenue or 0),
        "cost": float(cost or 0),
        "roi_d7": float(roi_d7) if roi_d7 is not None else None,
    }, int(n or 0)


def _delta_media(pre: Dict[str, Any], post: Dict[str, Any],
                 pre_days: int, post_days: int) -> Dict[str, Any]:
    """Media 事实表 delta：日均口径（避免不同长度窗口误比较）。"""
    pre_rate = {k: pre[k] / pre_days for k in ("spend", "impressions", "clicks", "installs")}
    post_rate = {k: post[k] / post_days for k in ("spend", "impressions", "clicks", "installs")}
    d_spend = post_rate["spend"] - pre_rate["spend"]
    d_imp = post_rate["impressions"] - pre_rate["impressions"]
    d_click = post_rate["clicks"] - pre_rate["clicks"]
    d_install = post_rate["installs"] - pre_rate["installs"]
    return {
        "delta_spend": round(d_spend, 4),
        "delta_impressions": round(d_imp, 2),
        "delta_clicks": round(d_click, 2),
        "delta_installs": round(d_install, 4),
        "delta_cpi": (round(post_rate["spend"] / post_rate["installs"], 4)
                       - round(pre_rate["spend"] / pre_rate["installs"], 4))
                       if pre_rate["installs"] and post_rate["installs"] else None,
        "delta_ctr": (round(post_rate["clicks"] / post_rate["impressions"], 6)
                       - round(pre_rate["clicks"] / pre_rate["impressions"], 6))
                       if pre_rate["impressions"] and post_rate["impressions"] else None,
    }


def _delta_mmp(pre: Dict[str, Any], post: Dict[str, Any],
               pre_days: int, post_days: int) -> Dict[str, Any]:
    """MMP 归因 delta：日均装机/营收/成本 + roi_d7 绝对差（roi 本身已是比率，不再日均化）。"""
    d_installs = post["installs"] / post_days - pre["installs"] / pre_days
    d_revenue = post["revenue"] / post_days - pre["revenue"] / pre_days
    d_cost = post["cost"] / post_days - pre["cost"] / pre_days
    d_roi = None
    if pre.get("roi_d7") is not None and post.get("roi_d7") is not None:
        d_roi = round(float(post["roi_d7"]) - float(pre["roi_d7"]), 6)
    return {
        "delta_installs": round(d_installs, 4),
        "delta_revenue": round(d_revenue, 4),
        "delta_cost": round(d_cost, 4),
        "delta_roi": d_roi,
    }


def _completeness(pre_rows: int, post_rows: int) -> float:
    """粗颗粒度：两个窗口都有数据 → 1.0；只有一边 → 0.5；都没有 → 0.0。"""
    if pre_rows > 0 and post_rows > 0:
        return 1.0
    if pre_rows > 0 or post_rows > 0:
        return 0.5
    return 0.0


def _empty_envelope(kind: str, window: str, source: str,
                    freshness: Optional[datetime]) -> Dict[str, Any]:
    """事实表命中 0 行时的 envelope：metrics 保持空，completeness=0.0。"""
    fresh_iso = freshness.isoformat() if isinstance(freshness, datetime) else None
    if kind == "observed":
        return make_observed({}, window=window, source=source,
                             completeness=0.0, freshness=fresh_iso)
    return make_attributed({}, window=window, source=source,
                           completeness=0.0, freshness=fresh_iso)
