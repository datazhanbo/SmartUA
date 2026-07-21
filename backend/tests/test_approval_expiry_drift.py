"""Phase 3.2 —— 审批过期 + 状态漂移的单元测试。

覆盖：
- 提案时 `expires_at` / `snapshot` 冻结到 APPROVAL 步骤，跨 store 重启仍可读回。
- 审批已过期：Loop.approve 走"过期"分支，跳过执行、加观察、重进 running。
- 状态漂移超阈值：Loop.approve 走"漂移"分支，跳过执行、附上 snapshot vs current。
- 状态未漂移且未过期：Loop.approve 正常执行工具。
- Loop._detect_drift 数字 / status / 缺失快照 的边界行为。

用 FakeConnector 而非 MockMediaConnector 直接驱动，方便在测试里精确制造漂移场景。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

import app.services.agent_runtime.session as _session_mod
from app.config import settings
from app.services.agent_runtime.loop import AgentLoop, _detect_drift, _summary_of
from app.services.agent_runtime.session import (
    AgentSession, AgentStep, AgentStepKind, AgentStepStatus, get_session_store,
)
from app.services.agent_runtime.tools import AgentContext


class FakeConnector:
    """最小 stub：只暴露 loop / tools 用到的表面。current_summary 内容外部可控。"""

    platform = "mock"
    execution_mode = "mock"
    account_id = "fake"

    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = rows
        self.actions: List[Dict[str, Any]] = []

    def current_summary(self):
        return self._rows

    def simulate_impact(self, action, entity_id, params, horizon=7):
        from app.services.connectors.base import ImpactEstimation
        z = [0.0] * horizon
        return ImpactEstimation(delta_roi=list(z), delta_spend=list(z), delta_cpi=list(z))

    # 供 pause_campaign / adjust_budget 工具兜底调用（若走到）
    def update_campaign_status(self, campaign_id: str, status: str):
        self.actions.append({"action": "update_campaign_status",
                             "entity_id": campaign_id, "status": status})
        return {"success": True, "campaign_id": campaign_id, "status": status}

    def update_campaign_budget(self, campaign_id: str, daily_budget: float):
        self.actions.append({"action": "update_campaign_budget",
                             "entity_id": campaign_id, "daily_budget": daily_budget})
        return {"success": True, "campaign_id": campaign_id, "daily_budget": daily_budget}

    def apply_action(self, action: str, entity_id: str, **params):
        self.actions.append({"action": action, "entity_id": entity_id, **params})
        return {"success": True, "action": action, "entity_id": entity_id, **params}


@pytest.fixture
def loop_setup():
    row = {"campaign_id": "camp_1", "country": "US", "status": "ACTIVE",
           "roi": 0.5, "spend": 500.0, "daily_budget": 100.0, "cpi": 2.0}
    conn = FakeConnector([row])
    session = AgentSession(app_id=1, user_id=42, goal="暂停低ROI活动")
    ctx = AgentContext(db=None, user=None, app_id=1, session=session,
                       connector=conn, memory=None, strategy=None)
    loop = AgentLoop()
    return loop, session, ctx, conn, row


def _propose_pause(loop: AgentLoop, session: AgentSession, ctx: AgentContext,
                   entity_id: str) -> AgentStep:
    """直接调用 _dispatch 走"提议 pause_campaign"路径，避开 LLM。"""
    from app.services.agent_runtime.loop import Decision
    decision = Decision(action="pause_campaign",
                        params={"entity_id": entity_id},
                        thought="test propose")
    loop._dispatch(session, ctx, decision)
    approval = next(s for s in session.steps if s.kind == AgentStepKind.APPROVAL.value)
    return approval


# ------------------------ 提案冻结 ------------------------

def test_dispatch_freezes_snapshot_and_expires_at(loop_setup):
    loop, session, ctx, conn, row = loop_setup
    approval = _propose_pause(loop, session, ctx, "camp_1")
    assert approval.status == AgentStepStatus.PROPOSED.value
    # snapshot 冻结当前 roi/spend/status/daily_budget
    assert approval.snapshot == {"roi": 0.5, "spend": 500.0,
                                  "status": "ACTIVE", "daily_budget": 100.0}
    # expires_at 是 ISO 字符串，且大约在 ttl 秒之后
    exp = datetime.fromisoformat(approval.expires_at.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    delta = (exp - now).total_seconds()
    assert settings.agent_approval_ttl_seconds - 5 <= delta <= settings.agent_approval_ttl_seconds + 5


def test_snapshot_survives_persist_reload(loop_setup):
    loop, session, ctx, conn, row = loop_setup
    approval = _propose_pause(loop, session, ctx, "camp_1")
    store = get_session_store()
    # Session 是 loop 内 add_step 得到的，需要手动持久化（未走 _done 时）
    session.id  # ensure id materialized
    store._cache[session.id] = session
    store.persist(session)
    step_id = approval.id

    _session_mod._session_store = None  # 抹掉进程内单例，强制走 DB 重建
    reloaded = get_session_store().get(session.id)
    assert reloaded is not None
    reloaded_step = next(s for s in reloaded.steps if s.id == step_id)
    assert reloaded_step.snapshot == approval.snapshot
    assert reloaded_step.expires_at is not None


# ------------------------ 过期路径 ------------------------

def test_expired_approval_skips_execution(loop_setup):
    loop, session, ctx, conn, row = loop_setup
    approval = _propose_pause(loop, session, ctx, "camp_1")
    # 手动把 expires_at 挪到过去
    approval.expires_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()

    loop.approve(session, approval.id, approved=True, reason=None, ctx=ctx)

    # 原审批步骤应被标记为 rejected + 含"过期"文案
    assert approval.status == AgentStepStatus.REJECTED.value
    assert "过期" in approval.text
    # 未调用媒体 API
    assert conn.actions == []
    # rejected 记录进 session.context，规则引擎不会再挑同一动作
    assert ("pause_campaign", "camp_1") in session.context.get("rejected", [])


# ------------------------ 漂移路径 ------------------------

def test_drift_above_threshold_blocks_execution(loop_setup):
    loop, session, ctx, conn, row = loop_setup
    approval = _propose_pause(loop, session, ctx, "camp_1")
    # 让漂移刚好越阈值：默认 20%，把 roi 从 0.5 抬到 0.75（+50%）
    row["roi"] = 0.75

    loop.approve(session, approval.id, approved=True, reason=None, ctx=ctx)
    assert approval.status == AgentStepStatus.REJECTED.value
    assert "漂移" in approval.text
    assert conn.actions == []
    # 观察步骤附带 snapshot vs current，便于前端 / 审计对账
    obs = [s for s in session.steps if s.kind == AgentStepKind.OBSERVATION.value
           and "漂移" in s.text]
    assert obs, "应插入一条漂移观察步骤"
    result = obs[-1].result or {}
    assert result.get("snapshot", {}).get("roi") == 0.5
    assert result.get("current", {}).get("roi") == 0.75


def test_status_flip_counts_as_drift(loop_setup):
    loop, session, ctx, conn, row = loop_setup
    approval = _propose_pause(loop, session, ctx, "camp_1")
    row["status"] = "PAUSED"  # 已经被别人暂停了 —— 再执行 pause 是无意义甚至危险

    loop.approve(session, approval.id, approved=True, reason=None, ctx=ctx)
    assert approval.status == AgentStepStatus.REJECTED.value
    assert "status" in approval.text
    assert conn.actions == []


def test_no_drift_no_expiry_executes_normally(loop_setup):
    loop, session, ctx, conn, row = loop_setup
    approval = _propose_pause(loop, session, ctx, "camp_1")
    # 让漂移在阈值内：+10% < 20%
    row["roi"] = 0.55

    loop.approve(session, approval.id, approved=True, reason=None, ctx=ctx)
    assert approval.status == AgentStepStatus.APPROVED.value
    # 工具被调用一次（pause_campaign → update_campaign_status via apply_action）
    assert any(a["action"] == "update_campaign_status" for a in conn.actions)


# ------------------------ _detect_drift 单元 ------------------------

def test_detect_drift_missing_snapshot_is_no_drift():
    assert _detect_drift(None, {"roi": 1.0}, 0.2) is None
    assert _detect_drift({"roi": 1.0}, None, 0.2) is None


def test_detect_drift_zero_baseline():
    # snapshot roi=0，current 变为非零 → 漂移
    assert _detect_drift({"roi": 0.0}, {"roi": 0.1}, 0.2) is not None
    # 两者都是 0 → 不漂移
    assert _detect_drift({"roi": 0.0}, {"roi": 0.0}, 0.2) is None


def test_detect_drift_below_threshold_is_no_drift():
    # +15% < 20% 阈值
    assert _detect_drift({"roi": 1.0, "status": "ACTIVE"},
                         {"roi": 1.15, "status": "ACTIVE"}, 0.2) is None


def test_summary_of_missing_entity_returns_none():
    conn = FakeConnector([{"campaign_id": "camp_1", "roi": 1.0, "spend": 100,
                           "status": "ACTIVE", "daily_budget": 50, "country": "US", "cpi": 1}])
    class _C: pass
    ctx = _C()
    ctx.connector = conn
    assert _summary_of(ctx, "camp_missing") is None
    got = _summary_of(ctx, "camp_1")
    assert got == {"roi": 1.0, "spend": 100, "status": "ACTIVE", "daily_budget": 50}
