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
from app.core.security import get_current_user, decode_token, require_app_access, user_can_access_app
from app.core.stream_ticket import get_stream_ticket_store
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


def _require_session_access(session, user: User, db: Session):
    """Phase 2.1：断言用户可访问该 session（其 app 在用户 UserAppBinding 里）。

    session 不存在 与 无权访问 都返回 404，避免通过响应差异枚举 session_id。
    调用方无需自行判空。
    """
    if session is None or not user_can_access_app(user, session.app_id, db):
        raise HTTPException(status_code=404, detail="Session not found")


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
    from app.services.connectors import ConnectorFactory, resolve_credentials
    connector = ConnectorFactory.get_connector(
        settings.agent_default_platform, db=db, app_id=app_id,
        credentials=resolve_credentials(settings.agent_default_platform, db=db, app_id=app_id),
        execution_mode=settings.agent_execution_mode)
    return AgentContext(db=db, user=user, app_id=app_id, session=None,
                        connector=connector, memory=get_memory(),
                        strategy=get_strategy())


def _resolve_session_provenance(db: Session, app_id: int) -> dict:
    """新建会话前解析真实执行目标：平台 / 执行模式 / 账户。

    Phase 1.2：会话一诞生即冻结 provenance，前端从 snapshot 起就能显示
    Mock/Sandbox/Live 标识，也能在审批卡上看到"这条动作作用在哪个账户"。
    绝不静默切换：若连接器构造失败（缺凭证 / SDK 未装），此函数不吞异常，
    让 create_session 拒绝创建。
    """
    from app.services.connectors import ConnectorFactory, resolve_credentials
    platform = settings.agent_default_platform
    execution_mode = settings.agent_execution_mode
    connector = ConnectorFactory.get_connector(
        platform, db=db, app_id=app_id,
        credentials=resolve_credentials(platform, db=db, app_id=app_id),
        execution_mode=execution_mode)
    return {
        "platform": connector.platform,
        "execution_mode": connector.execution_mode,
        "account_id": connector.account_id or "",
    }


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
            try:
                get_session_store().persist(session)
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
    """SSE 鉴权：Authorization Header（Bearer JWT）优先；`?token=` 长期 JWT 默认拒绝。

    Phase 2.2：长期 JWT 不再进入 URL / 代理日志 / 浏览器历史。前端使用一次性
    stream-ticket；本函数只处理 Authorization Header 或（旧版兼容时）query token。
    stream-ticket 由 stream_session 单独处理，因其携带 session 绑定信息。
    """
    raw = None
    if authorization:
        raw = authorization[7:] if authorization.startswith("Bearer ") else authorization
    if not raw and token and settings.agent_sse_allow_legacy_token:
        raw = token
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
    require_app_access(current_user, req.app_id, db)
    store = get_session_store()
    try:
        prov = _resolve_session_provenance(db, req.app_id)
    except (ValueError, RuntimeError) as e:
        # Phase 1.1 fail-closed 语义：live 缺凭证 / SDK 直接拒绝创建会话
        raise HTTPException(status_code=400, detail=f"无法初始化执行目标: {e}")
    session = store.create(
        app_id=req.app_id, user_id=current_user.id, goal=req.text,
        platform=prov["platform"], execution_mode=prov["execution_mode"],
        account_id=prov["account_id"],
    )
    _spawn_loop("start", session, current_user, req.app_id)
    return session


