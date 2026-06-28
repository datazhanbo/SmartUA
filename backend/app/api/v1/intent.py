from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
from app.db.base import get_db
from app.core.security import get_current_user
from app.models.sys import User
from app.models.intent import IntentExecution, StrategyTemplate
from app.services.intent_engine import get_intent_engine
from app.schemas.intent import (
    IntentParseRequest, IntentParseResponse,
    IntentApprovalRequest, IntentExecutionResponse,
    StrategyTemplateCreate, StrategyTemplateResponse
)

router = APIRouter(prefix="/intent", tags=["intent"])


@router.post("/parse", response_model=IntentParseResponse)
async def parse_intent(
    request: IntentParseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """解析自然语言意图"""
    engine = get_intent_engine(db, current_user, request.app_id)
    result = engine.parse(request.text)
    return IntentParseResponse(**result)


@router.post("/execute")
async def parse_and_execute(
    request: IntentParseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """解析并创建意图执行记录"""
    engine = get_intent_engine(db, current_user, request.app_id)
    parse_result = engine.parse(request.text)
    execution = engine.create_execution(parse_result, request.text)

    return {
        "execution_id": execution.id,
        "risk_level": execution.risk_level,
        "approval_status": execution.approval_status,
        "execution_status": execution.execution_status,
        "affected_count": execution.affected_count,
        "approval_required": execution.approval_status == "pending",
        "approval_deadline": execution.approval_deadline
    }


@router.post("/approve")
async def approve_execution(
    request: IntentApprovalRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """审批意图执行"""
    execution = db.query(IntentExecution).filter(
        IntentExecution.id == request.execution_id
    ).first()

    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    # 检查权限
    if execution.risk_level == "L3":
        # L3级别操作需要管理员权限
        pass  # TODO: 实现权限检查

    engine = get_intent_engine(db, current_user, execution.app_id)
    result = engine.approve(request.execution_id, request.approved, request.reason)

    return {
        "execution_id": result.id,
        "approval_status": result.approval_status,
        "execution_status": result.execution_status
    }


@router.get("/executions", response_model=List[IntentExecutionResponse])
async def list_executions(
    app_id: int,
    status: str = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """列出意图执行历史"""
    query = db.query(IntentExecution).filter(IntentExecution.app_id == app_id)

    if status:
        if status in ["pending", "approved", "rejected", "timeout", "auto_executed"]:
            query = query.filter(IntentExecution.approval_status == status)
        else:
            query = query.filter(IntentExecution.execution_status == status)

    executions = query.order_by(IntentExecution.created_at.desc()).limit(limit).all()
    return executions


@router.get("/executions/{execution_id}")
async def get_execution_detail(
    execution_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取执行详情"""
    execution = db.query(IntentExecution).filter(
        IntentExecution.id == execution_id
    ).first()

    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    return {
        "id": execution.id,
        "intent_text": execution.intent_text,
        "intent_class": execution.intent_class,
        "risk_level": execution.risk_level,
        "confidence": float(execution.confidence) if execution.confidence else None,
        "parameters": execution.parameters_json,
        "affected_campaigns": execution.affected_campaigns_json,
        "estimated_impact": execution.estimated_impact_json,
        "approval_status": execution.approval_status,
        "execution_status": execution.execution_status,
        "created_at": execution.created_at,
        "approved_at": execution.approved_at,
        "executed_at": execution.executed_at,
        "impact_2h": execution.impact_2h_json,
        "impact_24h": execution.impact_24h_json,
        "impact_7d": execution.impact_7d_json,
        "actions_log": execution.actions_log_json
    }


# ==================== 策略模板 ====================

@router.get("/strategies", response_model=List[StrategyTemplateResponse])
async def list_strategies(
    app_id: int,
    category: str = None,
    is_active: bool = True,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """列出策略模板"""
    query = db.query(StrategyTemplate).filter(
        StrategyTemplate.app_id == app_id,
        StrategyTemplate.is_active == is_active
    )

    if category:
        query = query.filter(StrategyTemplate.category == category)

    return query.order_by(StrategyTemplate.created_at.desc()).all()


@router.post("/strategies", response_model=StrategyTemplateResponse)
async def create_strategy(
    strategy: StrategyTemplateCreate,
    app_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建策略模板"""
    template = StrategyTemplate(
        app_id=app_id,
        created_by=current_user.id,
        **strategy.model_dump()
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.put("/strategies/{strategy_id}")
async def update_strategy(
    strategy_id: int,
    strategy: StrategyTemplateCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新策略模板"""
    template = db.query(StrategyTemplate).filter(
        StrategyTemplate.id == strategy_id
    ).first()

    if not template:
        raise HTTPException(status_code=404, detail="Strategy not found")

    for field, value in strategy.model_dump().items():
        setattr(template, field, value)

    template.updated_at = datetime.utcnow()
    db.commit()
    return {"status": "success"}


@router.delete("/strategies/{strategy_id}")
async def delete_strategy(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """删除（停用）策略模板"""
    template = db.query(StrategyTemplate).filter(
        StrategyTemplate.id == strategy_id
    ).first()

    if not template:
        raise HTTPException(status_code=404, detail="Strategy not found")

    template.is_active = False
    db.commit()
    return {"status": "success"}
