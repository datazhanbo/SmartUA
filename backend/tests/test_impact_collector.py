"""Phase 4.2 —— 延迟回采 impact_collector 单元测试。

覆盖：
- verified 动作 → enqueue 6 条 job（observed × 3 + attributed × 3）。
- 到点 job 才被 run_due_jobs 拾起；未到点跳过。
- FactMediaDaily 有数据 → observed envelope 写回 AgentActionDB，metrics 反映 delta。
- FactMMPDaily 有数据 → attributed envelope 写回 AgentActionDB。
- 事实表命中 0 行 → envelope 保留 metrics={}, completeness=0.0（**Phase 4.1 不变量**：
  没观察到不能冒充 0 delta）。
- 已 done 的 job 幂等：再次 run_due_jobs 不重复处理。
- 无 entity_id 的动作 → enqueue 为空（回采查不到）。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.db.base import SessionLocal
from app.models.agent_runtime import AgentActionDB, AgentImpactJobDB
from app.models.data import FactMediaDaily, FactMMPDaily
from app.services.agent_runtime.impact import make_predicted
from app.services.agent_runtime.impact_collector import (
    enqueue_after_verified, run_due_jobs,
)


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        s.query(AgentImpactJobDB).delete()
        s.query(AgentActionDB).delete()
        s.query(FactMediaDaily).delete()
        s.query(FactMMPDaily).delete()
        s.commit()
        yield s
    finally:
        s.rollback()
        s.close()


T0 = datetime(2026, 7, 10, 12, 0, 0)  # 动作 verified 时间


def _make_action(db, *, entity_id="camp_c42", platform="google",
                 verified_at=T0, action_id="act_c42") -> AgentActionDB:
    act = AgentActionDB(
        id=action_id,
        idempotency_key=f"k-{action_id}",
        session_id=None, step_id=None,
        app_id=1, user_id=42,
        tool="adjust_budget", action="update_campaign_budget",
        entity_id=entity_id, platform=platform,
        execution_mode="live", risk_level="L1",
        state="verified",
        predicted_impact_json=make_predicted(
            {"delta_roi": 0.05}, window="24h", source="simulate_impact/mock"),
        verified_at=verified_at, accepted_at=verified_at,
    )
    db.add(act)
    db.commit()
    return act


def _add_media(db, *, date_, campaign_id="camp_c42", spend=100.0,
                impressions=10000, clicks=200, installs=20,
                platform="google", app_id=1, seq=0):
    """写一行 FactMediaDaily。source_row_hash 用日期+entity+seq 保证唯一。"""
    row = FactMediaDaily(
        app_id=app_id,
        source_platform=platform,
        source_type="report",
        date=date_,
        account_id="acct_1",
        app_key="test_app",
        media_source=platform,
        campaign_id=campaign_id,
        currency="USD",
        impressions=impressions,
        clicks=clicks,
        spend=Decimal(str(spend)),
        spend_usd=Decimal(str(spend)),
        media_installs=installs,
        source_row_hash=f"media-{campaign_id}-{date_}-{seq}",
    )
    db.add(row)


def _add_mmp(db, *, date_, campaign_id="camp_c42", installs=10,
              revenue=50.0, cost=80.0, roi_d7=0.05, app_id=1, seq=0):
    row = FactMMPDaily(
        app_id=app_id,
        mmp="appsflyer",
        date=date_,
        app_key="test_app",
        media_source="google",
        campaign_id=campaign_id,
        currency="USD",
        attributed_installs=installs,
        revenue=Decimal(str(revenue)),
        revenue_usd=Decimal(str(revenue)),
        cost=Decimal(str(cost)),
        cost_usd=Decimal(str(cost)),
        roi_d7=Decimal(str(roi_d7)) if roi_d7 is not None else None,
        source_row_hash=f"mmp-{campaign_id}-{date_}-{seq}",
    )
    db.add(row)


# ------------------------ enqueue 语义 ------------------------ #

def test_enqueue_creates_six_jobs(db):
    act = _make_action(db)
    jobs = enqueue_after_verified(db, act, now=T0)
    db.commit()
    assert len(jobs) == 6
    kinds = sorted((j.kind, j.window) for j in jobs)
    assert kinds == [
        ("attributed", "24h"), ("attributed", "2h"), ("attributed", "7d"),
        ("observed", "24h"),   ("observed", "2h"),   ("observed", "7d"),
    ]
    # scheduled_at 相对 verified_at 精确
    by_key = {(j.kind, j.window): j for j in jobs}
    assert by_key[("observed", "2h")].scheduled_at == T0 + timedelta(hours=2)
    assert by_key[("observed", "24h")].scheduled_at == T0 + timedelta(hours=24)
    assert by_key[("observed", "7d")].scheduled_at == T0 + timedelta(days=7)


def test_enqueue_no_entity_id_returns_empty(db):
    act = _make_action(db, entity_id=None, action_id="act_no_eid")
    jobs = enqueue_after_verified(db, act)
    assert jobs == []


def test_enqueue_is_idempotent(db):
    act = _make_action(db)
    enqueue_after_verified(db, act, now=T0)
    db.commit()
    # 再来一次不应新增
    again = enqueue_after_verified(db, act, now=T0)
    db.commit()
    assert again == []
    assert db.query(AgentImpactJobDB).filter(
        AgentImpactJobDB.action_id == act.id).count() == 6


# ------------------------ run_due_jobs 时序 ------------------------ #

def test_not_due_yet_jobs_are_skipped(db):
    act = _make_action(db)
    enqueue_after_verified(db, act, now=T0)
    db.commit()
    # 早于所有 job 的时刻 → 全跳过
    stats = run_due_jobs(db, now=T0 + timedelta(minutes=30))
    db.commit()
    assert stats == {"done": 0, "empty": 0, "failed": 0}
    assert db.query(AgentImpactJobDB).filter(
        AgentImpactJobDB.status == "scheduled").count() == 6


def test_2h_window_runs_but_7d_still_pending(db):
    act = _make_action(db)
    enqueue_after_verified(db, act, now=T0)
    db.commit()
    # T0 + 3h：2h window（observed+attributed）应该 due，24h/7d 还没到
    stats = run_due_jobs(db, now=T0 + timedelta(hours=3))
    db.commit()
    # 无事实数据 → empty=2
    assert stats["done"] + stats["empty"] == 2
    still_scheduled = db.query(AgentImpactJobDB).filter(
        AgentImpactJobDB.status == "scheduled").count()
    assert still_scheduled == 4


# ------------------------ observed 回采：真实数据 ------------------------ #

def test_observed_envelope_reflects_media_delta(db):
    act = _make_action(db)
    enqueue_after_verified(db, act, now=T0)
    # 动作前 baseline：3 天，每天 spend=50, installs=10
    for i, d_off in enumerate([3, 5, 6]):
        _add_media(db, date_=(T0 - timedelta(days=d_off)).date(),
                    spend=50.0, installs=10, seq=i)
    # 动作后 24h 窗口内：spend=200, installs=40 —— 明显放量
    _add_media(db, date_=T0.date(), spend=200.0, installs=40, seq=100)
    db.commit()

    stats = run_due_jobs(db, now=T0 + timedelta(hours=25))
    db.commit()
    # 24h 和 2h 的 observed+attributed 都到点了（4 条）
    assert stats["done"] + stats["empty"] == 4

    act = db.query(AgentActionDB).filter(AgentActionDB.id == "act_c42").one()
    env = act.observed_impact_json
    assert env is not None
    assert env["kind"] == "observed"
    # 24h 窗口是最后一次覆盖（enqueue 顺序 2h 在前，24h 在后 —— run_due_jobs 按 scheduled_at 升序处理）
    # 关键断言：spend delta 反映真实变化，不是 predicted 值
    metrics = env["metrics"]
    assert metrics["delta_spend"] > 0
    assert metrics["delta_installs"] > 0
    assert env["source"] == "google"
    assert env["completeness"] == 1.0  # pre + post 都有数据


def test_observed_empty_when_no_fact_rows(db):
    """核心不变量：事实表 0 行 → envelope 保留空 metrics，completeness=0，禁止用 0 冒充。"""
    act = _make_action(db)
    enqueue_after_verified(db, act, now=T0)
    db.commit()
    stats = run_due_jobs(db, now=T0 + timedelta(days=8))  # 所有 job 全 due
    db.commit()
    assert stats["empty"] == 6
    assert stats["done"] == 0

    act = db.query(AgentActionDB).filter(AgentActionDB.id == "act_c42").one()
    assert act.observed_impact_json is not None
    assert act.observed_impact_json["kind"] == "observed"
    assert act.observed_impact_json["metrics"] == {}
    assert act.observed_impact_json["completeness"] == 0.0
    assert act.attributed_impact_json["metrics"] == {}
    assert act.attributed_impact_json["completeness"] == 0.0


# ------------------------ attributed 回采：MMP ------------------------ #

def test_attributed_envelope_reflects_mmp_delta(db):
    act = _make_action(db)
    enqueue_after_verified(db, act, now=T0)
    # baseline：7天窗口内 2 个非零日，ROI 0.03
    for i, d_off in enumerate([3, 5]):
        _add_mmp(db, date_=(T0 - timedelta(days=d_off)).date(),
                  installs=20, revenue=30.0, cost=100.0, roi_d7=0.03, seq=i)
    # post 7天窗口内多个日 —— 每天都有 40 装机
    for i, d_off in enumerate(range(0, 7)):
        _add_mmp(db, date_=(T0 + timedelta(days=d_off)).date(),
                  installs=40, revenue=80.0, cost=100.0, roi_d7=0.10, seq=100 + i)
    db.commit()

    run_due_jobs(db, now=T0 + timedelta(days=8))
    db.commit()

    act = db.query(AgentActionDB).filter(AgentActionDB.id == "act_c42").one()
    env = act.attributed_impact_json
    assert env is not None
    assert env["kind"] == "attributed"
    assert env["source"] == "appsflyer_mmp"
    metrics = env["metrics"]
    # ROI 从 0.03 → 0.10，delta ≈ 0.07
    assert metrics["delta_roi"] == pytest.approx(0.07, abs=1e-4)
    # 日均装机 post ≈ 40/day，pre ≈ 40/7/day ≈ 5.7/day → delta > 0
    assert metrics["delta_installs"] > 0
    assert metrics["delta_revenue"] > 0
    assert env["completeness"] == 1.0


# ------------------------ 幂等 ------------------------ #

def test_run_due_jobs_is_idempotent(db):
    act = _make_action(db)
    enqueue_after_verified(db, act, now=T0)
    db.commit()

    stats1 = run_due_jobs(db, now=T0 + timedelta(days=8))
    db.commit()
    assert stats1["empty"] == 6
    # 全部标记 done，再跑一次不应重复处理
    stats2 = run_due_jobs(db, now=T0 + timedelta(days=8))
    db.commit()
    assert stats2 == {"done": 0, "empty": 0, "failed": 0}
