from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from decimal import Decimal

from app.db.base import get_db
from app.models.campaign import Campaign, AdGroup, Ad, Creative
from app.schemas.campaign import (
    Campaign as CampaignSchema,
    CampaignCreate,
    CampaignUpdate,
    CampaignDetail,
    AdGroup as AdGroupSchema,
    Ad as AdSchema,
    Creative as CreativeSchema,
)

router = APIRouter(tags=["campaigns"])


# ============ Campaign APIs ============
@router.get("/campaigns", response_model=List[CampaignSchema])
def list_campaigns(
    app_id: Optional[int] = None,
    status: Optional[str] = None,
    media: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Campaign)
    if app_id:
        query = query.filter(Campaign.app_id == app_id)
    if status:
        query = query.filter(Campaign.status == status)
    if media:
        query = query.filter(Campaign.media == media)
    return query.order_by(Campaign.updated_at.desc()).all()


@router.get("/campaigns/{campaign_id}", response_model=CampaignDetail)
def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.post("/campaigns", response_model=CampaignSchema)
def create_campaign(campaign: CampaignCreate, db: Session = Depends(get_db)):
    db_campaign = Campaign(
        **campaign.model_dump(),
        budget=campaign.total_budget,
    )
    db.add(db_campaign)
    db.commit()
    db.refresh(db_campaign)
    return db_campaign


@router.put("/campaigns/{campaign_id}", response_model=CampaignSchema)
def update_campaign(campaign_id: int, update: CampaignUpdate, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    for key, value in update.model_dump(exclude_unset=True).items():
        setattr(campaign, key, value)

    db.commit()
    db.refresh(campaign)
    return campaign


@router.delete("/campaigns/{campaign_id}")
def delete_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    db.delete(campaign)
    db.commit()
    return {"message": "Campaign deleted successfully"}


# ============ AdGroup APIs ============
@router.get("/campaigns/{campaign_id}/adgroups", response_model=List[AdGroupSchema])
def list_adgroups(campaign_id: int, db: Session = Depends(get_db)):
    return db.query(AdGroup).filter(AdGroup.campaign_id == campaign_id).all()


@router.get("/adgroups/{adgroup_id}", response_model=AdGroupSchema)
def get_adgroup(adgroup_id: int, db: Session = Depends(get_db)):
    adgroup = db.query(AdGroup).filter(AdGroup.id == adgroup_id).first()
    if not adgroup:
        raise HTTPException(status_code=404, detail="AdGroup not found")
    return adgroup


# ============ Ad APIs ============
@router.get("/adgroups/{adgroup_id}/ads", response_model=List[AdSchema])
def list_ads(adgroup_id: int, db: Session = Depends(get_db)):
    return db.query(Ad).filter(Ad.ad_group_id == adgroup_id).all()


# ============ Creative APIs ============
@router.get("/creatives", response_model=List[CreativeSchema])
def list_creatives(
    app_id: Optional[int] = None,
    type: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Creative)
    if app_id:
        query = query.filter(Creative.app_id == app_id)
    if type:
        query = query.filter(Creative.type == type)
    if status:
        query = query.filter(Creative.status == status)
    return query.order_by(Creative.updated_at.desc()).all()


@router.get("/creatives/{creative_id}", response_model=CreativeSchema)
def get_creative(creative_id: int, db: Session = Depends(get_db)):
    creative = db.query(Creative).filter(Creative.id == creative_id).first()
    if not creative:
        raise HTTPException(status_code=404, detail="Creative not found")
    return creative


@router.get("/campaigns/{campaign_id}/creatives", response_model=List[CreativeSchema])
def get_campaign_creatives(campaign_id: int, db: Session = Depends(get_db)):
    """获取 Campaign 关联的所有素材"""
    creatives = db.query(Creative).join(Ad).join(AdGroup).filter(
        AdGroup.campaign_id == campaign_id
    ).distinct().all()
    return creatives


# ============ Dashboard Data API ============
@router.get("/dashboard/campaigns")
def dashboard_campaigns(
    app_id: int = 1,
    db: Session = Depends(get_db)
):
    """投放大盘数据"""
    campaigns = db.query(Campaign).filter(
        Campaign.app_id == app_id
    ).order_by(Campaign.updated_at.desc()).all()

    total_spend = sum(c.spend for c in campaigns if c.spend)
    total_installs = sum(c.installs for c in campaigns)
    active_count = sum(1 for c in campaigns if c.status == "running")

    avg_roi = Decimal(0)
    if campaigns:
        rois = [c.roi for c in campaigns if c.roi]
        if rois:
            avg_roi = sum(rois) / len(rois)

    return {
        "campaigns": campaigns,
        "summary": {
            "total_spend": total_spend,
            "total_installs": total_installs,
            "active_count": active_count,
            "avg_roi": avg_roi
        }
    }
