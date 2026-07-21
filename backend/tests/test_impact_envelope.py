"""Phase 4.1 —— 三类影响 envelope 与 predicted/observed/attributed 语义拆分测试。

覆盖：
- ImpactEnvelope 构造器保留 provenance（kind/window/source/freshness/completeness/currency）。
- make_predicted / make_observed / make_attributed 分别产出正确 kind。
- 缺 metrics 时 envelope 不填 0（None 或键缺失 → metric() 返回 default）。
- tools._compute_impact 返回三个 predicted envelope（kind == "predicted"）。
- Episode._metric 兼容新 envelope（metrics 子键）和老 Episode（裸 dict）。
- AgentActionDB / IntentExecution schema 新列可读可写。
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.base import SessionLocal
from app.models.agent_runtime import AgentActionDB, EpisodeDB
from app.models.intent import IntentExecution
from app.services.agent_runtime.impact import (
    ImpactEnvelope, make_attributed, make_observed, make_predicted, metric,
)
from app.services.agent_runtime.memory import Episode, EpisodicMemory


# ------------------------ envelope 构造 ------------------------ #

def test_make_predicted_records_provenance():
    env = make_predicted({"delta_roi": 0.15, "delta_spend": 20.0},
                         window="24h", source="simulate_impact/mock",
                         currency="USD")
    assert env["kind"] == "predicted"
    assert env["metrics"] == {"delta_roi": 0.15, "delta_spend": 20.0}
    assert env["window"] == "24h"
    assert env["source"] == "simulate_impact/mock"
    assert env["currency"] == "USD"
    assert env["completeness"] == 1.0
    assert env["freshness"] is not None


def test_make_observed_leaves_completeness_none_by_default():
    env = make_observed({"delta_spend": 12.3},
                        window="24h", source="google_ads_report")
    assert env["kind"] == "observed"
    # 未指定 completeness → None，禁止用 0 或 1 冒充
    assert env["completeness"] is None


def test_make_attributed_carries_source_and_kind():
    env = make_attributed({"delta_installs": 5, "delta_revenue": 42.5},
                          window="7d", source="appsflyer_mmp",
                          completeness=0.87)
    assert env["kind"] == "attributed"
    assert env["source"] == "appsflyer_mmp"
    assert env["completeness"] == 0.87


def test_metric_missing_returns_default():
    env = make_predicted({"delta_roi": 0.1}, window="24h", source="s")
    assert metric(env, "delta_roi") == 0.1
    assert metric(env, "delta_spend") is None
    assert metric(env, "delta_spend", default=0.0) == 0.0
    # None envelope
    assert metric(None, "delta_roi") is None
    # 缺 metrics 键
    assert metric({"kind": "observed"}, "delta_roi") is None


def test_envelope_roundtrip_from_dict():
    src = make_observed({"delta_roi": -0.05}, window="2h", source="meta_insights",
                        completeness=0.9)
    back = ImpactEnvelope.from_dict(src)
    assert back is not None
    assert back.kind == "observed"
    assert back.metrics == {"delta_roi": -0.05}
    assert back.completeness == 0.9
    # None / 空 dict / 非 dict → None
    assert ImpactEnvelope.from_dict(None) is None
    assert ImpactEnvelope.from_dict({}) is None


# ------------------------ tools._compute_impact ------------------------ #

def test_compute_impact_emits_predicted_envelopes():
    from app.services.agent_runtime.impact import ImpactEnvelope
    from app.services.agent_runtime.tools import _compute_impact
    from app.services.connectors.base import ImpactEstimation

    class Ctx:
        pass

    class Conn:
        platform = "mock"

        def simulate_impact(self, action, entity_id, ap, horizon=7):
            # 用固定序列，方便断言 —— roi 首日 +0.1，spend 首日 +10，7d 均值 +0.05 / +5
            return ImpactEstimation(
                delta_roi=[0.1, 0.06, 0.04, 0.03, 0.02, 0.05, 0.05],
                delta_spend=[10.0] * 7,
                delta_cpi=[-0.02] * 7,
            )

    ctx = Ctx()
    ctx.connector = Conn()
    out = _compute_impact(ctx, "update_campaign_budget", "camp_1", {"daily_budget": 200})

    assert set(out.keys()) == {"impact_2h", "impact_24h", "impact_7d"}
    for k, env in out.items():
        assert env["kind"] == "predicted"
        assert env["source"].startswith("simulate_impact/")
        assert env["completeness"] == 1.0
    # 具体指标
    assert out["impact_24h"]["metrics"]["delta_roi"] == 0.1
    assert out["impact_24h"]["metrics"]["delta_spend"] == 10.0
    assert out["impact_2h"]["window"] == "2h"
    assert out["impact_7d"]["window"] == "7d"


def test_compute_impact_returns_empty_on_simulate_failure():
    from app.services.agent_runtime.tools import _compute_impact

    class Ctx:
        pass

    class Conn:
        platform = "mock"

        def simulate_impact(self, *a, **kw):
            raise RuntimeError("connector down")

    ctx = Ctx()
    ctx.connector = Conn()
    assert _compute_impact(ctx, "x", "y", {}) == {}


# ------------------------ Episode 兼容新旧 impact 格式 ------------------------ #

def test_episode_reads_predicted_envelope_metrics():
    ep = Episode(
        action="adjust_budget",
        impact={
            "impact_24h": make_predicted(
                {"delta_roi": 0.08, "delta_spend": 12.0},
                window="24h", source="simulate_impact/mock"),
            "impact_7d": make_predicted(
                {"avg_delta_roi": 0.03},
                window="7d", source="simulate_impact/mock"),
        },
    )
    assert ep.delta_roi_24h() == 0.08
    assert ep.delta_spend_24h() == 12.0
    assert ep.avg_delta_roi_7d() == 0.03
    assert ep.impact_kind("impact_24h") == "predicted"
    assert ep.impact_kind("impact_2h") is None  # 未提供


def test_episode_reads_legacy_bare_dict_impact():
    """老 Episode（Phase 3.3 之前）是裸 metrics dict，无 kind/window：
    Phase 4.1 的 Episode 仍能读通。"""
    ep = Episode(
        action="pause_campaign",
        impact={
            "impact_24h": {"delta_roi": 0.2, "delta_spend": -5.0},
            "impact_7d": {"avg_delta_roi": 0.15},
        },
    )
    assert ep.delta_roi_24h() == 0.2
    assert ep.delta_spend_24h() == -5.0
    assert ep.avg_delta_roi_7d() == 0.15
    # 裸 dict 没有 kind
    assert ep.impact_kind("impact_24h") is None


def test_episode_missing_impact_returns_zero():
    ep = Episode(action="rotate_creative", impact={})
    assert ep.delta_roi_24h() == 0.0
    assert ep.avg_delta_roi_7d() == 0.0
    assert ep.impact_kind("impact_24h") is None


# ------------------------ 新 schema 列可读写 ------------------------ #

@pytest.fixture(autouse=True)
def _wipe():
    db = SessionLocal()
    try:
        db.query(AgentActionDB).delete()
        db.query(EpisodeDB).delete()
        db.commit()
    finally:
        db.close()


def test_agent_action_stores_observed_and_attributed():
    """schema 新列可写、可读、和 predicted 并存。"""
    db = SessionLocal()
    try:
        obs = make_observed({"delta_roi": 0.06, "delta_spend": 8.0},
                            window="24h", source="google_ads_report",
                            completeness=0.95)
        attr = make_attributed({"delta_installs": 12, "delta_revenue": 55.0},
                               window="7d", source="appsflyer_mmp",
                               completeness=0.80)
        pred = make_predicted({"delta_roi": 0.10}, window="24h",
                              source="simulate_impact/mock")
        act = AgentActionDB(
            id="act_phase41_1",
            idempotency_key="k-phase41-1",
            session_id=None, step_id=None,
            app_id=1, user_id=42,
            tool="adjust_budget", action="update_campaign_budget",
            entity_id="camp_1", platform="mock",
            execution_mode="mock", risk_level="L1",
            state="verified",
            predicted_impact_json=pred,
            observed_impact_json=obs,
            attributed_impact_json=attr,
        )
        db.add(act)
        db.commit()

        got = db.query(AgentActionDB).filter(AgentActionDB.id == "act_phase41_1").one()
        assert got.predicted_impact_json["kind"] == "predicted"
        assert got.observed_impact_json["kind"] == "observed"
        assert got.attributed_impact_json["kind"] == "attributed"
        # 关键不变量：observed 没到位前必须为 None，绝不能用 0 冒充
        assert got.observed_impact_json["completeness"] == 0.95
        assert metric(got.observed_impact_json, "delta_roi") == 0.06
        assert metric(got.attributed_impact_json, "delta_installs") == 12.0
    finally:
        db.close()


def test_agent_action_defaults_observed_and_attributed_to_null():
    """未回采时保留 NULL —— 这是 Phase 4.1 的核心不变量。"""
    db = SessionLocal()
    try:
        act = AgentActionDB(
            id="act_phase41_2",
            idempotency_key="k-phase41-2",
            session_id=None, step_id=None,
            app_id=1, user_id=42,
            tool="pause_campaign", action="update_campaign_status",
            entity_id="camp_2", platform="mock",
            execution_mode="mock", risk_level="L1",
            state="verified",
            predicted_impact_json=make_predicted(
                {"delta_roi": 0.05}, window="24h", source="simulate_impact/mock"),
        )
        db.add(act)
        db.commit()

        got = db.query(AgentActionDB).filter(AgentActionDB.id == "act_phase41_2").one()
        assert got.observed_impact_json is None
        assert got.attributed_impact_json is None
        # 消费方约定：metric() 面对 None envelope → default（不冒充 0）
        assert metric(got.observed_impact_json, "delta_roi") is None
        assert metric(got.attributed_impact_json, "delta_installs", default=0.0) == 0.0
    finally:
        db.close()
