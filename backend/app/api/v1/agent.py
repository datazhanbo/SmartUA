"""Agent Loop API —— 多轮对话式投放智能体（Phase 1）。

端点：
- POST /agent/sessions                 建会话并跑循环（首个 L1/L2 动作会停在 awaiting_approval）
- GET  /agent/sessions                 列出本 app 的会话
- GET  /agent/sessions/{id}            查看会话状态（目标/步骤/待审批/上下文）
- POST /agent/sessions/{id}/approve    人在环审批（批准→续跑，驳回→重新规划）
- POST /agent/sessions/{id}/message    多轮追问 / 追加指令

执行平台：settings.agent_default_platform（Meta 被封期间为 mock 因果模拟引擎）。
"""
import asyncio
import json
import threading
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session

from app.db.base import get_db, SessionLocal
from app.core.security import get_current_user, decode_token
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
from app.services.agent_runtime.session import (
    AgentStep, AgentStepKind, AgentStepStatus,
)

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


# ----------------------------- 后台异步执行 Agent Loop ----------------------------- #
# Agent Loop 会同步调用大模型（方舟推理模型单次决策需数十秒），若放在 HTTP 请求内同步跑，
# 会远超前端 axios 10s / Vite 代理 120s 超时。改为后台线程执行、立即返回会话，
# 前端轮询 GET /agent/sessions/{id} 获取实时步骤。
def _spawn_loop(method: str, session, user, app_id: int, **kw):
    def _task():
        bg_db = SessionLocal()
        try:
            ctx = _make_ctx(bg_db, user, app_id)
            ctx.session = session
            loop = AgentLoop()
            if method == "start":
                loop.start(session, ctx)
            elif method == "approve":
                loop.approve(session, kw["step_id"], kw["approved"],
                             kw.get("reason"), ctx)
            elif method == "message":
                loop.send_message(session, kw["text"], ctx)
            # —— 中途改向续跑：用户在 Agent 运行中发新指令，旧循环退出后按新方向重跑 ——
            while True:
                redirect = getattr(session, "pending_redirect", None)
                if not redirect:
                    break
                session.pending_redirect = None
                loop.redirect_run(session, ctx, redirect)
        except Exception as e:  # 异常落到会话上，前端轮询可见
            session.status = "failed"
            try:
                session.add_step(AgentStep(
                    kind=AgentStepKind.FINAL.value,
                    text=f"Agent 执行异常：{e}",
                    status=AgentStepStatus.FAILED.value))
            except Exception:
                pass
        finally:
            bg_db.close()
    threading.Thread(target=_task, daemon=True).start()


# ----------------------------- SSE 流式辅助 ----------------------------- #
def _sse(event: str, data: dict) -> str:
    """序列化为一条 SSE 消息。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _authenticate(token: Optional[str], authorization: Optional[str], db: Session) -> User:
    """SSE 鉴权：token 可来自 query（EventSource 无法自定义 Header）或 Authorization Header。"""
    raw = token
    if not raw and authorization:
        raw = authorization[7:] if authorization.startswith("Bearer ") else authorization
    if not raw:
        raise HTTPException(status_code=401, detail="未提供认证凭据")
    payload = decode_token(raw)
    if not payload or not payload.get("sub"):
        raise HTTPException(status_code=401, detail="认证无效或已过期")
    user = db.query(User).filter(User.email == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user


# ----------------------------- 路由 ----------------------------- #
@router.post("/sessions")
def create_session(
    req: StartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建 Agent 会话并异步启动 ReAct 循环（立即返回，进度由前端轮询）。"""
    store = get_session_store()
    session = store.create(app_id=req.app_id, user_id=current_user.id, goal=req.text)
    _spawn_loop("start", session, current_user, req.app_id)
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


