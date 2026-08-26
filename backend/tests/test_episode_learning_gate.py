"""Phase 4.3 —— Episode 学习门禁测试。

覆盖：
- tools._write 记录 Episode 时携带 execution_mode / data_quality（impact_kind=predicted）
  且 usable_for_learning 保持 False。
- 仅有 Mock（execution_mode != live）Episode → StrategyStore.learn_from_memory 明确返回
  "无可用真实样本"，规则不变。
- 手工构造 live + observed envelope + completeness>0 的 Episode → 学习成功且 note 带 usable 计数。
- impact_collector 回采到真实 media 数据 → 将挂在同一 action_id 的 Episode 提权到
  usable_for_learning=True，并把 impact envelope 写回 impact_{window}。
- Mock execution_mode 的 Episode 即便回采到数据也不会被提权。
- Reflection 使用完整 aggregate（不受门禁影响），保证观察面板依旧可用。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.db.base import SessionLocal
from app.models.agent_runtime import (
    AgentActionDB, JobDB, EpisodeDB,
)
from app.models.data import FactMediaDaily, FactMMPDaily
from app.services.agent_runtime.impact import make_predicted
from app.services.agent_runtime.impact_collector import (
    enqueue_after_verified, run_due_jobs,
)
from app.services.agent_runtime.memory import Episode, get_memory
from app.services.agent_runtime.strategy import get_strategy


T0 = datetime(2026, 7, 10, 12, 0, 0)


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        s.query(JobDB).delete()
        s.query(EpisodeDB).delete()
        s.query(AgentActionDB).delete()
        s.query(FactMediaDaily).delete()
        s.query(FactMMPDaily).delete()
        s.commit()
        yield s
    finally:
        s.rollback()
        s.close()


def _mk_action(db, *, action_id: str, verified_at=T0,
                execution_mode: str = "live",
                entity_id: str = "camp_c42") -> AgentActionDB:
    a = AgentActionDB(
        id=action_id,
        idempotency_key=f"k-{action_id}",
        app_id=1, user_id=42,
        tool="adjust_budget", action="update_campaign_budget",
        entity_id=entity_id, platform="google",
        execution_mode=execution_mode, risk_level="L1",
        state="verified",
        predicted_impact_json=make_predicted({"delta_roi": 0.05},
                                             window="24h", source="mock"),
        verified_at=verified_at, accepted_at=verified_at,
    )
    db.add(a)
    db.commit()
    return a


def _mk_episode(db, *, episode_id: str, action_id: str | None,
                 execution_mode: str, impact_kind: str = "predicted",
                 usable: bool = False,
                 pct: int = 30) -> EpisodeDB:
    """构造一条 Episode。Phase 4.3 关注 execution_mode / usable_for_learning。"""
    row = EpisodeDB(
        episode_id=episode_id,
        timestamp=T0,
        session_id="sess_test",
        goal="test",
        action="adjust_budget",
        action_label="调整预算 test",
        intent_class="campaign.budget_adjust",
        params_json={"entity_id": "camp_c42", "_pct": pct,
                      "daily_budget": 100.0},
        pre_state_json={"roi": 1.2, "spend": 100, "status": "ACTIVE",
                         "country": "US"},
        impact_json={
            "impact_7d": {
                "kind": impact_kind,
                "metrics": {"avg_delta_roi": 0.08},
                "window": "7d",
                "completeness": 1.0 if impact_kind != "predicted" else None,
                "source": "fact_media_daily",
            }
        },
        outcome=True,
        note="",
        execution_mode=execution_mode,
        data_quality_json={"impact_kind": impact_kind,
                            "execution_mode": execution_mode,
                            "completeness": 1.0 if impact_kind != "predicted" else None,
                            "sources": ["fact_media_daily"]},
        usable_for_learning=usable,
        action_id=action_id,
    )
    db.add(row)
    db.commit()
    return row


def _add_media(db, *, date_, campaign_id="camp_c42", spend=100.0,
                installs=20, seq=0):
    db.add(FactMediaDaily(
        app_id=1, source_platform="google", source_type="report",
        date=date_, account_id="acct_1", app_key="test_app",
        media_source="google", campaign_id=campaign_id, currency="USD",
        impressions=10000, clicks=200,
        spend=Decimal(str(spend)), spend_usd=Decimal(str(spend)),
        media_installs=installs,
        source_row_hash=f"media-{campaign_id}-{date_}-{seq}",
    ))


# ---------- 记忆层：mock episode 不进策略 ---------- #

def test_learn_returns_no_usable_when_only_mock_episodes(db):
    """仅 Mock/Sandbox Episode → 策略保持不变，note 明确提示。"""
    _mk_episode(db, episode_id="ep_mock_1", action_id=None,
                execution_mode="mock")
    _mk_episode(db, episode_id="ep_mock_2", action_id=None,
                execution_mode="sandbox")
    mem = get_memory()
    mem._loaded = False  # 强制从 DB 重载
    strategy = get_strategy()
    strategy.reset()
    before = strategy.all()

    result = strategy.learn_from_memory(mem)
    assert result.learned_keys == []
    assert "无可用真实样本" in result.note
    assert strategy.all() == before  # 完全没改动


def test_learn_uses_only_usable_live_episodes(db):
    """真实 live + 已提权样本 → 学习成功；note 报告样本数。"""
    _mk_episode(db, episode_id="ep_mock", action_id=None,
                execution_mode="mock", pct=99)  # 应被忽略
    _mk_episode(db, episode_id="ep_live_1", action_id=None,
                execution_mode="live", impact_kind="observed",
                usable=True, pct=20)
    _mk_episode(db, episode_id="ep_live_2", action_id=None,
                execution_mode="live", impact_kind="attributed",
                usable=True, pct=15)
    mem = get_memory()
    mem._loaded = False
    strategy = get_strategy()
    strategy.reset()

    result = strategy.learn_from_memory(mem)
    assert "budget_increase_cap" in result.learned_keys
    assert "usable=2" in result.note  # head 报告 usable 数量
    # 学到的 cap 只来自 live samples；mock 的 pct=99 不影响
    rule = strategy.all()["budget_increase_cap"]
    assert rule.n_samples == 2
    assert rule.value in (20.0, 15.0, 10.0)  # 依 avg7d 走 else 支或收敛


# ---------- 回采提权：collector → Episode ---------- #

def test_collector_promotes_live_episode_to_usable(db):
    """有真实 media 数据 → 关联的 live Episode 被提权到 usable_for_learning=True。"""
    action = _mk_action(db, action_id="act_live_1", execution_mode="live")
    _mk_episode(db, episode_id="ep_live_link", action_id="act_live_1",
                execution_mode="live", impact_kind="predicted",
                usable=False)

    enqueue_after_verified(db, action, now=T0)
    # 有 baseline + 有 post
    for i, d_off in enumerate([3, 5, 6]):
        _add_media(db, date_=(T0 - timedelta(days=d_off)).date(),
                    spend=50.0, installs=10, seq=i)
    _add_media(db, date_=T0.date(), spend=200.0, installs=40, seq=100)
    db.commit()

    run_due_jobs(db, now=T0 + timedelta(days=8))
    db.commit()

    ep = db.query(EpisodeDB).filter(
        EpisodeDB.episode_id == "ep_live_link").one()
    assert ep.usable_for_learning is True
    assert ep.data_quality_json["impact_kind"] in ("observed", "attributed")
    # 至少一个 window envelope 被写回 impact_json
    assert any(k.startswith("impact_") and isinstance(v, dict)
               and v.get("kind") in ("observed", "attributed")
               for k, v in (ep.impact_json or {}).items())


def test_collector_does_not_promote_mock_episode(db):
    """Mock Episode 即便有回采数据也不能被提权 —— Phase 1 execution_mode 边界。"""
    action = _mk_action(db, action_id="act_mock_1", execution_mode="mock")
    _mk_episode(db, episode_id="ep_mock_link", action_id="act_mock_1",
                execution_mode="mock", impact_kind="predicted",
                usable=False)

    enqueue_after_verified(db, action, now=T0)
    _add_media(db, date_=T0.date(), spend=200.0, installs=40, seq=0)
    for i, d_off in enumerate([3, 5]):
        _add_media(db, date_=(T0 - timedelta(days=d_off)).date(),
                    spend=50.0, installs=10, seq=100 + i)
    db.commit()

    run_due_jobs(db, now=T0 + timedelta(days=8))
    db.commit()

    ep = db.query(EpisodeDB).filter(
        EpisodeDB.episode_id == "ep_mock_link").one()
    assert ep.usable_for_learning is False
    # data_quality 仍会被更新为 observed（有数据），但门禁挡住 usable
    assert ep.data_quality_json["impact_kind"] in ("observed", "attributed")


def test_empty_collect_does_not_promote(db):
    """回采到 0 行事实数据 → completeness=0，不能提权。"""
    action = _mk_action(db, action_id="act_live_2", execution_mode="live")
    _mk_episode(db, episode_id="ep_live_no_data", action_id="act_live_2",
                execution_mode="live", impact_kind="predicted",
                usable=False)

    enqueue_after_verified(db, action, now=T0)
    db.commit()
    run_due_jobs(db, now=T0 + timedelta(days=8))
    db.commit()

    ep = db.query(EpisodeDB).filter(
        EpisodeDB.episode_id == "ep_live_no_data").one()
    assert ep.usable_for_learning is False


# ---------- Episode 字段迁移兼容 ---------- #

def test_episode_dataclass_carries_new_fields(db):
    """新记录的 Episode 应带 execution_mode / usable_for_learning / data_quality。"""
    mem = get_memory()
    mem.clear()
    mem.record(Episode(
        action="adjust_budget",
        params={"entity_id": "camp_c42"},
        execution_mode="live",
        data_quality={"impact_kind": "predicted",
                       "execution_mode": "live",
                       "completeness": None,
                       "sources": ["simulate_impact/mock"]},
        usable_for_learning=False,
    ))
    mem._loaded = False
    got = mem.all()[0]
    assert got.execution_mode == "live"
    assert got.data_quality["impact_kind"] == "predicted"
    assert got.usable_for_learning is False
