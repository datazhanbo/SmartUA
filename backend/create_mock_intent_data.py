"""
创建意图引擎 Mock 数据
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta
from decimal import Decimal

from app.db.base import SessionLocal
from app.models.intent import IntentExecution, StrategyTemplate, ActionLog
from app.models.sys import User

db = SessionLocal()

# 获取用户
user = db.query(User).filter(User.email == 'admin@smartua.com').first()

# ============ 1. 创建策略模板 ============
print("Creating strategy templates...")

templates = [
    {
        "name": "ROI 低于阈值自动降预算",
        "description": "当 Campaign ROI 低于指定阈值时，自动降低预算",
        "category": "budget",
        "risk_level": "L1",
        "rules_json": {
            "conditions": [{"metric": "roi_7", "operator": "<", "value": 0.5}],
            "actions": [{"type": "adjust_budget", "reduction_pct": 20}],
            "auto_execute": False
        },
        "is_system": True,
        "is_active": True
    },
    {
        "name": "高 ROI Campaign 自动提预算",
        "description": "当 Campaign ROI 高于指定阈值时，自动增加预算",
        "category": "budget",
        "risk_level": "L1",
        "rules_json": {
            "conditions": [{"metric": "roi_7", "operator": ">", "value": 1.2}],
            "actions": [{"type": "adjust_budget", "increase_pct": 20}],
            "auto_execute": True
        },
        "is_system": True,
        "is_active": True
    },
    {
        "name": "低 ROI Campaign 自动暂停",
        "description": "当 Campaign ROI 严重低于预期时自动暂停",
        "category": "status_change",
        "risk_level": "L2",
        "rules_json": {
            "conditions": [{"metric": "roi_7", "operator": "<", "value": 0.3}],
            "actions": [{"type": "pause_campaign"}],
            "auto_execute": False
        },
        "is_system": True,
        "is_active": True
    },
    {
        "name": "素材轮换策略",
        "description": "当素材 CTR 低于平均值时自动轮换",
        "category": "creative",
        "risk_level": "L1",
        "rules_json": {
            "conditions": [{"metric": "ctr", "operator": "<", "below_avg_pct": 30}],
            "actions": [{"type": "rotate_creative"}],
            "auto_execute": True
        },
        "is_system": True,
        "is_active": True
    },
    {
        "name": "异常花费告警",
        "description": "检测单日花费波动超过阈值时告警",
        "category": "alert",
        "risk_level": "L0",
        "rules_json": {
            "conditions": [{"metric": "spend_fluctuation", "operator": ">", "value": 50}],
            "actions": [{"type": "send_alert"}],
            "auto_execute": True
        },
        "is_system": True,
        "is_active": True
    }
]

for t in templates:
    template = StrategyTemplate(
        created_by=user.id,
        app_id=1,
        **t
    )
    db.add(template)
db.commit()
print(f"Created {len(templates)} strategy templates")

# ============ 2. 创建意图执行历史 ============
print("\nCreating intent execution history...")

intent_examples = [
    {
        "text": "把 ROI 低于 0.5 的 Campaign 预算降低 20%",
        "intent_class": "budget_adjustment",
        "risk_level": "L2",
        "confidence": 0.92,
        "approval_status": "approved",
        "execution_status": "success",
        "affected_count": 5,
        "notes": "识别到 5 个 Campaign ROI 低于阈值，总花费 $12,500"
    },
    {
        "text": "给 ROI > 1.2 的 Campaign 加预算 20%",
        "intent_class": "budget_adjustment",
        "risk_level": "L1",
        "confidence": 0.95,
        "approval_status": "auto_executed",
        "execution_status": "success",
        "affected_count": 8,
        "notes": "识别到 8 个高 ROI Campaign，预计增加日预算 $8,000"
    },
    {
        "text": "查看美国地区表现最差的 3 个计划",
        "intent_class": "analysis",
        "risk_level": "L0",
        "confidence": 0.98,
        "approval_status": "not_required",
        "execution_status": "success",
        "affected_count": 0,
        "notes": "查询完成，生成 US 地区 Campaign 性能报告"
    },
    {
        "text": "暂停所有花费超过 1000 美金但 ROI 为 0 的计划",
        "intent_class": "status_change",
        "risk_level": "L2",
        "confidence": 0.88,
        "approval_status": "pending",
        "execution_status": "scheduled",
        "affected_count": 3,
        "notes": "识别到 3 个 Campaign 花费超 $1000 但无回收，待审批"
    },
    {
        "text": "把转化率低于 2% 的广告组出价降低 10%",
        "intent_class": "bid_adjustment",
        "risk_level": "L1",
        "confidence": 0.91,
        "approval_status": "approved",
        "execution_status": "success",
        "affected_count": 12,
        "notes": "12 个 AdSet 出价已调整，平均 CPI 下降 8%"
    },
    {
        "text": "检查今日异常告警",
        "intent_class": "analysis",
        "risk_level": "L0",
        "confidence": 0.99,
        "approval_status": "not_required",
        "execution_status": "success",
        "affected_count": 0,
        "notes": "发现 2 条异常：Meta CPM 上涨 35%，Google 花费下降 50%"
    },
    {
        "text": "暂停所有测试用的 Campaign",
        "intent_class": "status_change",
        "risk_level": "L2",
        "confidence": 0.78,
        "approval_status": "rejected",
        "execution_status": "cancelled",
        "affected_count": 15,
        "notes": "意图歧义：未明确哪些是测试 Campaign，已拒绝执行"
    },
    {
        "text": "CTR 低于 1% 的素材全部暂停",
        "intent_class": "creative_optimization",
        "risk_level": "L1",
        "confidence": 0.85,
        "approval_status": "auto_executed",
        "execution_status": "success",
        "affected_count": 7,
        "notes": "7 个低 CTR 素材已暂停"
    }
]

for i, example in enumerate(intent_examples):
    created_at = datetime.now() - timedelta(hours=i * 2 + 1)

    approved_at = created_at + timedelta(minutes=2) if example["approval_status"] in ["approved", "auto_executed"] else None
    executed_at = approved_at + timedelta(minutes=3) if approved_at and example["execution_status"] == "success" else None

    execution = IntentExecution(
        app_id=1,
        user_id=user.id,
        intent_text=example["text"],
        intent_class=example["intent_class"],
        risk_level=example["risk_level"],
        confidence=Decimal(str(example["confidence"])),
        approval_status=example["approval_status"],
        execution_status=example["execution_status"],
        affected_count=example["affected_count"],
        notes=example["notes"],
        parameters_json={"regions": ["US"], "metrics": ["ROI", "spend"]},
        created_at=created_at,
        approved_at=approved_at,
        approved_by=user.id if approved_at else None,
        executed_at=executed_at
    )
    db.add(execution)
db.commit()
print(f"Created {len(intent_examples)} intent executions")

# ============ 3. 创建操作日志 ============
print("\nCreating action logs...")

executions = db.query(IntentExecution).filter(IntentExecution.execution_status == "success").all()
for exec in executions:
    log = ActionLog(
        app_id=1,
        user_id=user.id,
        intent_execution_id=exec.id,
        action_type=exec.intent_class,
        campaign_id=f"camp_{exec.id}",
        reason=exec.notes,
        status="success",
        created_at=exec.executed_at or datetime.now()
    )
    db.add(log)

db.commit()
print(f"Created {len(executions)} action logs")

print("\n✅ Mock intent data created successfully!")
print("\nSummary:")
print(f"  - Strategy Templates: {db.query(StrategyTemplate).count()}")
print(f"  - Intent Executions: {db.query(IntentExecution).count()}")
print(f"  - Action Logs: {db.query(ActionLog).count()}")

db.close()