@router.get("/sessions/{session_id}/stream")
async def stream_session(
    session_id: str,
    token: Optional[str] = Query(None, description="SSE 鉴权 token（EventSource 无法自定义 Header，故走 query）"),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """SSE 流式推送会话步骤：连接即发 snapshot，之后每当 Agent Loop 产生新步骤/状态变化即推送。

    前端用 EventSource 订阅，实现"边跑边显示"的实时明细流（thought/observation/action/approval/final），
    避免整轮 Agent Loop（真调大模型需数分钟）跑完才一次性返回。
    """
    _authenticate(token, authorization, db)
    store = get_session_store()
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    async def event_gen():
        last = 0
        last_status = session.status
        # 跟踪每个 step 的文本长度 + 状态，用于检测"思考步骤内容增长"并重发
        step_sig: Dict[str, tuple] = {}
        # 初始快照：让前端立即拿到已有步骤与状态
        yield _sse("snapshot", {
            "steps": [s.model_dump() for s in session.steps],
            "status": session.status,
        })
        for st in session.steps:
            step_sig[st.id] = (len(st.text), st.status)
        yield _sse("status", {"status": session.status})
        heartbeat = 0
        max_iter = int(30 * 60 / 0.3)  # 安全上限：约 30 分钟，防连接泄漏
        while heartbeat < max_iter:
            s = store.get(session_id)
            if s is None:
                break
            steps = s.steps
            # 1) 新增步骤：逐条推送
            if len(steps) > last:
                for st in steps[last:]:
                    yield _sse("step", st.model_dump())
                    step_sig[st.id] = (len(st.text), st.status)
                last = len(steps)
            # 2) 已有步骤内容/状态变化（如思考步骤流式增长）：重发该 step
            for st in steps:
                sig = (len(st.text), st.status)
                if step_sig.get(st.id) != sig:
                    step_sig[st.id] = sig
                    yield _sse("step", st.model_dump())
            if s.status != last_status:
                last_status = s.status
                yield _sse("status", {"status": s.status})
            if s.status in ("done", "failed"):
                yield _sse("end", {"status": s.status})
                break
            heartbeat += 1
            if heartbeat % 10 == 0:
                yield ": keepalive\n\n"
            await asyncio.sleep(0.3)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 关闭下游代理缓冲（如 nginx）
        },
    )


@router.post("/sessions/{session_id}/approve")
def approve_step(
    session_id: str,
    req: ApproveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """人在环审批一个待确认动作；批准后 Agent 异步续跑，驳回后重新规划（立即返回）。"""
    store = get_session_store()
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 若是主动自治生成的提案，回写关联告警状态（前端告警流随之更新）
    try:
        update_alert_for_session(
            session_id, req.approved,
            "已批准，Agent 续跑" if req.approved else f"已驳回（{req.reason or '用户拒绝'}）")
    except Exception:
        pass

    session.status = "running"  # 立即返回 running，驱动前端轮询续跑进度
    _spawn_loop("approve", session, current_user, session.app_id,
                step_id=req.step_id, approved=req.approved, reason=req.reason)
    return session


@router.post("/sessions/{session_id}/message")
def send_message(
    session_id: str,
    req: MessageRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """向 Agent 追加指令 / 多轮追问（异步执行，立即返回）。"""
    store = get_session_store()
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.status = "running"  # 立即返回 running，驱动前端轮询
    _spawn_loop("message", session, current_user, session.app_id, text=req.text)
    return session


@router.post("/sessions/{session_id}/abort")
def abort_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """中断当前运行中的 Loop（优雅停机，保留已完成步骤）。"""
    store = get_session_store()
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.abort_requested = True
    return {"ok": True, "status": session.status}


@router.post("/sessions/{session_id}/redirect")
def redirect_session(
    session_id: str,
    req: MessageRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """中途改向：中断当前运行中的 Loop，并按新指令重启一轮 ReAct（立即返回）。

    仅置 abort + pending_redirect 标志；正在跑的 Loop 退出后，
    由 _spawn_loop 的续跑循环接管并按新方向续跑（SSE 同会话 id 无缝续推）。
    """
    store = get_session_store()
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "running":
        raise HTTPException(status_code=400, detail="仅运行中的会话可改向")
    session.abort_requested = True
    session.pending_redirect = req.text
    return {"ok": True, "status": session.status, "pending_redirect": req.text}


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
