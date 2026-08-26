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
    # Phase 4.3 —— Episode 学习门禁 -----------------------------------------
    # execution_mode: 记录动作真实执行环境（mock / sandbox / live）。
    #   Mock/Sandbox Episode 永远不能反哺生产策略。
    # data_quality: 结构化数据来源，形如
    #   {"impact_kind": "predicted|observed|attributed",
    #    "execution_mode": "mock|sandbox|live",
    #    "completeness": 0.0~1.0,
    #    "sources": ["fact_media_daily", "appsflyer_mmp"]}
    # usable_for_learning: 显式布尔门。默认 False，只有当
    #   (execution_mode == "live") ∧ (impact_kind ∈ {observed, attributed})
    #   ∧ (completeness > 0) 时由回采任务提权为 True。
    # evidence_action_ids: 关联的 AgentActionDB.id 列表；反思和策略调整必须能"点到"证据。
    # action_id: 单条 Episode 对应的动作（1-1；一个 Episode 由一个动作产出）。
    execution_mode = Column(String(16), nullable=True, index=True)
    data_quality_json = Column(JSON, nullable=True)
    usable_for_learning = Column(Boolean, default=False, index=True)
    evidence_action_ids_json = Column(JSON, nullable=True)
    action_id = Column(String(32), ForeignKey("agent_actions.id"), nullable=True, index=True)


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
    predicted_impact_json = Column(JSON, nullable=True)        # Phase 4.1: 严格只存"预测"，不再冒充实际
    # Phase 4.1 —— 三类影响严格拆分：
    # observed_impact_json：动作生效后从媒体侧读到的账面变化（Google/Meta/TikTok Reports）。
    #   由 Phase 4.2 延迟回采任务在 2h/24h/7d 窗口填入；未回采完成前保持 NULL，不能用 0 冒充。
    # attributed_impact_json：把变化归因到"本次动作"的部分（MMP、matched control、DiD）。
    #   同样只在归因数据可用时写入；不可用则保持 NULL。
    # 三个字段都遵循 impact.ImpactEnvelope 形状（kind/metrics/window/tz/currency/source/freshness/completeness）。
    observed_impact_json = Column(JSON, nullable=True)
    attributed_impact_json = Column(JSON, nullable=True)
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


# Phase 4.4 —— Durable Background Jobs（P2 #4） ----------------------------
#
# 通用延迟任务表：impact 回采、autonomy 周期巡检、未来其它后台 job 都落这张表。
# APScheduler 只做高频 tick（默认 30s），真正的 job 状态在 DB，进程重启可恢复。
#
# 状态机（应用层强制）：
#   scheduled → running → done
#                      └→ failed（attempts < max_attempts 时由 recover_stale 复位为 scheduled）
# 启动时 recover_stale 把 started_at 早于 stale_timeout 的 running job 复位，
# 保证进程崩溃不会让 job 永远卡在 running。
#
# idempotency_key：同 key 的 job 只允许一条（UNIQUE），用于重入去重；
# impact job 用 f"impact:{action_id}:{kind}:{window}"。
class JobDB(Base):
    __tablename__ = "agent_jobs"

    id = Column(String(32), primary_key=True)
    job_type = Column(String(64), nullable=False, index=True)
    idempotency_key = Column(String(128), nullable=False)

    status = Column(String(16), nullable=False, default="scheduled", index=True)
    # scheduled / running / done / failed / cancelled

    scheduled_at = Column(DateTime, nullable=False, index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    payload = Column(JSON, nullable=True)
    result = Column(JSON, nullable=True)
    attempts = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=1, nullable=False)
    last_error = Column(Text, nullable=True)

    app_id = Column(Integer, nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_agent_jobs_idempotency"),
        Index("ix_agent_jobs_due", "status", "scheduled_at"),
        Index("ix_agent_jobs_type_status", "job_type", "status"),
    )
