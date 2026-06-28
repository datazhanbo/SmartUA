from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
from decimal import Decimal


# ============ Creative Schemas ============
class CreativeBase(BaseModel):
    name: str
    type: str
    format: Optional[str] = None
    file_size: Optional[int] = None
    duration: Optional[int] = None
    resolution: Optional[str] = None
    url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    designer: Optional[str] = None
    tags: Optional[List[str]] = None
    status: Optional[str] = "active"


class CreativeCreate(CreativeBase):
    app_id: int


class CreativeUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    tags: Optional[List[str]] = None


class Creative(CreativeBase):
    id: int
    app_id: int
    spend: Decimal = Field(default=0)
    impressions: int = Field(default=0)
    clicks: int = Field(default=0)
    installs: int = Field(default=0)
    ctr: Optional[Decimal] = None
    cpc: Optional[Decimal] = None
    cpi: Optional[Decimal] = None
    roi: Optional[Decimal] = None
    conversion_rate: Optional[Decimal] = None
    performance_score: int = Field(default=50)
    trend: Optional[str] = "stable"
    last_used_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============ Ad Schemas ============
class AdBase(BaseModel):
    name: str
    ad_type: Optional[str] = None
    placement: Optional[str] = None
    title: Optional[str] = None
    body: Optional[str] = None
    cta_text: Optional[str] = None


class AdCreate(AdBase):
    ad_group_id: int
    creative_id: Optional[int] = None


class AdUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    title: Optional[str] = None
    body: Optional[str] = None


class Ad(AdBase):
    id: int
    ad_group_id: int
    creative_id: Optional[int] = None
    status: str
    spend: Decimal = Field(default=0)
    impressions: int = Field(default=0)
    clicks: int = Field(default=0)
    installs: int = Field(default=0)
    ctr: Optional[Decimal] = None
    cpc: Optional[Decimal] = None
    cpi: Optional[Decimal] = None
    roi: Optional[Decimal] = None
    conversion_rate: Optional[Decimal] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============ AdGroup Schemas ============
class AdGroupBase(BaseModel):
    name: str
    bid_amount: Optional[Decimal] = None
    daily_budget: Optional[Decimal] = None
    audience_json: Optional[dict] = None


class AdGroupCreate(AdGroupBase):
    campaign_id: int


class AdGroupUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    bid_amount: Optional[Decimal] = None
    daily_budget: Optional[Decimal] = None


class AdGroup(AdGroupBase):
    id: int
    campaign_id: int
    status: str
    spend: Decimal = Field(default=0)
    impressions: int = Field(default=0)
    clicks: int = Field(default=0)
    installs: int = Field(default=0)
    cpi: Optional[Decimal] = None
    ctr: Optional[Decimal] = None
    roi: Optional[Decimal] = None
    created_at: datetime
    updated_at: datetime

    ads: List[Ad] = Field(default_factory=list)

    class Config:
        from_attributes = True


# ============ Campaign Schemas ============
class CampaignBase(BaseModel):
    name: str
    media: Optional[str] = None
    dsp: Optional[str] = None
    campaign_type: Optional[str] = None
    objective: Optional[str] = None
    bid_strategy: Optional[str] = None
    optimization_goal: Optional[str] = None
    country: Optional[str] = None
    platform: Optional[str] = None
    daily_budget: Optional[Decimal] = None
    total_budget: Optional[Decimal] = None
    target_cpi: Optional[Decimal] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    account_id: Optional[str] = None
    ctr: Optional[Decimal] = None


class CampaignCreate(CampaignBase):
    app_id: int


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    daily_budget: Optional[Decimal] = None
    target_cpi: Optional[Decimal] = None
    notes: Optional[str] = None


class Campaign(CampaignBase):
    id: int
    app_id: int
    status: str
    health: str
    spend: Decimal = Field(default=0)
    budget: Optional[Decimal] = None
    roi: Optional[Decimal] = None
    cpi: Optional[Decimal] = None
    impressions: int = Field(default=0)
    clicks: int = Field(default=0)
    installs: int = Field(default=0)
    ctr: Optional[Decimal] = None
    last_update: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    ad_groups: List[AdGroup] = Field(default_factory=list)

    class Config:
        from_attributes = True


# ============ Campaign Detail ============
class CampaignDetail(Campaign):
    ad_groups: List[AdGroup] = Field(default_factory=list)

    class Config:
        from_attributes = True


# ============ Campaign List Response ============
class CampaignListResponse(BaseModel):
    total: int
    items: List[Campaign]
