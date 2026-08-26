"""P2 #4 —— Durable Background Jobs 测试。

覆盖：
- 基本入队/claim/执行（scheduled → running → done）。
- 幂等：同 idempotency_key 不重复入队。
- 异常路径：handler 抛错 → failed（max_attempts=1）；max_attempts>1 时回 scheduled 重试。
- Stale recovery：进程崩溃卡在 running 的 job 被 recover_stale 复位/失败。
- 重启恢复：新建 JobRunner 实例后，未完成的 job 仍能被 run_pending 拾起执行。
- 与 impact_collector 的端到端集成：enqueue_after_verified 入 agent_jobs，run_pending 执行。
- autonomy_scan handler：payload 驱动、扫描结果写 job.result。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.db.base import SessionLocal
from app.models.agent_runtime import (
    AgentActionDB, JobDB, EpisodeDB,
)
from app.models.data import FactMediaDaily, FactMMPDaily
from app.services.agent_runtime.impact import make_predicted
from app.services.agent_runtime.impact_collector import (
    enqueue_after_verified, run_impact_job,
)
from app.services.agent_runtime.jobs import (
    JobRunner, get_job_runner, register_default_handlers, reset_job_runner,
)


T0 = datetime(2026, 8, 26, 10, 0, 0)


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        s.query(JobDB).delete()
        s.query(EpisodeDB).delete()
        s.query(AgentActionDB).delete()
        s.commit()
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture(autouse=True)
def _reset_runner():
    reset_job_runner()
    yield
    reset_job_runner()


# --------------------------------------------------------------------------- #
# 基本生命周期
# --------------------------------------------------------------------------- #
def test_enqueue_and_run_happy_path(db):
    runner = JobRunner()
    seen = []

    def handler(session, payload):
        seen.append(payload)
        return {"ok": True, "echo": payload}

    runner.register("echo", handler)
    job = runner.enqueue(db, "echo", {"x": 1}, scheduled_at=T0,
                          idempotency_key="echo-1")
    db.commit()
    assert job.status == "scheduled"

    stats = runner.run_pending(db, now=T0)
    db.commit()
    assert stats == {"done": 1, "failed": 0, "missing_handler": 0}
    assert seen == [{"x": 1}]

    refreshed = db.query(JobDB).filter(JobDB.id == job.id).one()
    assert refreshed.status == "done"
    assert refreshed.result == {"ok": True, "echo": {"x": 1}}
    assert refreshed.attempts == 1
    assert refreshed.started_at is not None
    assert refreshed.finished_at is not None


def test_not_due_yet_is_skipped(db):
    runner = JobRunner()
    runner.register("noop", lambda s, p: None)
    runner.enqueue(db, "noop", {}, scheduled_at=T0 + timedelta(hours=1),
                    idempotency_key="future")
    db.commit()
    stats = runner.run_pending(db, now=T0)
    assert stats == {"done": 0, "failed": 0, "missing_handler": 0}
    pending = db.query(JobDB).filter(JobDB.status == "scheduled").count()
    assert pending == 1


def test_idempotent_enqueue(db):
    runner = JobRunner()
    j1 = runner.enqueue(db, "noop", {}, scheduled_at=T0, idempotency_key="dup")
    db.commit()
    j2 = runner.enqueue(db, "noop", {}, scheduled_at=T0, idempotency_key="dup")
    db.commit()
    assert j1 is not None
    assert j2 is None
    assert db.query(JobDB).filter(JobDB.idempotency_key == "dup").count() == 1


def test_missing_handler_marks_failed(db):
    runner = JobRunner()
    runner.enqueue(db, "unknown_type", {}, scheduled_at=T0,
                    idempotency_key="uh")
    db.commit()
    stats = runner.run_pending(db, now=T0)
    assert stats["missing_handler"] == 1
    job = db.query(JobDB).filter(JobDB.idempotency_key == "uh").one()
    assert job.status == "failed"
    assert "no handler" in (job.last_error or "")


def test_handler_exception_failed_after_max_attempts(db):
    runner = JobRunner()

    def boom(s, p):
        raise RuntimeError("kaboom")

    runner.register("boom", boom)
    runner.enqueue(db, "boom", {}, scheduled_at=T0,
                    idempotency_key="b", max_attempts=2)
    db.commit()
    # 第一次：attempts=1 < 2，回 scheduled
    stats = runner.run_pending(db, now=T0)
    assert stats["failed"] == 1
    job = db.query(JobDB).filter(JobDB.idempotency_key == "b").one()
    assert job.status == "scheduled"
    assert job.attempts == 1
    assert "kaboom" in (job.last_error or "")

    # 第二次：attempts=2 >= 2，落 failed
    stats = runner.run_pending(db, now=T0 + timedelta(seconds=1))
    assert stats["failed"] == 1
    job = db.query(JobDB).filter(JobDB.idempotency_key == "b").one()
    assert job.status == "failed"
    assert job.attempts == 2


def test_done_jobs_are_not_reprocessed(db):
    runner = JobRunner()
    calls = []

    def h(s, p):
        calls.append(1)
        return None

    runner.register("once", h)
    runner.enqueue(db, "once", {}, scheduled_at=T0, idempotency_key="o")
    db.commit()
    runner.run_pending(db, now=T0)
    db.commit()
    runner.run_pending(db, now=T0 + timedelta(minutes=1))
    db.commit()
    assert len(calls) == 1


# --------------------------------------------------------------------------- #
# Stale recovery & 重启恢复
# --------------------------------------------------------------------------- #
def test_recover_stale_resets_running_job(db):
    runner = JobRunner()
    runner.register("echo", lambda s, p: {"ok": True})
    job = runner.enqueue(db, "echo", {}, scheduled_at=T0,
                          idempotency_key="stale", max_attempts=3)
    db.commit()
    # 模拟进程崩溃：把 job 卡在 running，started_at 一小时前
    job.status = "running"
    job.started_at = T0 - timedelta(hours=1)
    job.attempts = 1
    db.commit()

    n = runner.recover_stale(db, now=T0, timeout=timedelta(minutes=10))
    db.commit()
    assert n == 1
    refreshed = db.query(JobDB).filter(JobDB.id == job.id).one()
    assert refreshed.status == "scheduled"
    assert refreshed.started_at is None

    # 模拟重启：新 runner 实例同样能捡起
    fresh_runner = JobRunner()
    fresh_runner.register("echo", lambda s, p: {"ok": True})
    stats = fresh_runner.run_pending(db, now=T0)
    assert stats["done"] == 1


def test_recover_stale_marks_failed_after_max_attempts(db):
    runner = JobRunner()
    job = runner.enqueue(db, "x", {}, scheduled_at=T0,
                          idempotency_key="stale2", max_attempts=1)
    db.commit()
    job.status = "running"
    job.started_at = T0 - timedelta(hours=1)
    job.attempts = 1
    db.commit()
    n = runner.recover_stale(db, now=T0)
    db.commit()
    assert n == 1
    refreshed = db.query(JobDB).filter(JobDB.id == job.id).one()
    assert refreshed.status == "failed"
    assert refreshed.finished_at is not None


def test_restart_picks_up_pending_jobs(db):
    """核心 durable 承诺：进程重启后 pending job 被新 runner 继续执行。"""
    runner1 = JobRunner()
    runner1.register("echo", lambda s, p: {"v": p["v"]})
    runner1.enqueue(db, "echo", {"v": 42}, scheduled_at=T0,
                     idempotency_key="persist")
    db.commit()
    # runner1 退出（不再引用），模拟重启

    runner2 = JobRunner()
    runner2.register("echo", lambda s, p: {"v": p["v"]})
    stats = runner2.run_pending(db, now=T0 + timedelta(seconds=1))
    assert stats["done"] == 1
    job = db.query(JobDB).filter(JobDB.idempotency_key == "persist").one()
    assert job.status == "done"
    assert job.result == {"v": 42}


# --------------------------------------------------------------------------- #
# Impact collector 端到端
# --------------------------------------------------------------------------- #
def _make_action(db, *, action_id="act_persist", entity_id="camp_p",
                  platform="google", verified_at=T0) -> AgentActionDB:
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


def _add_media(db, date_, campaign_id="camp_p", spend=100.0, installs=20,
                platform="google", seq=0):
    db.add(FactMediaDaily(
        app_id=1, source_platform=platform, source_type="report",
        date=date_, account_id="acct_1", app_key="test_app",
        media_source=platform, campaign_id=campaign_id, currency="USD",
        impressions=10000, clicks=200,
        spend=Decimal(str(spend)), spend_usd=Decimal(str(spend)),
        media_installs=installs,
        source_row_hash=f"m-{campaign_id}-{date_}-{seq}",
    ))


def test_impact_jobs_survive_runner_restart(db):
    act = _make_action(db)
    enqueue_after_verified(db, act, now=T0)
    db.commit()
    # 事实表数据：post 有、pre 有
    for i, d_off in enumerate([3, 5, 6]):
        _add_media(db, (T0 - timedelta(days=d_off)).date(),
                    spend=50.0, installs=10, seq=i)
    _add_media(db, T0.date(), spend=200.0, installs=40, seq=100)
    db.commit()

    # 重启：新进程的 runner 注册 handler 后跑 pending
    fresh = JobRunner()
    fresh.register("impact_collect", run_impact_job)
    stats = fresh.run_pending(db, now=T0 + timedelta(days=8))
    db.commit()
    # 6 条全部到点
    assert stats["done"] == 6

    act = db.query(AgentActionDB).filter(AgentActionDB.id == "act_persist").one()
    assert act.observed_impact_json is not None
    assert act.observed_impact_json["metrics"]["delta_spend"] > 0
    assert act.attributed_impact_json is not None


def test_impact_jobs_are_idempotent_across_restarts(db):
    act = _make_action(db, action_id="act_idem")
    enqueue_after_verified(db, act, now=T0)
    db.commit()
    # 再来一次不应新增
    enqueue_after_verified(db, act, now=T0)
    db.commit()
    assert db.query(JobDB).filter(
        JobDB.job_type == "impact_collect",
        JobDB.idempotency_key.like("impact:act_idem:%")
    ).count() == 6


# --------------------------------------------------------------------------- #
# Default handlers 注册
# --------------------------------------------------------------------------- #
def test_register_default_handlers_idempotent():
    reset_job_runner()
    register_default_handlers()
    runner = get_job_runner()
    assert runner.has("impact_collect")
    assert runner.has("autonomy_scan")
    # 再次调用不抛、不重复
    register_default_handlers()
    assert runner.has("impact_collect")


# --------------------------------------------------------------------------- #
# Autonomy scan handler
# --------------------------------------------------------------------------- #
def test_autonomy_scan_handler_invokes_engine(monkeypatch):
    from app.services.agent_runtime import autonomy as autonomy_mod

    called = []

    class FakeEngine:
        def scan(self, app_id):
            called.append(app_id)

    monkeypatch.setattr(autonomy_mod, "AutonomyEngine", lambda: FakeEngine())

    # 直接调 handler
    db = SessionLocal()
    try:
        result = autonomy_mod.run_autonomy_scan_job(db, {"app_id": 7})
    finally:
        db.close()
    assert called == [7]
    assert result["app_id"] == 7
    assert "elapsed_ms" in result
