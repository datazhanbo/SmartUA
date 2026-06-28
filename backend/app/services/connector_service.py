from datetime import date, datetime
from typing import Dict, List, Optional, Any
import logging
from sqlalchemy.orm import Session

from .connectors import ConnectorFactory
from app.models.data import ConnectorRun, ConnectorCredential, RawPayload, FactMediaDaily, FactMMPDaily, AggUADaily
from app.schemas.data import ConnectorCredentialCreate, ConnectorCredentialUpdate

logger = logging.getLogger(__name__)


class ConnectorService:
    """连接器管理服务"""

    def __init__(self, db: Session):
        self.db = db

    def list_connectors(self) -> Dict[str, Any]:
        """获取可用的连接器列表"""
        return ConnectorFactory.available_connectors()

    def list_connector_runs(self,
                            app_id: int,
                            connector: Optional[str] = None,
                            status: Optional[str] = None,
                            limit: int = 50,
                            offset: int = 0) -> Dict[str, Any]:
        """获取连接器运行历史"""
        query = self.db.query(ConnectorRun).filter(ConnectorRun.app_id == app_id)

        if connector:
            query = query.filter(ConnectorRun.connector == connector)
        if status:
            query = query.filter(ConnectorRun.status == status)

        total = query.count()
        runs = query.order_by(ConnectorRun.created_at.desc()).offset(offset).limit(limit).all()

        return {
            "total": total,
            "items": [
                {
                    "id": run.id,
                    "connector": run.connector,
                    "source_type": run.source_type,
                    "operation": run.operation,
                    "report_type": run.report_type,
                    "date_from": run.date_from.isoformat() if run.date_from else None,
                    "date_to": run.date_to.isoformat() if run.date_to else None,
                    "status": run.status,
                    "raw_row_count": run.raw_row_count,
                    "normalized_row_count": run.normalized_row_count,
                    "created_at": run.created_at.isoformat(),
                    "error_detail": run.error_detail,
                }
                for run in runs
            ]
        }

    def run_pull(self,
                 app_id: int,
                 platform: str,
                 date_from: date,
                 date_to: date,
                 report_type: str = "campaign_daily",
                 credentials: Dict = None,
                 account_id: str = "",
                 app_key: str = "",
                 executed_by: int = None,
                 **kwargs) -> Dict[str, Any]:
        """运行数据拉取任务"""
        credentials = credentials or self._get_default_credentials(app_id, platform)

        if not credentials:
            return {"success": False, "error": "No credentials provided"}

        connector = ConnectorFactory.get_connector(
            platform=platform,
            db=self.db,
            app_id=app_id,
            credentials=credentials
        )

        result = connector.execute_pull(
            date_from=date_from,
            date_to=date_to,
            report_type=report_type,
            account_id=account_id,
            app_key=app_key,
            executed_by=executed_by,
            **kwargs
        )

        if result.get("success"):
            self._refresh_aggregates(app_id, date_from, date_to)

        return result

    def run_operation(self,
                      app_id: int,
                      platform: str,
                      operation: str,
                      entity_id: str,
                      params: Dict,
                      credentials: Dict = None,
                      executed_by: int = None) -> Dict[str, Any]:
        """执行写操作（如更新预算、出价等）"""
        credentials = credentials or self._get_default_credentials(app_id, platform)

        if not credentials:
            return {"success": False, "error": "No credentials provided"}

        connector = ConnectorFactory.get_connector(
            platform=platform,
            db=self.db,
            app_id=app_id,
            credentials=credentials
        )

        if not connector.auth():
            return {"success": False, "error": "Authentication failed"}

        operation_map = {
            "update_campaign_budget": connector.update_campaign_budget,
            "update_campaign_status": connector.update_campaign_status,
            "update_adset_bid": connector.update_adset_bid,
        }

        handler = operation_map.get(operation)
        if not handler:
            return {"success": False, "error": f"Unknown operation: {operation}"}

        result = handler(entity_id, **params)
        result["operation"] = operation
        result["entity_id"] = entity_id

        return result

    def sync_dwd_to_dws(self, app_id: int, date_from: date, date_to: date) -> Dict[str, Any]:
        """同步 DWD 层数据到 DWS 层"""
        from sqlalchemy import func, and_

        try:
            deleted = self.db.query(AggUADaily).filter(
                and_(
                    AggUADaily.app_id == app_id,
                    AggUADaily.active_date >= date_from,
                    AggUADaily.active_date <= date_to
                )
            ).delete()

            media_agg = self.db.query(
                FactMediaDaily.date.label("active_date"),
                FactMediaDaily.app_key,
                FactMediaDaily.media_source,
                FactMediaDaily.source_platform,
                FactMediaDaily.country,
                FactMediaDaily.account_id,
                FactMediaDaily.campaign_id,
                FactMediaDaily.campaign_name,
                FactMediaDaily.adset_id,
                FactMediaDaily.adset_name,
                FactMediaDaily.ad_id,
                FactMediaDaily.ad_name,
                func.sum(FactMediaDaily.impressions).label("total_shows"),
                func.sum(FactMediaDaily.clicks).label("total_clicks"),
                func.sum(FactMediaDaily.spend).label("total_cost"),
                func.sum(FactMediaDaily.spend_usd).label("total_cost_usd"),
                func.sum(FactMediaDaily.media_installs).label("total_media_installs"),
            ).filter(
                and_(
                    FactMediaDaily.app_id == app_id,
                    FactMediaDaily.date >= date_from,
                    FactMediaDaily.date <= date_to
                )
            ).group_by(
                FactMediaDaily.date,
                FactMediaDaily.app_key,
                FactMediaDaily.media_source,
                FactMediaDaily.source_platform,
                FactMediaDaily.country,
                FactMediaDaily.account_id,
                FactMediaDaily.campaign_id,
                FactMediaDaily.campaign_name,
                FactMediaDaily.adset_id,
                FactMediaDaily.adset_name,
                FactMediaDaily.ad_id,
                FactMediaDaily.ad_name,
            ).subquery()

            mmp_agg = self.db.query(
                FactMMPDaily.date,
                FactMMPDaily.app_key,
                FactMMPDaily.media_source,
                FactMMPDaily.campaign_id,
                FactMMPDaily.country,
                func.sum(FactMMPDaily.attributed_installs).label("total_mmp_installs"),
                func.sum(FactMMPDaily.registrations).label("total_registers"),
                func.sum(FactMMPDaily.revenue).label("total_revenue"),
                func.sum(FactMMPDaily.revenue_usd).label("total_revenue_usd"),
            ).filter(
                and_(
                    FactMMPDaily.app_id == app_id,
                    FactMMPDaily.date >= date_from,
                    FactMMPDaily.date <= date_to
                )
            ).group_by(
                FactMMPDaily.date,
                FactMMPDaily.app_key,
                FactMMPDaily.media_source,
                FactMMPDaily.campaign_id,
                FactMMPDaily.country,
            ).subquery()

            agg_rows = self.db.query(
                media_agg,
                mmp_agg.c.total_mmp_installs,
                mmp_agg.c.total_registers,
                mmp_agg.c.total_revenue,
                mmp_agg.c.total_revenue_usd,
            ).outerjoin(
                mmp_agg,
                and_(
                    media_agg.c.active_date == mmp_agg.c.date,
                    media_agg.c.app_key == mmp_agg.c.app_key,
                    media_agg.c.media_source == mmp_agg.c.media_source,
                    media_agg.c.campaign_id == mmp_agg.c.campaign_id,
                    media_agg.c.country == mmp_agg.c.country,
                )
            ).all()

            inserted = 0
            for row in agg_rows:
                agg_row = AggUADaily(
                    app_id=app_id,
                    active_date=row.active_date,
                    app_key=row.app_key or "",
                    media_source=row.media_source or "",
                    source_platform=row.source_platform or "",
                    country=row.country or "ALL",
                    account_id=row.account_id or "",
                    campaign_id=row.campaign_id or "",
                    campaign_name=row.campaign_name or "",
                    adset_id=row.adset_id or "",
                    adset_name=row.adset_name or "",
                    ad_id=row.ad_id or "",
                    ad_name=row.ad_name or "",
                    total_shows=row.total_shows or 0,
                    total_clicks=row.total_clicks or 0,
                    total_cost=row.total_cost or 0,
                    total_cost_usd=row.total_cost_usd or 0,
                    total_media_installs=row.total_media_installs or 0,
                    total_mmp_installs=row.total_mmp_installs or 0,
                    total_registers=row.total_registers or 0,
                    total_revenue=row.total_revenue or 0,
                    total_revenue_usd=row.total_revenue_usd or 0,
                )

                if agg_row.total_shows > 0:
                    agg_row.ctr = agg_row.total_clicks / agg_row.total_shows
                    agg_row.cpm = agg_row.total_cost_usd * 1000 / agg_row.total_shows
                if agg_row.total_clicks > 0:
                    agg_row.cpc = agg_row.total_cost_usd / agg_row.total_clicks
                if agg_row.total_mmp_installs > 0:
                    agg_row.af_cpi = agg_row.total_cost_usd / agg_row.total_mmp_installs
                    agg_row.af_arpu = agg_row.total_revenue_usd / agg_row.total_mmp_installs
                if agg_row.total_shows > 0:
                    agg_row.ipm = agg_row.total_mmp_installs * 1000 / agg_row.total_shows
                if agg_row.total_mmp_installs > 0:
                    agg_row.af_cvr = agg_row.total_registers / agg_row.total_mmp_installs
                if agg_row.total_cost_usd > 0:
                    agg_row.roi_0 = agg_row.total_revenue_usd / agg_row.total_cost_usd

                if agg_row.total_mmp_installs > 10:
                    agg_row.match_status = "matched"
                    agg_row.signal_confidence = "high"
                elif agg_row.total_mmp_installs > 0:
                    agg_row.match_status = "partial"
                    agg_row.signal_confidence = "medium"
                else:
                    agg_row.match_status = "unmatched"
                    agg_row.signal_confidence = "low"

                self.db.add(agg_row)
                inserted += 1

            self.db.commit()

            return {
                "success": True,
                "deleted_old": deleted,
                "inserted_new": inserted,
                "date_range": {"from": date_from.isoformat(), "to": date_to.isoformat()}
            }

        except Exception as e:
            self.db.rollback()
            logger.error(f"sync_dwd_to_dws failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def _refresh_aggregates(self, app_id: int, date_from: date, date_to: date):
        """刷新聚合数据"""
        try:
            self.sync_dwd_to_dws(app_id, date_from, date_to)
        except Exception as e:
            logger.error(f"Failed to refresh aggregates: {e}")

    def _get_default_credentials(self, app_id: int, platform: str) -> Dict:
        """获取默认凭证（实际项目中从数据库读取）"""
        return {}

    def get_sync_status(self, app_id: int) -> Dict[str, Any]:
        """获取同步状态概览"""
        from sqlalchemy import func, and_

        seven_days_ago = date.today().replace(day=date.today().day - 7) if date.today().day > 7 else date.today()

        status_counts = self.db.query(
            ConnectorRun.status,
            func.count(ConnectorRun.id)
        ).filter(
            and_(
                ConnectorRun.app_id == app_id,
                ConnectorRun.created_at >= seven_days_ago
            )
        ).group_by(ConnectorRun.status).all()

        by_connector = self.db.query(
            ConnectorRun.connector,
            ConnectorRun.status,
            func.count(ConnectorRun.id)
        ).filter(
            and_(
                ConnectorRun.app_id == app_id,
                ConnectorRun.created_at >= seven_days_ago
            )
        ).group_by(ConnectorRun.connector, ConnectorRun.status).all()

        last_success = self.db.query(
            ConnectorRun.connector,
            func.max(ConnectorRun.created_at)
        ).filter(
            and_(
                ConnectorRun.app_id == app_id,
                ConnectorRun.status == "success"
            )
        ).group_by(ConnectorRun.connector).all()

        return {
            "period_days": 7,
            "status_summary": dict(status_counts),
            "by_connector": {
                conn: {
                    status: cnt
                    for (c, status, cnt) in by_connector if c == conn
                }
                for conn in set(c for c, _, _ in by_connector)
            },
            "last_success": {
                conn: dt.isoformat() if dt else None
                for conn, dt in last_success
            }
        }

    # === 凭证管理 ===

    def list_credentials(self, app_id: int, platform: Optional[str] = None) -> List[ConnectorCredential]:
        """获取凭证列表"""
        query = self.db.query(ConnectorCredential).filter(ConnectorCredential.app_id == app_id)
        if platform:
            query = query.filter(ConnectorCredential.platform == platform)
        return query.order_by(ConnectorCredential.updated_at.desc()).all()

    def get_credential(self, app_id: int, credential_id: int) -> Optional[ConnectorCredential]:
        """获取单个凭证"""
        return self.db.query(ConnectorCredential).filter(
            ConnectorCredential.app_id == app_id,
            ConnectorCredential.id == credential_id
        ).first()

    def create_credential(self, app_id: int, data: ConnectorCredentialCreate) -> ConnectorCredential:
        """创建凭证"""
        credential = ConnectorCredential(
            app_id=app_id,
            platform=data.platform,
            account_name=data.account_name,
            account_id=data.account_id,
            auth_type=data.auth_type,
            credentials_json=data.credentials_json,
            sync_frequency=data.sync_frequency,
            auto_sync_enabled=data.auto_sync_enabled,
            params=data.params or {},
            notes=data.notes,
            status="active",
            is_verified=False
        )
        self.db.add(credential)
        self.db.commit()
        self.db.refresh(credential)
        return credential

    def update_credential(self, app_id: int, credential_id: int, data: ConnectorCredentialUpdate) -> Optional[ConnectorCredential]:
        """更新凭证"""
        credential = self.get_credential(app_id, credential_id)
        if not credential:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(credential, key, value)

        credential.is_verified = False  # 更新后需要重新验证
        self.db.commit()
        self.db.refresh(credential)
        return credential

    def delete_credential(self, app_id: int, credential_id: int) -> bool:
        """删除凭证"""
        credential = self.get_credential(app_id, credential_id)
        if not credential:
            return False

        self.db.delete(credential)
        self.db.commit()
        return True

    def verify_credential(self, app_id: int, credential_id: int) -> Dict[str, Any]:
        """验证凭证是否有效"""
        credential = self.get_credential(app_id, credential_id)
        if not credential:
            return {"success": False, "error": "Credential not found"}

        try:
            connector = ConnectorFactory.get_connector(
                platform=credential.platform,
                db=self.db,
                app_id=app_id,
                credentials=credential.credentials_json
            )

            is_valid = connector.auth()

            credential.is_verified = is_valid
            credential.last_verified_at = datetime.utcnow()
            if not is_valid:
                credential.status = "error"
            self.db.commit()

            return {"success": True, "is_verified": is_valid, "platform": credential.platform}

        except Exception as e:
            logger.error(f"Verify credential failed: {e}", exc_info=True)
            credential.is_verified = False
            credential.status = "error"
            self.db.commit()
            return {"success": False, "error": str(e)}

    def _get_default_credentials(self, app_id: int, platform: str) -> Optional[Dict]:
        """获取默认凭证（从数据库读取）"""
        credential = self.db.query(ConnectorCredential).filter(
            ConnectorCredential.app_id == app_id,
            ConnectorCredential.platform == platform,
            ConnectorCredential.status == "active",
            ConnectorCredential.is_verified == True
        ).order_by(ConnectorCredential.updated_at.desc()).first()

        return credential.credentials_json if credential else None
