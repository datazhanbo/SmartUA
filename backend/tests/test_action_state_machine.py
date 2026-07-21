"""Phase 3.1 — 动作实体 / 状态机 / 幂等键的单元测试。

覆盖：
- 相同 (session, step, tool, params) 幂等键复用同一动作；不同参数生成不同动作。
- 合法路径 proposed → approved → dispatching → accepted → verified。
- 非法跳转（跳阶段 / 终态回滚）拒绝。
- 终态之后再迁移一律拒绝，即便同一 to_state 也不行。

不覆盖：
- 与 _write() / dispatcher 的联动 —— 那是 Phase 3.3 的事，本轮只建立实体。
"""
from __future__ import annotations

import pytest

from app.db.base import SessionLocal
from app.models.agent_runtime import AgentActionDB
from app.services.agent_runtime.action_store import (
    ActionRequest,
    AgentActionStore,
    InvalidTransition,
    build_idempotency_key,
    get_action_store,
)


def _fresh_db():
    return SessionLocal()


def _req(**overrides):
    base = dict(
        session_id="s-phase31",
        step_id="step-1",
        app_id=1,
        user_id=42,
        tool="pause_campaign",
        action="update_campaign_status",
        entity_id="camp_001",
        platform="mock",
        account_id="acct_1",
        execution_mode="mock",
        risk_level="L1",
        request={"status": "PAUSED"},
        pre_state={"roi": 0.4, "spend": 500.0, "status": "ACTIVE"},
        predicted_impact={"impact_24h": {"delta_roi": 0.1}},
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


def test_idempotency_key_stable_across_key_order():
    """dict 键顺序不同不影响幂等键 —— 摘要用 sort_keys。"""
    k1 = build_idempotency_key("s", "st", "adjust_budget", {"daily_budget": 100, "_pct": 20})
    k2 = build_idempotency_key("s", "st", "adjust_budget", {"_pct": 20, "daily_budget": 100})
    assert k1 == k2


def test_mint_or_get_reuses_existing_action():
    store = AgentActionStore()
    db = _fresh_db()
    try:
        a = store.mint_or_get(db, _req())
        db.commit()
        b = store.mint_or_get(db, _req())
        db.commit()
        assert a.id == b.id
        assert db.query(AgentActionDB).count() == 1
    finally:
        db.close()


def test_different_params_generate_different_actions():
    store = AgentActionStore()
    db = _fresh_db()
    try:
        a = store.mint_or_get(db, _req(request={"status": "PAUSED"}))
        b = store.mint_or_get(db, _req(request={"status": "ACTIVE"}))
        db.commit()
        assert a.id != b.id
        assert db.query(AgentActionDB).count() == 2
    finally:
        db.close()


def test_singleton_action_store_reused():
    """默认单例复用 —— Loop / dispatcher 应看到同一份 store 语义。"""
    assert get_action_store() is get_action_store()


def test_happy_path_transitions_populate_timestamps():
    store = AgentActionStore()
    db = _fresh_db()
    try:
        a = store.mint_or_get(db, _req())
        assert a.state == "proposed"

        store.transition(db, a, "approved")
        assert a.state == "approved" and a.approved_at is not None

        store.transition(db, a, "dispatching")
        assert a.state == "dispatching" and a.dispatched_at is not None

        store.transition(db, a, "accepted", provider_request_id="req-xyz",
                         provider_response={"ok": True})
        assert a.state == "accepted" and a.accepted_at is not None
        assert a.provider_request_id == "req-xyz"
        assert a.provider_response_json == {"ok": True}

        store.transition(db, a, "verified")
        assert a.state == "verified" and a.verified_at is not None
        db.commit()
    finally:
        db.close()


def test_illegal_skip_rejected():
    """proposed 不能直接跳到 dispatching（必须先 approved）。"""
    store = AgentActionStore()
    db = _fresh_db()
    try:
        a = store.mint_or_get(db, _req())
        with pytest.raises(InvalidTransition):
            store.transition(db, a, "dispatching")
        assert a.state == "proposed"
    finally:
        db.close()


def test_terminal_state_cannot_transition():
    """verified / failed 是终态：任何后续跳转都要被拒绝。"""
    store = AgentActionStore()
    db = _fresh_db()
    try:
        a = store.mint_or_get(db, _req())
        store.transition(db, a, "approved")
        store.transition(db, a, "dispatching")
        store.transition(db, a, "accepted")
        store.transition(db, a, "verified")
        with pytest.raises(InvalidTransition):
            store.transition(db, a, "failed")
        with pytest.raises(InvalidTransition):
            store.transition(db, a, "approved")
    finally:
        db.close()


def test_unknown_can_converge_to_verified_or_failed():
    """dispatching 期间媒体超时 → unknown；对账后可收敛为 verified/failed。"""
    store = AgentActionStore()
    db = _fresh_db()
    try:
        a = store.mint_or_get(db, _req(step_id="step-unknown"))
        store.transition(db, a, "approved")
        store.transition(db, a, "dispatching")
        store.transition(db, a, "unknown", error="timeout waiting for response")
        assert a.error == "timeout waiting for response"
        store.transition(db, a, "verified")
        assert a.state == "verified"
    finally:
        db.close()


def test_failure_from_proposed_and_from_dispatching():
    store = AgentActionStore()
    db = _fresh_db()
    try:
        # proposed → failed（例如审批前发现参数不合法）
        a = store.mint_or_get(db, _req(step_id="step-A"))
        store.transition(db, a, "failed", error="param out of range")
        assert a.state == "failed" and a.error == "param out of range"

        # dispatching → failed（媒体明确拒绝）
        b = store.mint_or_get(db, _req(step_id="step-B"))
        store.transition(db, b, "approved")
        store.transition(db, b, "dispatching")
        store.transition(db, b, "failed", error="account suspended")
        assert b.state == "failed"
    finally:
        db.close()


def test_get_and_get_by_idempotency_key_return_same_row():
    store = AgentActionStore()
    db = _fresh_db()
    try:
        a = store.mint_or_get(db, _req(step_id="step-lookup"))
        db.commit()
        by_id = store.get(db, a.id)
        by_key = store.get_by_idempotency_key(db, a.idempotency_key)
        assert by_id is not None and by_key is not None
        assert by_id.id == by_key.id == a.id
    finally:
        db.close()
