"""Agent Loop 会话状态（多轮对话 / 计划 / 审批）。

设计要点：
- 与"平台做身体+护栏，Agent Loop 做大脑"一致：会话只持有"目标、步骤、待审批项、上下文"，
  真实执行仍走 Connector / 意图引擎（审计、安全分级天然生效）。
- Phase A1 起：会话仓库为「进程内缓存（快路径）+ SQLite 持久化（重启不丢）」双轨。
  - 内存 dict 持有活跃会话对象，loop 对其原地修改立即可见（SSE 实时推流依赖此）。
  - 每次 create / persist 把会话 + 步骤落库；get 优先命中缓存，未命中则从 DB 重建。
  - 满足 Phase A1 目标：进程重启后，新建会话 / 步骤 / 状态可从 DB 完整读回。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Any, List, Optional

from pydantic import BaseModel, Field

from app.db.base import SessionLocal
from app.models.agent_runtime import AgentSessionDB, AgentStepDB


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentStepKind(str, Enum):
    REASONING = "reasoning"    # 大模型思考过程（推理模型的 reasoning_content，逐 token 流式）
    THOUGHT = "thought"        # 推理结论（模型在 JSON 中给出的 thought 摘要）
    ACTION = "action"          # 已执行的写动作
    OBSERVATION = "observation"  # 读/观察结果
    APPROVAL = "approval"      # 待人确认的高风险动作
    FINAL = "final"            # 最终结论


class AgentStepStatus(str, Enum):
    PROPOSED = "proposed"      # 等待人确认
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"
    THINKING = "thinking"      # 大模型正在流式思考中（reasoning 步骤）
    DONE = "done"              # 观察/结论已落定


class AgentStep(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    kind: str
    text: str
    tool: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    risk_level: Optional[str] = None
    predicted_impact: Optional[Dict[str, Any]] = None
    status: str = "done"
    result: Optional[Dict[str, Any]] = None
    created_at: str = Field(default_factory=_now)
    # Phase 3.2 审批过期 / 漂移校验（仅审批类步骤使用；ISO 字符串）
    expires_at: Optional[str] = None
    snapshot: Optional[Dict[str, Any]] = None

    def short(self) -> str:
        tag = {
            AgentStepKind.REASONING.value: "🧠",
            AgentStepKind.THOUGHT.value: "💭",
            AgentStepKind.OBSERVATION.value: "👁",
            AgentStepKind.ACTION.value: "✅",
            AgentStepKind.APPROVAL.value: "⏳",
            AgentStepKind.FINAL.value: "🏁",
        }.get(self.kind, "•")
        meta = ""
        if self.risk_level:
            meta = f" [{self.risk_level}]"
        return f"{tag} {self.text}{meta}"


class AgentSession(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    app_id: int
    user_id: int
    goal: str
    status: str = "running"   # running / awaiting_approval / done / failed
    steps: List[AgentStep] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict)  # 累计观察（如最近一次 summary）
    # Phase 1.2：执行 provenance（session-level），前端始终可展示 Mock/Sandbox/Live 标识
    platform: Optional[str] = None
    execution_mode: Optional[str] = None
    account_id: Optional[str] = None
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    abort_requested: bool = False            # 用户请求中断当前循环
    pending_redirect: Optional[str] = None    # 用户中途改向：中断后按此新指令续跑

    def add_step(self, step: AgentStep) -> AgentStep:
        self.steps.append(step)
        self.updated_at = _now()
        return step

    def touch(self):
        self.updated_at = _now()

    def pending_approval(self) -> Optional[AgentStep]:
        for s in self.steps:
            if s.kind == AgentStepKind.APPROVAL.value and s.status == AgentStepStatus.PROPOSED.value:
                return s
        return None

    def plan_view(self) -> List[str]:
        """给前端/用户看的步骤时间线。"""
        return [s.short() for s in self.steps]


class AgentSessionStore:
    """会话仓库：进程内缓存（快路径）+ SQLite 持久化（重启不丢，Phase A1）。

    - 内存 dict 持有活跃会话对象，loop 对其原地修改立即可见（SSE 实时推流依赖此）。
    - 每次 create / persist 把会话 + 步骤落库；get 优先命中缓存，未命中则从 DB 重建。
    """

    def __init__(self):
        self._cache: Dict[str, AgentSession] = {}

    # ----- 持久化辅助 -----
    _PROV_KEY = "_provenance"

    @classmethod
    def _row_to_session(cls,
                        row: AgentSessionDB,
                        steps: Optional[List[AgentStepDB]]) -> AgentSession:
        step_objs: List[AgentStep] = []
        for sr in (steps or []):
            step_objs.append(AgentStep(
                id=sr.id,
                kind=sr.kind,
                text=sr.text,
                tool=sr.tool,
                params=sr.params_json or {},
                risk_level=sr.risk_level,
                predicted_impact=sr.predicted_impact_json,
                status=sr.status or "done",
                result=sr.result_json,
                created_at=sr.created_at.isoformat() if sr.created_at else _now(),
                expires_at=sr.expires_at.isoformat() if sr.expires_at else None,
                snapshot=sr.snapshot_json,
            ))
        raw_ctx = dict(row.context_json or {})
        prov = raw_ctx.pop(cls._PROV_KEY, None) or {}
        return AgentSession(
            id=row.id,
            app_id=row.app_id,
            user_id=row.user_id,
            goal=row.goal or "",
            status=row.status or "running",
            steps=step_objs,
            context=raw_ctx,
            platform=prov.get("platform"),
            execution_mode=prov.get("execution_mode"),
            account_id=prov.get("account_id"),
            created_at=row.created_at.isoformat() if row.created_at else _now(),
            updated_at=row.updated_at.isoformat() if row.updated_at else _now(),
            abort_requested=bool(row.abort_requested),
            pending_redirect=row.pending_redirect,
        )

    def persist(self, session: AgentSession) -> None:
        """把会话对象（含全部步骤）写入 SQLite（upsert 会话 + 重建步骤）。"""
        db = SessionLocal()
        try:
            row = db.get(AgentSessionDB, session.id)
            if row is None:
                row = AgentSessionDB(id=session.id)
                db.add(row)
            row.app_id = session.app_id
            row.user_id = session.user_id
            row.goal = session.goal
            row.status = session.status
            ctx_to_save = dict(session.context or {})
            ctx_to_save[self._PROV_KEY] = {
                "platform": session.platform,
                "execution_mode": session.execution_mode,
                "account_id": session.account_id,
            }
            row.context_json = ctx_to_save
            row.abort_requested = session.abort_requested
            row.pending_redirect = session.pending_redirect
            row.updated_at = datetime.utcnow()
            # 重建步骤（先删后插，保证顺序与当前内存一致）
            db.query(AgentStepDB).filter(AgentStepDB.session_id == session.id).delete()
            for seq, st in enumerate(session.steps, start=1):
                exp_dt: Optional[datetime] = None
                if st.expires_at:
                    try:
                        exp_dt = datetime.fromisoformat(st.expires_at.replace("Z", "+00:00"))
                        if exp_dt.tzinfo is not None:
                            exp_dt = exp_dt.astimezone(timezone.utc).replace(tzinfo=None)
                    except Exception:
                        exp_dt = None
                db.add(AgentStepDB(
                    id=st.id,
                    session_id=session.id,
                    seq=seq,
                    kind=st.kind,
                    text=st.text,
                    tool=st.tool,
                    params_json=st.params,
                    risk_level=st.risk_level,
                    predicted_impact_json=st.predicted_impact,
                    status=st.status,
                    result_json=st.result,
                    expires_at=exp_dt,
                    snapshot_json=st.snapshot,
                ))
            db.commit()
        finally:
            db.close()
        self._cache[session.id] = session

    def create(self, app_id: int, user_id: int, goal: str,
               platform: Optional[str] = None,
               execution_mode: Optional[str] = None,
               account_id: Optional[str] = None) -> AgentSession:
        s = AgentSession(
            app_id=app_id, user_id=user_id, goal=goal,
            platform=platform, execution_mode=execution_mode, account_id=account_id,
        )
        self._cache[s.id] = s
        self.persist(s)
        return s

    def get(self, session_id: str) -> Optional[AgentSession]:
        if session_id in self._cache:
            return self._cache[session_id]
        db = SessionLocal()
        try:
            row = db.get(AgentSessionDB, session_id)
            if row is None:
                return None
            steps = db.query(AgentStepDB).filter(
                AgentStepDB.session_id == session_id).order_by(AgentStepDB.seq).all()
            s = self._row_to_session(row, steps)
        finally:
            db.close()
        self._cache[session_id] = s
        return s

    def list(self, app_id: int) -> List[AgentSession]:
        db = SessionLocal()
        try:
            rows = db.query(AgentSessionDB).filter(
                AgentSessionDB.app_id == app_id).order_by(
                AgentSessionDB.created_at.desc()).all()
        finally:
            db.close()
        return [self.get(r.id) for r in rows]

    def delete(self, session_id: str) -> bool:
        self._cache.pop(session_id, None)
        db = SessionLocal()
        try:
            row = db.get(AgentSessionDB, session_id)
            if row is None:
                return False
            db.query(AgentStepDB).filter(AgentStepDB.session_id == session_id).delete()
            db.delete(row)
            db.commit()
            return True
        finally:
            db.close()

    def clear(self) -> None:
        """清空全部会话（演示 / 测试用）。"""
        self._cache.clear()
        db = SessionLocal()
        try:
            db.query(AgentStepDB).delete()
            db.query(AgentSessionDB).delete()
            db.commit()
        finally:
            db.close()


# 全局单例（与 MockMediaConnector 的引擎单例机制一致）
_session_store: Optional[AgentSessionStore] = None


def get_session_store() -> AgentSessionStore:
    global _session_store
    if _session_store is None:
        _session_store = AgentSessionStore()
    return _session_store
