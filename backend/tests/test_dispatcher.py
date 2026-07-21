"""Phase 3.3 —— 同步 Dispatcher 的单元测试。

覆盖：
- 提议 → 审批 → 派发 → 回读 → verified 的黄金路径，媒体只叫一次。
- 幂等：同一 idempotency_key 重复 dispatch_and_verify，不会二次调媒体。
- 媒体抛异常 → unknown（等对账，不重试）。
- 媒体返回 success=False → failed。
- 媒体返回 success=True 但回读缺失 → unknown（保守）。
- 回读值和预期不匹配 → unknown（延迟或偏移，交对账）。
- reconcile：unknown 动作再拉一次媒体，匹配 → verified；不匹配 → failed。
- 无 read_state / 无 entity_id → 停在 unknown（不冒充 verified）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from app.db.base import SessionLocal
from app.models.agent_runtime import AgentActionDB
from app.services.agent_runtime.action_store import ActionRequest, AgentActionStore
from app.services.agent_runtime.dispatcher import Dispatcher


def _fresh_db():
    return SessionLocal()


def _req(**overrides):
    base = dict(
        session_id="s-phase33",
        step_id="step-1",
        app_id=1,
        user_id=42,
        tool="pause_campaign",
        action="update_campaign_status",
        entity_id="camp_disp",
        platform="mock",
        account_id="acct_1",
        execution_mode="mock",
        risk_level="L1",
        request={"status": "PAUSED"},
    )
    base.update(overrides)
    return ActionRequest(**base)


@pytest.fixture(autouse=True)
def _wipe_actions():
    db = _fresh_db()
    try:
        db.query(AgentActionDB).delete()
        db.commit()
    finally:
        db.close()


# ------------------------ Happy path + 幂等 ------------------------ #

def test_happy_path_reaches_verified_and_calls_media_once():
    db = _fresh_db()
    call_count = {"n": 0}

    def media():
        call_count["n"] += 1
        return {"success": True, "provider_request_id": "req-123"}

    def read_state(eid):
        return {"status": "PAUSED", "daily_budget": None}

    dispatcher = Dispatcher(store=AgentActionStore())
    try:
        outcome = dispatcher.dispatch_and_verify(
            db, _req(), media_call=media, read_state=read_state)
        db.commit()
        assert outcome.state == "verified"
        assert call_count["n"] == 1
        assert outcome.action.provider_request_id == "req-123"

        # 幂等重试：同一 req 再来一次 —— 不再调媒体
        outcome2 = dispatcher.dispatch_and_verify(
            db, _req(), media_call=media, read_state=read_state)
        assert outcome2.state == "verified"
        assert outcome2.action.id == outcome.action.id
        assert call_count["n"] == 1  # 关键：不重复
    finally:
        db.close()


def test_verified_short_circuits_before_dispatch():
    """已经 verified 的动作，dispatch_and_verify 立即返回，不重放。"""
    db = _fresh_db()
    dispatcher = Dispatcher()
    calls = []

    def read_state(eid):
        return {"status": "PAUSED"}

    dispatcher.dispatch_and_verify(
        db, _req(), media_call=lambda: {"success": True}, read_state=read_state)
    db.commit()

    # 第二次派发用会失败的 media（如果被叫到就报错），验证短路。
    def boom():
        calls.append(1)
        raise RuntimeError("should not be called")

    outcome = dispatcher.dispatch_and_verify(
        db, _req(), media_call=boom, read_state=read_state)
    assert outcome.state == "verified"
    assert calls == []
    db.close()


# ------------------------ 失败 / 不确定 ------------------------ #

def test_media_exception_transitions_to_unknown():
    db = _fresh_db()

    def boom():
        raise TimeoutError("network flapped")

    outcome = Dispatcher().dispatch_and_verify(
        db, _req(step_id="step-boom"), media_call=boom,
        read_state=lambda eid: {"status": "PAUSED"})
    db.commit()
    assert outcome.state == "unknown"
    assert "raised" in outcome.observation
    # 状态机确实推进过 approved → dispatching → unknown
    assert outcome.action.dispatched_at is not None
    db.close()


def test_media_explicit_failure_transitions_to_failed():
    db = _fresh_db()

    def rejected():
        return {"success": False, "error": "budget too low"}

    outcome = Dispatcher().dispatch_and_verify(
        db, _req(step_id="step-fail"), media_call=rejected,
        read_state=lambda eid: {"status": "ACTIVE"})
    db.commit()
    assert outcome.state == "failed"
    assert "budget too low" in (outcome.action.error or "")
    db.close()


def test_media_ambiguous_success_flag_is_unknown():
    """provider 返回 dict 但没有 success 字段 → unknown（不冒充成功）。"""
    db = _fresh_db()

    def ambiguous():
        return {"note": "queued"}

    outcome = Dispatcher().dispatch_and_verify(
        db, _req(step_id="step-amb"), media_call=ambiguous,
        read_state=lambda eid: {"status": "PAUSED"})
    db.commit()
    assert outcome.state == "unknown"
    db.close()


def test_read_state_returns_none_after_accepted_is_unknown():
    db = _fresh_db()

    outcome = Dispatcher().dispatch_and_verify(
        db, _req(step_id="step-null-read"),
        media_call=lambda: {"success": True},
        read_state=lambda eid: None)
    db.commit()
    assert outcome.state == "unknown"
    assert "None" in outcome.observation or "read_state" in outcome.observation.lower()
    db.close()


def test_read_state_mismatch_is_unknown():
    """媒体已 accept 但账户读回的 status 和预期不同 → unknown（可能延迟，交对账）。"""
    db = _fresh_db()

    outcome = Dispatcher().dispatch_and_verify(
        db, _req(step_id="step-mismatch"),
        media_call=lambda: {"success": True},
        read_state=lambda eid: {"status": "ACTIVE"})
    db.commit()
    assert outcome.state == "unknown"
    assert "mismatch" in outcome.observation.lower()
    db.close()


def test_no_read_state_no_entity_stays_unknown():
    db = _fresh_db()

    outcome = Dispatcher().dispatch_and_verify(
        db, _req(step_id="step-no-read", entity_id=None),
        media_call=lambda: {"success": True},
        read_state=None)
    db.commit()
    assert outcome.state == "unknown"
    db.close()


# ------------------------ 预算动作的相对差判定 ------------------------ #

def test_budget_within_tolerance_verified():
    db = _fresh_db()
    req = _req(step_id="step-bud", tool="adjust_budget",
               action="update_campaign_budget",
               request={"daily_budget": 100.0})

    outcome = Dispatcher().dispatch_and_verify(
        db, req, media_call=lambda: {"success": True},
        read_state=lambda eid: {"status": "ACTIVE", "daily_budget": 101.5})
    db.commit()
    # 相对差 1.5% < 5% → verified
    assert outcome.state == "verified"
    db.close()


def test_budget_outside_tolerance_unknown():
    db = _fresh_db()
    req = _req(step_id="step-bud2", tool="adjust_budget",
               action="update_campaign_budget",
               request={"daily_budget": 100.0})

    outcome = Dispatcher().dispatch_and_verify(
        db, req, media_call=lambda: {"success": True},
        read_state=lambda eid: {"status": "ACTIVE", "daily_budget": 130.0})
    db.commit()
    assert outcome.state == "unknown"
    db.close()


# ------------------------ reconcile ------------------------ #

def test_reconcile_unknown_to_verified():
    db = _fresh_db()
    dispatcher = Dispatcher()
    req = _req(step_id="step-rec-ok")

    # 先制造一个 unknown：read_state 拿到 None
    outcome = dispatcher.dispatch_and_verify(
        db, req, media_call=lambda: {"success": True}, read_state=lambda eid: None)
    db.commit()
    assert outcome.state == "unknown"

    # 稍后媒体真的生效 —— reconcile 拿到匹配的状态
    outcome2 = dispatcher.reconcile(
        db, outcome.action, req, read_state=lambda eid: {"status": "PAUSED"})
    db.commit()
    assert outcome2.state == "verified"
    assert outcome.action.state == "verified"
    db.close()


def test_reconcile_unknown_to_failed_on_mismatch():
    db = _fresh_db()
    dispatcher = Dispatcher()
    req = _req(step_id="step-rec-fail")

    outcome = dispatcher.dispatch_and_verify(
        db, req, media_call=lambda: {"success": True}, read_state=lambda eid: None)
    db.commit()
    assert outcome.state == "unknown"

    # 对账再来一次仍与预期不同 → 判定为最终失败
    outcome2 = dispatcher.reconcile(
        db, outcome.action, req, read_state=lambda eid: {"status": "ACTIVE"})
    db.commit()
    assert outcome2.state == "failed"
    db.close()


def test_reconcile_still_none_stays_unknown():
    db = _fresh_db()
    dispatcher = Dispatcher()
    req = _req(step_id="step-rec-still-unknown")

    outcome = dispatcher.dispatch_and_verify(
        db, req, media_call=lambda: {"success": True}, read_state=lambda eid: None)
    db.commit()
    assert outcome.state == "unknown"

    outcome2 = dispatcher.reconcile(
        db, outcome.action, req, read_state=lambda eid: None)
    db.commit()
    assert outcome2.state == "unknown"
    db.close()


def test_reconcile_no_op_for_non_unknown_states():
    """已经 verified/failed 的动作 reconcile 不应再改状态。"""
    db = _fresh_db()
    dispatcher = Dispatcher()
    req = _req(step_id="step-noop")

    dispatcher.dispatch_and_verify(
        db, req, media_call=lambda: {"success": True},
        read_state=lambda eid: {"status": "PAUSED"})
    db.commit()

    action = req  # not used, just to keep names distinct
    stored = dispatcher._store.get_by_idempotency_key(
        db, f"{req.session_id}:{req.step_id}:{req.tool}:")  # partial; use next
    # 用状态从 store 反查更简单：拿到刚 verified 的 action
    verified = db.query(AgentActionDB).order_by(AgentActionDB.updated_at.desc()).first()
    assert verified.state == "verified"

    outcome = dispatcher.reconcile(
        db, verified, req, read_state=lambda eid: {"status": "ACTIVE"})
    # verified 不该再回退 —— reconcile 直接跳过
    assert outcome.state == "verified"
    assert verified.state == "verified"
    db.close()
