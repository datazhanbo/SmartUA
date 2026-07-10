"""Agent Loop API —— 多轮对话式投放智能体（Phase 1）。

端点：
- POST /agent/sessions                 建会话并跑循环（首个 L1/L2 动作会停在 awaiting_approval）
- GET  /agent/sessions                 列出本 app 的会话
- GET  /agent/sessions/{id}            查看会话状态（目标/步骤/待审批/上下文）
- POST /agent/sessions/{id}/approve    人在环审批（批准→续跑，驳回→重新规划）
- POST /agent/sessions/{id}/message    多轮追问 / 追加指令

执行平台：settings.agent_default_platform（Meta 被封期间为 mock 因果模拟引擎）。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.core.security import get_current_user
from app.models.sys import User
from app.config import settings
from app.services.agent_runtime import (
    AgentLoop, AgentContext, get_session_store, get_memory, get_strategy,
)
from app.services.agent_runtime.autonomy import (
    AutonomyEngine, get_autonomy_store, start_scheduler, stop_scheduler,
    update_alert_for_session,
)
from app.services.agent_runtime.reflection import Reflector

router = APIRouter(prefix="/agent", tags=["agent"])


# ----------------------------- Schemas ----------------------------- #
class StartRequest(BaseModel):
    text: str
    app_id: int


class ApproveRequest(BaseModel):
    step_id: str
    approved: bool
    reason: Optional[str] = None


class MessageRequest(BaseModel):
    text: str


# ----------------------------- 依赖 ----------------------------- #
def _make_ctx(db: Session, user: User, app_id: int) -> AgentContext:
    from app.services.connectors import ConnectorFactory
    connector = ConnectorFactory.get_connector(
        settings.agent_default_platform, db=db, app_id=app_id, credentials={})
    return AgentContext(db=db, user=user, app_id=app_id, session=None,
                        connector=connector, memory=get_memory(),
                        strategy=get_strategy())


# ----------------------------- 路由 ----------------------------- #
@router.post("/sessions")
def create_session(
    req: StartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建 Agent 会话并启动 ReAct 循环。"""
    store = get_session_store()
    session = store.create(app_id=req.app_id, user_id=current_user.id, goal=req.text)
    ctx = _make_ctx(db, current_user, req.app_id)
    ctx.session = session

    loop = AgentLoop()
    loop.start(session, ctx)
    return session


