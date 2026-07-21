"""Phase 3.1 — 动作实体与状态机的持久化仓库。

`_write()` 目前仍是"审批通过后同步调用媒体 API + 补审计"的老路径。本模块只建立
`AgentActionDB` 的读写与状态机契约；实际把 outbox / dispatcher 接进 Loop 由
Phase 3.3 完成。做法上：

- 幂等：以 `(session_id, step_id, tool, request_digest)` 派生 `idempotency_key`，
  DB UNIQUE 约束兜底。`mint_or_get` 竞争时先 flush，重复插入捕获 IntegrityError 后
  改为 SELECT 返回原动作 —— 即"同一提案永远只有一条动作，媒体只会被叫一次"。
- 状态机：合法迁移在应用层枚举；越权跳转 raise `InvalidTransition`。SQLite CHECK
  约束不友好，先靠代码兜住，Phase 5 迁 PostgreSQL 时再加数据库层保护。

不做的事：
- 不隐式提交外层事务；调用方持有 session 的所有权。
- 不发送任何媒体 API 请求 —— 那是 dispatcher 的职责。
- 不覆盖既有 IntentExecution/ActionLog 审计链；`intent_execution_id` / `action_log_id`
  只做"软链接"，方便对账时反查。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.agent_runtime import AgentActionDB


# 合法状态迁移。任何未列出的 (from → to) 均视为非法。
_ALLOWED_TRANSITIONS: Dict[str, set[str]] = {
    "proposed":    {"approved", "failed"},
    "approved":    {"dispatching", "failed"},
    "dispatching": {"accepted", "failed", "unknown"},
    "accepted":    {"verified", "failed", "unknown"},
    "unknown":     {"verified", "failed"},   # 对账后收敛
    "verified":    set(),                    # 终态
    "failed":      set(),                    # 终态
}

TERMINAL_STATES = {"verified", "failed"}


class InvalidTransition(Exception):
    """状态机拒绝的跳转（例如 verified→approved）。"""


@dataclass(frozen=True)
class ActionRequest:
    """真实写动作的冻结请求。幂等键从这里派生。"""
    session_id: str
    step_id: str
    app_id: int
    user_id: Optional[int]
    tool: str
    action: str
    entity_id: Optional[str]
    platform: Optional[str]
    account_id: Optional[str]
    execution_mode: Optional[str]
    risk_level: Optional[str]
    request: Dict[str, Any]
    pre_state: Optional[Dict[str, Any]] = None
    predicted_impact: Optional[Dict[str, Any]] = None


def _digest(payload: Dict[str, Any]) -> str:
    """稳定摘要：key 排序 + JSON 化 + SHA256 前 32 字符。"""
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_idempotency_key(session_id: str, step_id: str, tool: str,
                          request: Dict[str, Any]) -> str:
    """业务视角的稳定键。同一 step 的同一 tool + 同一参数 → 同一动作。"""
    return f"{session_id}:{step_id}:{tool}:{_digest(request)}"


class AgentActionStore:
    """AgentAction 的持久化仓库。所有方法都以传入的 SQLAlchemy Session 为准。"""

    def mint_or_get(self, db: Session, req: ActionRequest) -> AgentActionDB:
        """幂等落库。同一 idempotency_key 存在时返回既有记录，不重复插入。"""
        key = build_idempotency_key(req.session_id, req.step_id, req.tool, req.request)
        existing = db.query(AgentActionDB).filter(
            AgentActionDB.idempotency_key == key
        ).first()
        if existing is not None:
            return existing

        action = AgentActionDB(
            id=uuid.uuid4().hex[:32],
            idempotency_key=key,
            session_id=req.session_id,
            step_id=req.step_id,
            app_id=req.app_id,
            user_id=req.user_id,
            tool=req.tool,
            action=req.action,
            entity_id=req.entity_id,
            platform=req.platform,
            account_id=req.account_id,
            execution_mode=req.execution_mode,
            risk_level=req.risk_level,
            state="proposed",
            request_json=req.request,
            request_digest=_digest(req.request),
            pre_state_json=req.pre_state,
            predicted_impact_json=req.predicted_impact,
        )
        db.add(action)
        try:
            db.flush()
        except IntegrityError:
            # 并发场景下另一个线程/进程刚刚插入同一幂等键：回滚后取回原记录。
            db.rollback()
            existing = db.query(AgentActionDB).filter(
                AgentActionDB.idempotency_key == key
            ).first()
            if existing is None:
                # 极端情况：唯一约束冲突却查不到记录 —— 说明约束错位，抛出让上层看见。
                raise
            return existing
        return action

    def get(self, db: Session, action_id: str) -> Optional[AgentActionDB]:
        return db.query(AgentActionDB).filter(AgentActionDB.id == action_id).first()

    def get_by_idempotency_key(self, db: Session, key: str) -> Optional[AgentActionDB]:
        return db.query(AgentActionDB).filter(
            AgentActionDB.idempotency_key == key
        ).first()

    def transition(self, db: Session, action: AgentActionDB, to_state: str,
                   *, provider_request_id: Optional[str] = None,
                   provider_response: Optional[Dict[str, Any]] = None,
                   error: Optional[str] = None,
                   intent_execution_id: Optional[int] = None,
                   action_log_id: Optional[int] = None) -> AgentActionDB:
        """按状态机推进；非法跳转抛 InvalidTransition。"""
        current = action.state
        allowed = _ALLOWED_TRANSITIONS.get(current, set())
        if to_state not in allowed:
            raise InvalidTransition(
                f"illegal transition {current} → {to_state} for action {action.id}"
            )
        now = datetime.utcnow()
        action.state = to_state
        if to_state == "approved":
            action.approved_at = now
        elif to_state == "dispatching":
            action.dispatched_at = now
        elif to_state == "accepted":
            action.accepted_at = now
        elif to_state == "verified":
            action.verified_at = now

        if provider_request_id is not None:
            action.provider_request_id = provider_request_id
        if provider_response is not None:
            action.provider_response_json = provider_response
        if error is not None:
            action.error = error
        if intent_execution_id is not None:
            action.intent_execution_id = intent_execution_id
        if action_log_id is not None:
            action.action_log_id = action_log_id

        action.updated_at = now
        db.flush()
        return action


_store: Optional[AgentActionStore] = None


def get_action_store() -> AgentActionStore:
    global _store
    if _store is None:
        _store = AgentActionStore()
    return _store
