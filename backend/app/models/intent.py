from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, JSON, BigInteger, Text, Numeric
from datetime import datetime
from app.db.base import Base


class IntentExecution(Base):
    """意图执行记录：大模型识别 + 安全分级 + 闭环学习"""
    __tablename__ = "intent_executions"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    app_id = Column(Integer, ForeignKey("apps.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # 意图识别结果
    intent_text = Column(Text, nullable=False)
    intent_class = Column(String(64), index=True)
    confidence = Column(Numeric(4, 3))
    risk_level = Column(String(8), index=True)  # L0 / L1 / L2 / L3
    parameters_json = Column(JSON)
    affected_count = Column(Integer)

    # 受影响的Campaign
    affected_campaigns_json = Column(JSON)

    # 影响预估
    estimated_impact_json = Column(JSON)

    # 审批流程
    approval_status = Column(String(16), default="pending", index=True)
    # pending / approved / rejected / timeout / auto_executed
    approved_by = Column(Integer, ForeignKey("users.id"))
    approved_at = Column(DateTime)
    rejection_reason = Column(Text)

    # 审批超时自动执行（L1级别）
    approval_deadline = Column(DateTime)
    auto_execute_on_timeout = Column(Boolean, default=False)

    # 执行状态
    execution_status = Column(String(16), default="scheduled", index=True)
    # scheduled / running / success / failed / rolled_back
    executed_at = Column(DateTime)
    execution_error = Column(Text)

    # 效果回扫检查点（历史遗留：预测影响写入 impact_2h/24h/7d_json；仍供 Episode / Memory 消费）
    impact_2h_json = Column(JSON)
    impact_24h_json = Column(JSON)
    impact_7d_json = Column(JSON)

    # Phase 4.1 —— 三类影响严格拆分：
    # observed_impact_json / attributed_impact_json 只在真实回采 / 归因数据到位后写入；
    # 若未回采则保持 NULL —— 学习门禁（Phase 4.3）用它区分"可训练样本"与"仅预测样本"。
    observed_impact_json = Column(JSON)
    attributed_impact_json = Column(JSON)

    # 闭环学习
    model_feedback = Column(String(16))  # good / bad / neutral
    human_feedback = Column(String(16))   # thumbs_up / thumbs_down
    notes = Column(Text)

    # 操作审计
    actions_log_json = Column(JSON)  # 记录所有实际执行的API调用


class StrategyTemplate(Base):
    """策略模板库"""
    __tablename__ = "strategy_templates"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    app_id = Column(Integer, ForeignKey("apps.id"), nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    name = Column(String(128), nullable=False)
    description = Column(Text)
    category = Column(String(32), index=True)  # budget / bidding / creative / audience
    risk_level = Column(String(8), default="L1")

    # 策略规则定义
    rules_json = Column(JSON, nullable=False)
    # {
    #   "conditions": [{"metric": "roi_7", "operator": "<", "value": 0.5}],
    #   "actions": [{"type": "pause_campaign"}],
    #   "auto_execute": false
    # }

    is_active = Column(Boolean, default=True)
    is_system = Column(Boolean, default=False)
    success_count = Column(Integer, default=0)
    total_applications = Column(Integer, default=0)
    avg_impact_roi = Column(Numeric(10, 6))


class ActionLog(Base):
    """投放操作日志"""
    __tablename__ = "action_logs"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    app_id = Column(Integer, ForeignKey("apps.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    intent_execution_id = Column(BigInteger, ForeignKey("intent_executions.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    action_type = Column(String(32), nullable=False)
    # pause_campaign / resume_campaign / adjust_budget / adjust_bid / change_creative

    campaign_id = Column(String(128), index=True)
    adset_id = Column(String(128))
    ad_id = Column(String(128))

    old_value_json = Column(JSON)
    new_value_json = Column(JSON)
    reason = Column(Text)

    # 效果追踪
    impact_24h_json = Column(JSON)
    impact_7d_json = Column(JSON)

    platform = Column(String(32))  # meta / google / tiktok
    platform_response_json = Column(JSON)
    status = Column(String(16), default="success")