@router.get("/sessions")
def list_sessions(
    app_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出本 app 的 Agent 会话。"""
    require_app_access(current_user, app_id, db)
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
    _require_session_access(session, current_user, db)
    return session


@router.post("/sessions/{session_id}/stream-ticket")
def create_stream_ticket(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """签发一次性 SSE 票据：JWT 认证 + session 归属校验 → 短期、单次、绑定 (user, session)。

    Phase 2.2：把长期 JWT 从 URL / 代理日志 / 浏览器历史里彻底移出。前端拿到 ticket 后
    只在 `GET /agent/sessions/{id}/stream?ticket=...` 这一次订阅时使用；消费后立即失效。
    session 不存在 / 无权访问统一 404，避免通过响应差异枚举 session_id。
    """
    store = get_session_store()
    session = store.get(session_id)
    _require_session_access(session, current_user, db)
    ticket, ttl = get_stream_ticket_store().mint(current_user.id, session_id)
    return {"ticket": ticket, "ttl_seconds": ttl}


@router.get("/sessions/{session_id}/stream")
async def stream_session(
    session_id: str,
    ticket: Optional[str] = Query(None, description="Phase 2.2 一次性票据（推荐）"),
    token: Optional[str] = Query(None, description="旧版长期 JWT（默认拒绝，需开启 agent_sse_allow_legacy_token）"),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """SSE 流式推送会话步骤：连接即发 snapshot，之后每当 Agent Loop 产生新步骤/状态变化即推送。

    前端用 EventSource 订阅，实现"边跑边显示"的实时明细流（thought/observation/action/approval/final），
    避免整轮 Agent Loop（真调大模型需数分钟）跑完才一次性返回。

    认证优先级（Phase 2.2）：
    1) 一次性 ticket（推荐）：`?ticket=` — 短期、单次、绑定 (user, session)。
    2) Authorization Header（Bearer JWT）— 命令行/后端 client 调试用。
    3) 旧版 `?token=<长期 JWT>` — 默认拒绝；仅在 `agent_sse_allow_legacy_token=True`
       开启时可用，目的是让灰度期能滚回旧前端。
    """
    user: Optional[User] = None
    store = get_session_store()

    if ticket:
        # 票据消费失败（不存在 / 过期 / 已用 / session 错配）全部同一 401，避免枚举 session_id
        uid = get_stream_ticket_store().consume(ticket, session_id)
        if uid is None:
            raise HTTPException(status_code=401, detail="Invalid or expired stream ticket")
        user = db.query(User).filter(User.id == uid).first()
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired stream ticket")
    else:
        user = _authenticate(token, authorization, db)

    session = store.get(session_id)
    _require_session_access(session, user, db)

    async def event_gen():
        last = 0
        last_status = session.status
        # 跟踪每个 step 的文本长度 + 状态，用于检测"思考步骤内容增长"并重发
        step_sig: Dict[str, tuple] = {}
        provenance = {
            "platform": session.platform,
            "execution_mode": session.execution_mode,
            "account_id": session.account_id,
        }
        # 初始快照：让前端立即拿到已有步骤与状态
        yield _sse("snapshot", {
            "steps": [s.model_dump() for s in session.steps],
            "status": session.status,
            "provenance": provenance,
        })
        for st in session.steps:
            step_sig[st.id] = (len(st.text), st.status)
        yield _sse("status", {"status": session.status, "provenance": provenance})
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
            "Referrer-Policy": "no-referrer",  # Phase 2.2：即便 ticket 泄进 URL，也不通过 Referer 外发
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
    _require_session_access(session, current_user, db)

    # Phase 3.2 —— 审批过期 fail-fast（批准前即可判定；驳回不受此限制，仍允许说明原因）
    if req.approved:
        step = next((s for s in session.steps if s.id == req.step_id), None)
        if step is None or step.kind != AgentStepKind.APPROVAL.value:
            raise HTTPException(status_code=404, detail="Approval step not found")
        if step.status != AgentStepStatus.PROPOSED.value:
            raise HTTPException(status_code=409,
                                detail=f"Approval step no longer proposed (status={step.status})")
        if step.expires_at:
            from datetime import datetime as _dt, timezone as _tz
            try:
                exp = _dt.fromisoformat(step.expires_at.replace("Z", "+00:00"))
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=_tz.utc)
                if _dt.now(_tz.utc) > exp:
                    raise HTTPException(
                        status_code=409,
                        detail={"error": "approval_expired", "expires_at": step.expires_at,
                                "message": "提案已过期，请重新触发规划"})
            except HTTPException:
                raise
            except Exception:
                pass

        # Phase 3.2 —— 状态漂移 fail-fast：批准瞬间重读实体，超过阈值直接 409。
        # 前端凭 detail.drift 说明与 snapshot/current 对比，重新提案。
        if step.snapshot and step.params and step.params.get("entity_id"):
            try:
                from app.services.agent_runtime.loop import _detect_drift, _summary_of
                ctx = _make_ctx(db, current_user, session.app_id)
                current = _summary_of(ctx, step.params.get("entity_id"))
                drift = _detect_drift(step.snapshot, current,
                                       settings.agent_approval_drift_pct)
                if drift:
                    raise HTTPException(
                        status_code=409,
                        detail={"error": "state_drifted",
                                "drift": drift,
                                "snapshot": step.snapshot,
                                "current": current,
                                "message": "审批期间实体状态发生漂移，请重新触发规划"})
            except HTTPException:
                raise
            except Exception:
                # 漂移检测失败不应阻塞审批（例如 connector 暂时不可达）；
                # Loop 内部还会再校验一次，保底不放行漂移动作。
                pass

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
    _require_session_access(session, current_user, db)

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
    _require_session_access(session, current_user, db)
    session.abort_requested = True
    store.persist(session)
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
    _require_session_access(session, current_user, db)
    if session.status != "running":
        raise HTTPException(status_code=400, detail="仅运行中的会话可改向")
    session.abort_requested = True
    session.pending_redirect = req.text
    store.persist(session)
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
    _require_session_access(session, current_user, db)
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


# ----------------------------- Phase 3.3 / 4.2：对账 & 回采 ----------------------------- #
class ReconcileRequest(BaseModel):
    app_id: int
    max_actions: int = 200


@router.post("/actions/reconcile")
def reconcile_actions(
    req: ReconcileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Phase 3.3 —— 把 `unknown` 状态的动作再拉一次媒体状态回读，看能否收敛到 verified/failed。

    - 只处理 req.app_id 范围内、当前 state='unknown' 的动作。
    - 依赖 connector.read_state；对无 entity_id 或 read_state 不可用的动作直接跳过并计入 still_unknown。
    """
    require_app_access(current_user, req.app_id, db)
    from app.models.agent_runtime import AgentActionDB
    from app.services.agent_runtime.action_store import ActionRequest
    from app.services.agent_runtime.dispatcher import get_dispatcher
    from app.services.connectors import ConnectorFactory, resolve_credentials

    rows = (db.query(AgentActionDB)
              .filter(AgentActionDB.app_id == req.app_id,
                      AgentActionDB.state == "unknown")
              .order_by(AgentActionDB.dispatched_at.asc())
              .limit(max(1, min(int(req.max_actions or 200), 1000)))
              .all())

    dispatcher = get_dispatcher()
    connector_cache = {}
    stats = {"scanned": len(rows), "verified": 0, "failed": 0, "still_unknown": 0}

    for row in rows:
        platform = row.platform or settings.agent_default_platform
        if platform not in connector_cache:
            try:
                connector_cache[platform] = ConnectorFactory.get_connector(
                    platform, db=db, app_id=req.app_id,
                    credentials=resolve_credentials(platform, db=db, app_id=req.app_id),
                    execution_mode=row.execution_mode or settings.agent_execution_mode)
            except Exception:
                connector_cache[platform] = None
        connector = connector_cache.get(platform)
        read_state = getattr(connector, "read_state", None) if connector else None
        if read_state is None or not row.entity_id:
            stats["still_unknown"] += 1
            continue

        action_req = ActionRequest(
            session_id=row.session_id, step_id=row.step_id, app_id=row.app_id,
            user_id=row.user_id, tool=row.tool, action=row.action,
            entity_id=row.entity_id, platform=row.platform, account_id=row.account_id,
            execution_mode=row.execution_mode, risk_level=row.risk_level,
            request=row.request_json or {}, pre_state=row.pre_state_json,
            predicted_impact=row.predicted_impact_json)
        try:
            outcome = dispatcher.reconcile(db, row, action_req, read_state=read_state)
        except Exception:
            stats["still_unknown"] += 1
            continue

        if outcome.state == "verified":
            stats["verified"] += 1
        elif outcome.state == "failed":
            stats["failed"] += 1
        else:
            stats["still_unknown"] += 1
    try:
        db.commit()
    except Exception:
        db.rollback()
    return stats


