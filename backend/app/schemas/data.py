from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import date, datetime
from decimal import Decimal


class ROI360Query(BaseModel):
    date_from: date
    date_to: date
    dimensions: List[str] = ["active_date"]
    metrics: List[str] = ["total_cost_usd", "total_registers", "af_cpi", "roi_7"]
    filters: Optional[Dict[str, List[str]]] = None
    sort_by: Optional[str] = None
    sort_order: Optional[str] = "desc"


class ROI360Row(BaseModel):
    active_date: Optional[date] = None
    app_key: Optional[str] = None
    media_source: Optional[str] = None
    source_platform: Optional[str] = None
    country: Optional[str] = None
    campaign_id: Optional[str] = None
    campaign_name: Optional[str] = None

    total_shows: Optional[int] = None
    total_clicks: Optional[int] = None
    total_cost: Optional[Decimal] = None
    total_cost_usd: Optional[Decimal] = None
    total_registers: Optional[int] = None
    total_media_installs: Optional[int] = None
    total_mmp_installs: Optional[int] = None
    total_revenue: Optional[Decimal] = None
    total_revenue_usd: Optional[Decimal] = None

    ctr: Optional[Decimal] = None
    cpm: Optional[Decimal] = None
    cpc: Optional[Decimal] = None
    af_cpi: Optional[Decimal] = None
    af_cvr: Optional[Decimal] = None
    af_arpu: Optional[Decimal] = None
    ipm: Optional[Decimal] = None

    roi_0: Optional[Decimal] = None
    roi_1: Optional[Decimal] = None
    roi_3: Optional[Decimal] = None
    roi_7: Optional[Decimal] = None
    roi_14: Optional[Decimal] = None
    roi_30: Optional[Decimal] = None

    retention_1: Optional[Decimal] = None
    retention_3: Optional[Decimal] = None
    retention_7: Optional[Decimal] = None
    retention_14: Optional[Decimal] = None
    retention_30: Optional[Decimal] = None

    class Config:
        from_attributes = True


class KPISummary(BaseModel):
    total_spend: Decimal
    total_installs: int
    avg_cpi: Decimal
    avg_roi_7: Decimal
    avg_retention_7: Decimal
    total_revenue: Decimal
    spend_trend: Optional[Decimal] = None
    roi_trend: Optional[Decimal] = None


class CampaignHealthRow(BaseModel):
    campaign_id: str
    campaign_name: str
    media_source: str
    country: str

    health_score: int
    health_level: str  # healthy / subhealthy / unhealthy

    daily_spend: Decimal
    spend_trend: str

    roi_d7: Decimal
    retention_d7: Decimal
    cpi_d7: Decimal

    suggestion: str
    alert_level: str

    class Config:
        from_attributes = True


class AlertResponse(BaseModel):
    id: int
    type: str
    severity: str
    status: str
    message: str

    campaign_id: Optional[str] = None
    campaign_name: Optional[str] = None
    country: Optional[str] = None
    media_source: Optional[str] = None

    metric: Optional[str] = None
    current_value: Optional[Decimal] = None
    previous_value: Optional[Decimal] = None
    threshold: Optional[Decimal] = None
    trend: Optional[str] = None

    description: Optional[str] = None
    affected_campaigns: Optional[List[Dict[str, Any]]] = None
    suggested_actions: Optional[List[str]] = None
    detected_at: Optional[datetime] = None

    created_at: datetime
    resolved_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ConnectorCredentialBase(BaseModel):
    platform: str
    account_name: str
    account_id: Optional[str] = None
    auth_type: str = "api_key"
    credentials_json: Dict[str, Any]
    sync_frequency: str = "daily"
    auto_sync_enabled: bool = False
    params: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


class ConnectorCredentialCreate(ConnectorCredentialBase):
    pass


class ConnectorCredentialUpdate(BaseModel):
    account_name: Optional[str] = None
    account_id: Optional[str] = None
    auth_type: Optional[str] = None
    credentials_json: Optional[Dict[str, Any]] = None
    sync_frequency: Optional[str] = None
    auto_sync_enabled: Optional[bool] = None
    params: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    status: Optional[str] = None


class ConnectorCredentialResponse(ConnectorCredentialBase):
    id: int
    app_id: int
    created_at: datetime
    updated_at: datetime
    status: str
    is_verified: bool
    last_verified_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ConnectorCredentialSimpleResponse(BaseModel):
    id: int
    platform: str
    account_name: str
    account_id: Optional[str] = None
    status: str
    is_verified: bool
    auto_sync_enabled: bool

    class Config:
        from_attributes = True


class ConnectorVerifyRequest(BaseModel):
    credential_id: int