@router.get("/sessions")
def list_sessions(
    app_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出本 app 的 Agent 会话。"""
    store = get_session_store()
    return store.list(app_id)


@router.get("/sessions/{session_id}")
def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查看会话状态。"""
    store = get_session_store()
    session = store.get(session_id)
    if not session or session.app_id != session.app_id:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/sessions/{session_id}/approve")
def approve_step(
    session_id: str,
    req: ApproveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """人在环审批一个待确认动作；批准后 Agent 续跑，驳回后重新规划。"""
    store = get_session_store()
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    ctx = _make_ctx(db, current_user, session.app_id)
    ctx.session = session
    loop = AgentLoop()
    try:
        loop.approve(session, req.step_id, req.approved, req.reason, ctx)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # 若是主动自治生成的提案，回写关联告警状态（前端告警流随之更新）
    try:
        update_alert_for_session(
            session_id, req.approved,
            "已批准，Agent 续跑" if req.approved else f"已驳回（{req.reason or '用户拒绝'}）")
    except Exception:
        pass
    return session


@router.post("/sessions/{session_id}/message")
def send_message(
    session_id: str,
    req: MessageRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """向 Agent 追加指令 / 多轮追问。"""
    store = get_session_store()
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    ctx = _make_ctx(db, current_user, session.app_id)
    ctx.session = session
    loop = AgentLoop()
    loop.send_message(session, req.text, ctx)
    return session


# ----------------------------- Phase 2：反思端点 ----------------------------- #
@router.post("/reflect")
def reflect(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """全局复盘：基于已沉淀的 Episode 记忆，提取启发式规则（无需会话）。"""
    if not settings.agent_reflection_enabled:
        raise HTTPException(status_code=503, detail="反思功能未启用（agent_reflection_enabled=false）")
    result = Reflector().reflect(get_memory())
    return result.to_dict()


@router.post("/sessions/{session_id}/reflect")
def reflect_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按会话复盘：基于记忆（结合本会话目标）提取启发式规则。"""
    if not settings.agent_reflection_enabled:
        raise HTTPException(status_code=503, detail="反思功能未启用（agent_reflection_enabled=false）")
    store = get_session_store()
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    result = Reflector().reflect(get_memory(), goal=session.goal)
    return result.to_dict()


# ----------------------------- Phase 3：策略自演化端点 ----------------------------- #
@router.post("/strategy/learn")
def learn_strategy(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """策略自演化：把已沉淀的 Episode 记忆编译成可复用策略参数并落盘。"""
    if not settings.agent_reflection_enabled:
        raise HTTPException(status_code=503, detail="策略学习未启用（agent_reflection_enabled=false）")
    store = get_session_store()
    ctx = _make_ctx(db, current_user, 1)
    loop = AgentLoop()
    result = loop.learn_strategy(ctx)
    if result is None:
        raise HTTPException(status_code=503, detail="策略层未初始化")
    return result.to_dict()


@router.get("/strategy")
def get_strategy_endpoint(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查看当前学到的策略参数。"""
    s = get_strategy()
    return {
        "strategy_path": s.path,
        "rules": {k: v.to_dict() for k, v in s.all().items()},
    }


@router.post("/strategy/reset")
def reset_strategy(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """清空已学策略（重置为硬编码默认）。"""
    get_strategy().reset()
    return {"ok": True, "detail": "策略已重置为硬编码默认值"}


# ----------------------------- Phase 4：主动式自治端点 ----------------------------- #
@router.get("/autonomy/status")
def autonomy_status(
    current_user: User = Depends(get_current_user),
):
    """查看主动自治调度状态与最近扫描情况。"""
    store = get_autonomy_store()
    return {
        "enabled": store.enabled,
        "interval_seconds": store.interval_seconds,
        "last_scan_at": store.last_scan_at,
        "alerts_total": len(store.list_alerts()),
        "pending": store.pending_count(),
        "platform": settings.agent_default_platform,
        "monitor_app_ids": settings.agent_monitor_app_ids,
    }


@router.get("/autonomy/alerts")
def autonomy_alerts(
    app_id: int = 1,
    current_user: User = Depends(get_current_user),
):
    """列出本 app 的主动自治告警（含待审批提案，可一键批准）。"""
    alerts = get_autonomy_store().list_alerts(app_id)
    # 最新的在前
    return [a.to_dict() for a in reversed(alerts)]


@router.post("/autonomy/scan")
def autonomy_scan(
    app_id: int = 1,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """手动触发一次主动巡检（等价于调度器的一次执行，便于演示/测试）。"""
    alerts = AutonomyEngine().scan(app_id=app_id, db=db, user=current_user)
    return {
        "scanned": True,
        "alerts": [a.to_dict() for a in alerts],
        "summary": {
            "auto_executed": sum(1 for a in alerts if a.status == "auto_executed"),
            "pending_approval": sum(1 for a in alerts if a.status == "pending_approval"),
            "no_action": sum(1 for a in alerts if a.status == "no_action"),
        },
    }


@router.post("/autonomy/toggle")
def autonomy_toggle(
    enabled: bool = Query(..., description="是否开启主动巡检调度"),
    current_user: User = Depends(get_current_user),
):
    """启停主动自治调度（APScheduler）。关闭后不再周期巡检，但手动 /autonomy/scan 仍可用。"""
    store = get_autonomy_store()
    store.set_enabled(enabled)
    if enabled:
        start_scheduler()
    else:
        stop_scheduler()
    return {"enabled": store.enabled, "detail": "主动自治调度已" + ("开启" if enabled else "关闭")}
