"""Agent 运行时持久化模型（Phase A1：消除重启即失）。

把原本进程内的 AgentSession / AgentStep / Episode / 自治告警&扫描 落库 SQLite，
与现有 connector 数据土壤（FactMediaDaily / FactMMPDaily / ConnectorRun）共用同一 Base。

Phase 3.1（v1.8.3）新增 AgentActionDB：真实写动作的唯一身份 + 状态机 + 幂等键。
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON, Text, ForeignKey, BigInteger, UniqueConstraint, Index
from datetime import datetime

from app.db.base import Base


class AgentSessionDB(Base):
    __tablename__ = "agent_sessions"

    id = Column(String(32), primary_key=True)
    app_id = Column(Integer, index=True)
    user_id = Column(Integer, index=True)
    goal = Column(Text)
    status = Column(String(16), default="running")
    context_json = Column(JSON)
    abort_requested = Column(Boolean, default=False)
    pending_redirect = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentStepDB(Base):
    __tablename__ = "agent_steps"

    id = Column(String(32), primary_key=True)
    session_id = Column(String(32), ForeignKey("agent_sessions.id"), index=True)
    seq = Column(Integer, default=0)
    kind = Column(String(16))
    text = Column(Text)
    tool = Column(String(64), nullable=True)
    params_json = Column(JSON)
    risk_level = Column(String(8), nullable=True)
    predicted_impact_json = Column(JSON)
    status = Column(String(16), default="done")
    result_json = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Phase 3.2 —— 审批过期与漂移校验
    # 仅审批类步骤会写入：expires_at = 提案时刻 + agent_approval_ttl_seconds；
    # snapshot_json = 提案时刻从 connector 读到的实体关键指标（roi/spend/status/daily_budget），
    # 审批通过后 Loop 会重新读取并对比，漂移超阈值则拒绝执行、重新规划。
    expires_at = Column(DateTime, nullable=True)
    snapshot_json = Column(JSON, nullable=True)


class EpisodeDB(Base):
    __tablename__ = "agent_episodes"

    episode_id = Column(String(32), primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    session_id = Column(String(32), nullable=True, index=True)
    goal = Column(Text)
    action = Column(String(64), index=True)
    action_label = Column(String(128))
    intent_class = Column(String(64))
    params_json = Column(JSON)
    pre_state_json = Column(JSON)
    impact_json = Column(JSON)
    outcome = Column(Boolean, default=True)
    note = Column(Text)


class AutonomyAlertDB(Base):
    __tablename__ = "agent_autonomy_alerts"

    id = Column(String(32), primary_key=True)
    detected_at = Column(DateTime, default=datetime.utcnow)
    app_id = Column(Integer, index=True)
    anomaly_json = Column(JSON)
    status = Column(String(32), default="pending_approval")
    session_id = Column(String(32), nullable=True)
    step_id = Column(String(32), nullable=True)
    resolution = Column(Text)


class AutonomyScanDB(Base):
    __tablename__ = "agent_autonomy_scans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    at = Column(DateTime, default=datetime.utcnow)
    app_id = Column(Integer, index=True)
    n_anomalies = Column(Integer, default=0)
    n_alerts = Column(Integer, default=0)


# Phase 3.1 — 动作实体与状态机 -------------------------------------------------
#
# 状态机（应用层强制）：
#   proposed → approved → dispatching → accepted → verified
#                                              └→ failed
#                                              └→ unknown（超时/无响应，待对账）
#   proposed → failed（审批前被拒/参数不合法）
#
# 幂等：(session_id, step_id, tool, params_digest) → idempotency_key（UNIQUE）
# 重复提交返回原动作，不重新调用媒体 API。真正的 outbox / dispatcher 由 Phase 3.3 引入。
class AgentActionDB(Base):
    __tablename__ = "agent_actions"

    id = Column(String(32), primary_key=True)
    idempotency_key = Column(String(96), nullable=False)
    session_id = Column(String(32), ForeignKey("agent_sessions.id"), index=True)
    step_id = Column(String(32), ForeignKey("agent_steps.id"), index=True)
    app_id = Column(Integer, index=True, nullable=False)
    user_id = Column(Integer, index=True)
    # 现有审计链的软关联（不加 FK 约束，允许 mock/无 db 场景）
    intent_execution_id = Column(BigInteger, index=True, nullable=True)
    action_log_id = Column(BigInteger, index=True, nullable=True)

    tool = Column(String(64), nullable=False)                  # eg. pause_campaign
    action = Column(String(64), nullable=False)                # 引擎侧动作 update_campaign_status
    entity_id = Column(String(128), index=True, nullable=True)  # 通常是 campaign_id
    platform = Column(String(32), nullable=True)               # meta / google / tiktok / mock
    account_id = Column(String(64), nullable=True)
    execution_mode = Column(String(16), nullable=True)         # mock / sandbox / live
    risk_level = Column(String(8), nullable=True)              # L0/L1/L2/L3

    state = Column(String(16), nullable=False, default="proposed", index=True)
    # proposed / approved / dispatching / accepted / verified / failed / unknown

    request_json = Column(JSON, nullable=True)                 # 冻结的动作参数
    request_digest = Column(String(64), nullable=True)         # sha256(request_json)
    pre_state_json = Column(JSON, nullable=True)               # 动作前实体快照
    predicted_impact_json = Column(JSON, nullable=True)        # 预测影响（不再冒充实际）
    provider_request_id = Column(String(128), nullable=True)   # 媒体返回的请求 ID
    provider_response_json = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    approved_at = Column(DateTime, nullable=True)
    dispatched_at = Column(DateTime, nullable=True)
    accepted_at = Column(DateTime, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_agent_actions_idempotency"),
        Index("ix_agent_actions_app_state", "app_id", "state"),
    )
