from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from typing import List, Optional
from datetime import date, datetime, timedelta
from app.db.base import get_db
from app.core.security import get_current_user
from app.models.sys import User
from app.models.data import AggUADaily, CampaignHealth, Alert
from app.schemas.data import (
    ROI360Query, ROI360Row, KPISummary,
    CampaignHealthRow, AlertResponse
)

router = APIRouter(prefix="/data", tags=["data"])


def apply_filters(query, model, filters: dict):
    """应用过滤条件"""
    if not filters:
        return query

    for field, values in filters.items():
        if not values:
            continue
        if hasattr(model, field):
            column = getattr(model, field)
            query = query.filter(column.in_(values))
    return query


@router.get("/roi360", response_model=List[ROI360Row])
async def get_roi360_data(
    date_from: date,
    date_to: date,
    app_id: int,
    dimensions: str = Query(default="active_date", description="逗号分隔的维度列表"),
    metrics: str = Query(default="total_cost_usd,total_registers,af_cpi,roi_7", description="逗号分隔的指标列表"),
    filters: Optional[str] = Query(default=None, description="JSON格式的过滤条件"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """ROI360数据查询"""
    # TODO: 检查用户对app_id的访问权限

    dim_list = [d.strip() for d in dimensions.split(",")]
    metric_list = [m.strip() for m in metrics.split(",")]

    # 构建查询
    query = db.query(AggUADaily).filter(
        AggUADaily.app_id == app_id,
        AggUADaily.active_date >= date_from,
        AggUADaily.active_date <= date_to
    )

    # 解析过滤条件（简化版）
    # if filters:
    #     import json
    #     filter_dict = json.loads(filters)
    #     query = apply_filters(query, AggUADaily, filter_dict)

    rows = query.order_by(AggUADaily.active_date.desc()).all()

    return rows


@router.get("/summary", response_model=KPISummary)
async def get_kpi_summary(
    app_id: int,
    days: int = Query(default=7, ge=1, le=90),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取KPI汇总数据"""
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    prev_start = start_date - timedelta(days=days)

    # 当前周期数据
    rows = db.query(
        func.sum(AggUADaily.total_cost_usd).label("spend"),
        func.sum(AggUADaily.total_mmp_installs).label("installs"),
        func.avg(AggUADaily.af_cpi).label("cpi"),
        func.avg(AggUADaily.roi_7).label("roi"),
        func.avg(AggUADaily.retention_7).label("retention"),
        func.sum(AggUADaily.total_revenue_usd).label("revenue")
    ).filter(
        AggUADaily.app_id == app_id,
        AggUADaily.active_date >= start_date,
        AggUADaily.active_date <= end_date
    ).first()

    # 上一周期数据（计算趋势）
    prev_rows = db.query(
        func.avg(AggUADaily.roi_7).label("prev_roi"),
        func.sum(AggUADaily.total_cost_usd).label("prev_spend")
    ).filter(
        AggUADaily.app_id == app_id,
        AggUADaily.active_date >= prev_start,
        AggUADaily.active_date < start_date
    ).first()

    from decimal import Decimal
    return KPISummary(
        total_spend=rows.spend or Decimal(0),
        total_installs=rows.installs or 0,
        avg_cpi=rows.cpi or Decimal(0),
        avg_roi_7=rows.roi or Decimal(0),
        avg_retention_7=rows.retention or Decimal(0),
        total_revenue=rows.revenue or Decimal(0),
        spend_trend=None,  # 简化计算
        roi_trend=None
    )


@router.get("/campaign-health", response_model=List[CampaignHealthRow])
async def get_campaign_health(
    app_id: int,
    health_level: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取Campaign健康度"""
    query = db.query(CampaignHealth).filter(
        CampaignHealth.app_id == app_id,
        CampaignHealth.snapshot_date == date.today()
    )

    if health_level:
        query = query.filter(CampaignHealth.health_level == health_level)

    rows = query.order_by(CampaignHealth.health_score).limit(limit).all()
    return rows


@router.get("/alerts", response_model=List[AlertResponse])
async def get_alerts(
    app_id: int,
    status: Optional[str] = Query(default="open", description="open/acknowledged/resolved"),
    severity: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取异常预警列表"""
    query = db.query(Alert).filter(Alert.app_id == app_id)

    if status:
        query = query.filter(Alert.status == status)
    if severity:
        query = query.filter(Alert.severity == severity)

    rows = query.order_by(Alert.created_at.desc()).limit(limit).all()

    # Map alert_type to type for frontend compatibility
    result = []
    for row in rows:
        alert_data = {c.name: getattr(row, c.name) for c in row.__table__.columns}
        alert_data['type'] = alert_data.pop('alert_type', None)
        result.append(alert_data)

    return result


@router.put("/alerts/{alert_id}/ack")
async def acknowledge_alert(
    alert_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """确认告警"""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.status = "acknowledged"
    alert.resolved_by = current_user.id
    db.commit()
    return {"status": "success", "message": "Alert acknowledged"}


@router.put("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: int,
    note: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """解决告警"""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.status = "resolved"
    alert.resolved_by = current_user.id
    alert.resolved_at = datetime.utcnow()
    alert.resolution_note = note
    db.commit()
    return {"status": "success", "message": "Alert resolved"}
