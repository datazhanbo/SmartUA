"""P1 #3 —— AdSet/Ad 粒度 connector + 工具测试。

覆盖：
- 模拟引擎 seed 出 AdSet/Ad 层级，读写真实改状态
- connector.apply_action 路由 update_adset_status / update_adset_bid
- read_state 能回读 adset 状态（dispatcher verify 依赖）
- observe_adsets / evaluate_creative 读工具
- pause_adset 写工具走 _write 链路
- 不支持 adset 写的连接器 fail-closed（base.apply_action 返回 success=False）
"""
from __future__ import annotations

import pytest

from app.services.connectors.mock_media import MockMediaConnector, reset_sim_engine
from app.services.agent_runtime.tools import (
    AgentContext, ToolRegistry, get_tool_registry, TOOL_TO_ACTION,
)


class _Session:
    def __init__(self):
        self.id = "sess-test"
        self.goal = "test"
        self.context = {}


@pytest.fixture()
def connector():
    reset_sim_engine(seed=42)
    c = MockMediaConnector(db=None, app_id=1, credentials={"seed": 42}, execution_mode="mock")
    return c


def _ctx(connector):
    return AgentContext(db=None, user=None, app_id=1, session=_Session(),
                        connector=connector, memory=None, strategy=None)


# --------------------------------------------------------------------------- #
# 引擎 / connector 层
# --------------------------------------------------------------------------- #
def test_engine_seeds_adsets_and_ads(connector):
    adsets = connector.list_adsets()
    assert len(adsets) >= 4  # 4 campaigns × 2 adsets
    assert all("adset_id" in a and "bid" in a and "status" in a for a in adsets)
    creatives = connector.evaluate_creative()
    assert len(creatives) >= 8  # 4 campaigns × 2 adsets × 2 ads
    assert all(c["health"] in ("healthy", "fatigued", "underperforming") for c in creatives)


def test_apply_action_update_adset_status_pauses(connector):
    adset_id = connector.list_adsets()[0]["adset_id"]
    result = connector.apply_action("update_adset_status", adset_id, status="PAUSED")
    assert result["success"] is True
    assert connector.engine.adsets[adset_id].status == "PAUSED"


def test_apply_action_update_adset_bid_changes_bid(connector):
    adset_id = connector.list_adsets()[0]["adset_id"]
    result = connector.apply_action("update_adset_bid", adset_id, bid_amount=1.75)
    assert result["success"] is True
    assert connector.engine.adsets[adset_id].bid == pytest.approx(1.75)


def test_update_adset_bid_rejects_nonpositive(connector):
    adset_id = connector.list_adsets()[0]["adset_id"]
    result = connector.apply_action("update_adset_bid", adset_id, bid_amount=0)
    assert result["success"] is False
    assert "positive" in result["error"]


def test_update_adset_status_unknown_adset_fails(connector):
    result = connector.apply_action("update_adset_status", "does_not_exist", status="PAUSED")
    assert result["success"] is False
    assert "not found" in result["error"]


def test_read_state_resolves_adset(connector):
    adset_id = connector.list_adsets()[0]["adset_id"]
    state = connector.read_state(adset_id)
    assert state is not None
    assert state["entity_level"] == "adset"
    assert state["status"] == "ACTIVE"


def test_read_state_falls_back_to_campaign(connector):
    # campaign 实体仍能被回读（不回归）
    state = connector.read_state("camp_uk_001")
    assert state is not None
    assert "status" in state and state.get("entity_level") != "adset"


def test_unsupported_adset_write_fails_closed(connector):
    # rotate_creative 风格：基类对未实现方法返回 success=False，不抛 AttributeError
    # 用一个未实现 update_adset_status 的连接器基类实例验证 fail-closed 语义
    from app.services.connectors.base import BaseConnector

    class ReadOnlyConnector(BaseConnector):
        platform = "ro"
        supported_modes = ("mock",)
        capabilities = {"read": True, "write": True, "structure": False, "simulate": False}

        def auth(self):
            return True

        def pull(self, *a, **k):
            return {"raw_rows": [], "metadata": {}}

        def normalize(self, rows):
            return rows

        # 故意不实现 update_adset_status

    ro = ReadOnlyConnector(db=None, app_id=1, credentials={}, execution_mode="mock")
    result = ro.apply_action("update_adset_status", "x", status="PAUSED")
    assert result["success"] is False
    assert "不支持" in result["error"]