class ImpactCollectRequest(BaseModel):
    app_id: int
    limit: int = 200


@router.post("/impact/collect")
def impact_collect(
    req: ImpactCollectRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Phase 4.2 —— 触发一次 `run_due_jobs`，把到点 impact job 从事实表回采。

    - 只回采 req.app_id 范围内的 job（通过 agent_jobs.app_id 过滤，见 collector 实现）。
    - 生产建议由外部调度器（APScheduler / cron）周期调用；本端点主要用于运维手动触发与验收。
    """
    require_app_access(current_user, req.app_id, db)
    from app.services.agent_runtime.impact_collector import run_due_jobs
    from datetime import datetime as _dt

    limit = max(1, min(int(req.limit or 200), 1000))
    stats = run_due_jobs(db, now=_dt.utcnow(), limit=limit, app_id=req.app_id)
    try:
        db.commit()
    except Exception:
        db.rollback()
    return {**stats, "scanned": stats["done"] + stats["empty"] + stats["failed"]}


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
        "execution_mode": settings.agent_execution_mode,
        "monitor_app_ids": settings.agent_monitor_app_ids,
    }


@router.get("/autonomy/alerts")
def autonomy_alerts(
    app_id: int = 1,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出本 app 的主动自治告警（含待审批提案，可一键批准）。"""
    require_app_access(current_user, app_id, db)
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
    require_app_access(current_user, app_id, db)
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
