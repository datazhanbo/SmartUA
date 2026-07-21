"""Agent 运行时持久化模型（Phase A1：消除重启即失）。

把原本进程内的 AgentSession / AgentStep / Episode / 自治告警&扫描 落库 SQLite，
与现有 connector 数据土壤（FactMediaDaily / FactMMPDaily / ConnectorRun）共用同一 Base。
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON, Text, ForeignKey
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
