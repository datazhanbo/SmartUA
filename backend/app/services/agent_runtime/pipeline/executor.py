"""执行层：把 ToolCall 转成 AgentActionDB 状态机或直接调 tool.handler。

逻辑从 loop.py::_dispatch_via_action_store / _execute_approved_write / _execute_l0_write
迁出。事务归属保持原样：dispatcher 不 commit，本模块在 dispatch 成功后 ctx.db.commit()。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.services.agent_runtime.pipeline.approval import _propose_text  # noqa: F401 (re-export)
from app.services.agent_runtime.pipeline.base import ToolCall, ToolCallResult
from app.services.agent_runtime.session import AgentStep, AgentStepKind, AgentStepStatus

logger = logging.getLogger(__name__)


def execute_tool_call(call: ToolCall, session) -> AgentStep:
    """执行一次 ToolCall 并返回 AgentStep。

    - read 或无 DB：直调 tool.handler，落 OBSERVATION / EXECUTED
    - write L0：走 dispatcher 状态机
    - write L1/L2/L3 + approved：走 dispatcher 状态机
    """
    if call.side_effect == "read":
        res = call.tool.handler(call.params, call.ctx)
        return AgentStep(
            kind=AgentStepKind.OBSERVATION.value,
            text=res.observation, tool=call.name, result=res.data,
            status=AgentStepStatus.DONE.value)

    outcome = dispatch_via_action_store(call, session)
    return AgentStep(
        kind=AgentStepKind.ACTION.value,
        text=outcome["text"], tool=call.name, params=call.params,
        risk_level=call.risk_level,
        status=outcome["status"], result=outcome["data"])


def dispatch_via_action_store(call: ToolCall, session) -> Dict[str, Any]:
    """把写动作交给 Dispatcher 走状态机。

    无 DB（demo）或缺失 action mapping 时回退直接 tool.handler，
    便于不依赖数据库的脚本仍然可跑。
    """
    from app.services.agent_runtime.action_store import ActionRequest
    from app.services.agent_runtime.dispatcher import get_dispatcher
    from app.services.agent_runtime.tools import TOOL_TO_ACTION

    ctx = call.ctx
    tool = call.tool
    params = call.params

    # 无 DB 或工具不在动作映射：兜底直接执行（demo 场景）
    if ctx.db is None or tool.name not in TOOL_TO_ACTION:
        res = tool.handler(params, ctx)
        return {"text": res.observation,
                "data": res.data,
                "status": AgentStepStatus.EXECUTED.value}

    action_name, build_ap = TOOL_TO_ACTION[tool.name]
    action_params = build_ap(params)
    req = ActionRequest(
        session_id=str(session.id),
        step_id=str(call.step_id or "auto"),
        app_id=ctx.app_id,
        user_id=getattr(ctx.user, "id", None) if ctx.user else None,
        tool=tool.name,
        action=action_name,
        entity_id=params.get("entity_id"),
        platform=getattr(ctx.connector, "platform", None),
        account_id=getattr(ctx.connector, "account_id", None) or None,
        execution_mode=getattr(ctx.connector, "execution_mode", None),
        risk_level=call.risk_level,
        request={**action_params, "entity_id": params.get("entity_id")},
        pre_state=call.snapshot,
        predicted_impact=call.predicted_impact,
    )

    captured: Dict[str, Any] = {}

    def media_call():
        res = tool.handler(params, ctx)
        captured["result"] = res
        data = res.data or {}
        provider = data.get("result") if isinstance(data.get("result"), dict) else data
        return {"success": bool(res.ok),
                "provider": provider,
                "observation": res.observation}

    read_state = getattr(ctx.connector, "read_state", None)
    try:
        outcome = get_dispatcher().dispatch_and_verify(
            ctx.db, req, media_call=media_call, read_state=read_state)
        _link_episode_to_action(ctx, session_id=str(session.id),
                                tool_name=tool.name,
                                action_id=outcome.action.id)
        try:
            ctx.db.commit()
        except Exception as e:
            logger.warning("commit after dispatch failed: %s", e)
            try:
                ctx.db.rollback()
            except Exception:
                pass
    except Exception as e:
        logger.exception("dispatch_via_action_store raised, falling back to direct handler")
        res = tool.handler(params, ctx)
        return {"text": f"{res.observation}（dispatcher 异常回退：{e}）",
                "data": res.data,
                "status": AgentStepStatus.EXECUTED.value}

    state_status = {
        "verified": AgentStepStatus.EXECUTED.value,
        "failed": AgentStepStatus.EXECUTED.value,
        "unknown": AgentStepStatus.EXECUTED.value,
    }.get(outcome.state, AgentStepStatus.EXECUTED.value)

    res = captured.get("result")
    if res is not None:
        observation = f"{res.observation}｜派发状态：{outcome.state}（{outcome.observation}）"
        data = {**(res.data or {}), "dispatch": {
            "state": outcome.state,
            "action_id": outcome.action.id,
            "observation": outcome.observation,
        }}
    else:
        observation = f"派发状态：{outcome.state}（{outcome.observation}）"
        data = {"dispatch": {
            "state": outcome.state,
            "action_id": outcome.action.id,
            "observation": outcome.observation,
        }}
    return {"text": observation, "data": data, "status": state_status}


def _link_episode_to_action(ctx, *, session_id: str,
                             tool_name: str, action_id: str) -> None:
    """把最近记录的同 tool、同 session 的 Episode 补上 action_id。"""
    if ctx.memory is None or ctx.db is None or not action_id:
        return
    try:
        from app.db.base import SessionLocal
        from app.models.agent_runtime import EpisodeDB
        s = SessionLocal()
        try:
            row = (s.query(EpisodeDB)
                    .filter(EpisodeDB.session_id == session_id,
                            EpisodeDB.action == tool_name,
                            EpisodeDB.action_id.is_(None))
                    .order_by(EpisodeDB.timestamp.desc())
                    .first())
            if row is not None:
                row.action_id = action_id
                evidence = list(row.evidence_action_ids_json or [])
                if action_id not in evidence:
                    evidence.append(action_id)
                row.evidence_action_ids_json = evidence
                s.commit()
        finally:
            s.close()
        try:
            ctx.memory._loaded = False  # type: ignore[attr-defined]
        except Exception:
            pass
    except Exception as e:
        logger.warning("link_episode_to_action failed: %s", e)
