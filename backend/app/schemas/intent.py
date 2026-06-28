from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from decimal import Decimal


class IntentParseRequest(BaseModel):
    text: str
    app_id: int


class AffectedCampaign(BaseModel):
    id: str
    name: str
    roi: Optional[Decimal] = None
    spend: Optional[Decimal] = None
    cpi: Optional[Decimal] = None


class EstimatedImpact(BaseModel):
    daily_spend_reduction: Optional[Decimal] = None
    expected_roi_improvement: Optional[Decimal] = None
    affected_campaign_count: Optional[int] = None


class IntentParseResponse(BaseModel):
    intent_class: str
    confidence: float
    risk_level: str  # L0 / L1 / L2 / L3
    parameters_extracted: Dict[str, Any]
    affected_campaigns: List[AffectedCampaign]
    estimated_impact: EstimatedImpact
    approval_required: bool
    approval_deadline: Optional[datetime] = None
    suggested_actions: List[Dict[str, Any]]
    raw_llm_response: Optional[str] = None


class IntentApprovalRequest(BaseModel):
    execution_id: int
    approved: bool
    reason: Optional[str] = None


class IntentExecutionResponse(BaseModel):
    id: int
    intent_text: str
    intent_class: str
    risk_level: str
    approval_status: str
    execution_status: str
    affected_count: int
    created_at: datetime
    approved_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class StrategyTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    category: str
    risk_level: str = "L1"
    rules_json: Dict[str, Any]


class StrategyTemplateResponse(StrategyTemplateCreate):
    id: int
    is_active: bool
    success_count: int
    total_applications: int
    avg_impact_roi: Optional[Decimal] = None
    created_at: datetime

    class Config:
        from_attributes = True