# --------------------------------------------------------------------------- #
# 工具层
# --------------------------------------------------------------------------- #
def test_registry_exposes_new_adset_tools():
    reg = get_tool_registry()
    for name in ("observe_adsets", "pause_adset", "evaluate_creative", "adjust_bid"):
        tool = reg.get(name)
        assert tool is not None, f"missing tool {name}"
    assert reg.get("observe_adsets").side_effect == "read"
    assert reg.get("evaluate_creative").side_effect == "read"
    assert reg.get("pause_adset").risk_level == "L1"
    assert reg.get("pause_adset").side_effect == "write"
    assert reg.get("adjust_bid").risk_level == "L2"


def test_tool_to_action_maps_pause_adset():
    assert "pause_adset" in TOOL_TO_ACTION
    action, fn = TOOL_TO_ACTION["pause_adset"]
    assert action == "update_adset_status"
    assert fn({"entity_id": "a"}) == {"status": "PAUSED"}


def test_observe_adsets_tool(connector):
    ctx = _ctx(connector)
    res = get_tool_registry().get("observe_adsets").handler({"campaign_id": "camp_uk_001"}, ctx)
    assert res.ok is True
    assert all(a["campaign_id"] == "camp_uk_001" for a in res.data["adsets"])
    assert len(res.data["adsets"]) == 2


def test_evaluate_creative_tool(connector):
    ctx = _ctx(connector)
    res = get_tool_registry().get("evaluate_creative").handler({}, ctx)
    assert res.ok is True
    assert res.data["creatives"]
    assert "health" in res.data["creatives"][0]


def test_pause_adset_tool_executes(connector):
    ctx = _ctx(connector)
    adset_id = connector.list_adsets()[0]["adset_id"]
    res = get_tool_registry().get("pause_adset").handler({"entity_id": adset_id}, ctx)
    assert res.ok is True
    assert connector.engine.adsets[adset_id].status == "PAUSED"


def test_adjust_bid_tool_executes_on_adset(connector):
    ctx = _ctx(connector)
    adset_id = connector.list_adsets()[0]["adset_id"]
    res = get_tool_registry().get("adjust_bid").handler(
        {"entity_id": adset_id, "bid_amount": 2.0}, ctx)
    assert res.ok is True
    assert connector.engine.adsets[adset_id].bid == pytest.approx(2.0)


# --------------------------------------------------------------------------- #
# 端到端：adset 暂停经 Dispatcher 走状态机到 verified
# --------------------------------------------------------------------------- #
def test_pause_adset_reaches_verified_via_dispatcher(connector):
    from app.db.base import SessionLocal
    from app.models.agent_runtime import AgentActionDB
    from app.services.agent_runtime.action_store import ActionRequest, AgentActionStore
    from app.services.agent_runtime.dispatcher import Dispatcher

    adset_id = connector.list_adsets()[0]["adset_id"]
    db = SessionLocal()
    try:
        db.query(AgentActionDB).delete()
        db.commit()
        req = ActionRequest(
            session_id="s-adset", step_id="step-1", app_id=1, user_id=42,
            tool="pause_adset", action="update_adset_status",
            entity_id=adset_id, platform="mock", account_id="acct_1",
            execution_mode="mock", risk_level="L1", request={"status": "PAUSED"},
        )
        outcome = Dispatcher(store=AgentActionStore()).dispatch_and_verify(
            db, req,
            media_call=lambda: connector.apply_action("update_adset_status", adset_id, status="PAUSED"),
            read_state=connector.read_state,
        )
        db.commit()
        assert outcome.state == "verified"
        assert connector.engine.adsets[adset_id].status == "PAUSED"
    finally:
        db.close()
