from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import List, Dict, Optional, Any
import hashlib
import logging
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class BaseConnector(ABC):
    """所有连接器的基类"""

    platform: str           # 平台标识，如 "meta", "google"
    source_type: str        # "media" / "mmp" / "dsp"
    rate_limit: int = 60    # API 每秒请求限制
    timeout: int = 30       # 请求超时时间（秒）

    def __init__(self, db: Session, app_id: int, credentials: Dict[str, Any]):
        self.db = db
        self.app_id = app_id
        self.credentials = credentials
        self.client = None
        self.run_id: Optional[int] = None

    @abstractmethod
    def auth(self) -> bool:
        """认证方法"""
        pass

    @abstractmethod
    def pull(self,
             date_from: date,
             date_to: date,
             report_type: str = "campaign_daily",
             **kwargs) -> Dict[str, Any]:
        """拉取数据核心方法"""
        pass

    @abstractmethod
    def normalize(self, raw_rows: List[Dict]) -> List[Dict]:
        """字段标准化转换"""
        pass

    def validate(self, rows: List[Dict]) -> bool:
        """数据校验（可选重写）"""
        if not rows:
            return True

        required_fields = ["date", "campaign_id", "impressions", "clicks", "spend"]
        for row in rows:
            for field in required_fields:
                if field not in row or row[field] is None:
                    logger.warning(f"Missing required field: {field} in row")
                    return False

            if row.get("impressions", 0) < 0:
                logger.warning("Invalid negative impressions")
                return False
            if row.get("clicks", 0) < 0:
                logger.warning("Invalid negative clicks")
                return False
            if row.get("spend", 0) < 0:
                logger.warning("Invalid negative spend")
                return False

        return True

    def _calculate_row_hash(self, row: Dict) -> str:
        """计算行数据唯一哈希，用于幂等性保证"""
        hash_components = [
            self.platform,
            str(row.get("date", "")),
            str(row.get("campaign_id", "")),
            str(row.get("adset_id", "")),
            str(row.get("ad_id", "")),
            str(row.get("country", "ALL")),
            str(row.get("account_id", "")),
        ]
        hash_string = "|".join(hash_components)
        return hashlib.md5(hash_string.encode("utf-8")).hexdigest()

    def save_ods(self, raw_data: Dict, run_id: int) -> int:
        """保存原始数据到 ODS 层（统一实现）"""
        from app.models.data import RawPayload
        import json

        raw_rows = raw_data.get("raw_rows", [])
        metadata = raw_data.get("metadata", {})

        if not raw_rows:
            return 0

        # 确保日期字段是字符串格式
        def ensure_date_str(d):
            if isinstance(d, date):
                return d.isoformat()
            return str(d) if d else None

        safe_metadata = dict(metadata)
        safe_metadata["date_from"] = ensure_date_str(metadata.get("date_from"))
        safe_metadata["date_to"] = ensure_date_str(metadata.get("date_to"))

        payload_json = {
            "platform": self.platform,
            "source_type": self.source_type,
            "pulled_at": datetime.utcnow().isoformat(),
            "rows": raw_rows,
            "metadata": safe_metadata
        }

        payload_str = json.dumps(payload_json, sort_keys=True)
        payload_hash = hashlib.md5(payload_str.encode("utf-8")).hexdigest()

        # 转换回 date 对象用于数据库
        def parse_date(d):
            if isinstance(d, date):
                return d
            if d:
                from datetime import datetime as dt
                return dt.strptime(str(d).split("T")[0], "%Y-%m-%d").date()
            return None

        raw_payload = RawPayload(
            run_id=run_id,
            app_id=self.app_id,
            connector=self.platform,
            source_type=self.source_type,
            report_type=safe_metadata.get("report_type", "campaign_daily"),
            endpoint=safe_metadata.get("endpoint", ""),
            account_id=safe_metadata.get("account_id", ""),
            app_key=safe_metadata.get("app_key", ""),
            date_from=parse_date(safe_metadata.get("date_from")),
            date_to=parse_date(safe_metadata.get("date_to")),
            request_hash=safe_metadata.get("request_hash", ""),
            payload_hash=payload_hash,
            row_count=len(raw_rows),
            payload_json=payload_json,
            file_size_bytes=len(payload_str.encode("utf-8"))
        )

        self.db.add(raw_payload)
        self.db.flush()

        return len(raw_rows)

    def save_dwd(self, normalized_rows: List[Dict], run_id: int) -> int:
        """保存标准化数据到 DWD 层（统一实现）"""
        from app.models.data import FactMediaDaily, FactMMPDaily
        from sqlalchemy.dialects.postgresql import insert

        if not normalized_rows:
            return 0

        saved_count = 0

        if self.source_type == "media":
            for row in normalized_rows:
                source_row_hash = self._calculate_row_hash(row)

                # 转换 date
                row_date = row.get("date")
                if isinstance(row_date, str):
                    from datetime import datetime as dt
                    row_date = dt.strptime(row_date.split("T")[0], "%Y-%m-%d").date()

                insert_stmt = insert(FactMediaDaily).values(
                    run_id=run_id,
                    app_id=self.app_id,
                    source_platform=self.platform,
                    source_type=self.source_type,
                    date=row_date,
                    account_id=row.get("account_id", ""),
                    app_key=row.get("app_key", ""),
                    media_source=row.get("media_source", self.platform),
                    campaign_id=str(row.get("campaign_id", "")),
                    campaign_name=row.get("campaign_name", ""),
                    adset_id=str(row.get("adset_id", "")),
                    adset_name=row.get("adset_name", ""),
                    ad_id=str(row.get("ad_id", "")),
                    ad_name=row.get("ad_name", ""),
                    creative_id=str(row.get("creative_id", "")),
                    creative_name=row.get("creative_name", ""),
                    country=row.get("country", "ALL"),
                    currency=row.get("currency", "USD"),
                    impressions=row.get("impressions", 0),
                    clicks=row.get("clicks", 0),
                    spend=row.get("spend", 0),
                    spend_usd=row.get("spend_usd", row.get("spend", 0)),
                    media_installs=row.get("installs", 0),
                    media_conversions=row.get("conversions", 0),
                    ctr=row.get("ctr", 0),
                    cpc=row.get("cpc", 0),
                    cpm=row.get("cpm", 0),
                    cpi=row.get("cpi", 0),
                    source_row_hash=source_row_hash,
                    raw_row_json=row
                )

                do_nothing_stmt = insert_stmt.on_conflict_do_nothing(
                    index_elements=["source_row_hash"]
                )
                self.db.execute(do_nothing_stmt)
                saved_count += 1

        elif self.source_type == "mmp":
            for row in normalized_rows:
                source_row_hash = self._calculate_row_hash(row)

                # 转换 date
                row_date = row.get("date")
                if isinstance(row_date, str):
                    from datetime import datetime as dt
                    row_date = dt.strptime(row_date.split("T")[0], "%Y-%m-%d").date()

                insert_stmt = insert(FactMMPDaily).values(
                    run_id=run_id,
                    app_id=self.app_id,
                    mmp=self.platform,
                    date=row_date,
                    app_key=row.get("app_key", ""),
                    platform=row.get("platform", ""),
                    media_source=row.get("media_source", ""),
                    campaign_id=str(row.get("campaign_id", "")),
                    campaign_name=row.get("campaign_name", ""),
                    adset_id=str(row.get("adset_id", "")),
                    adset_name=row.get("adset_name", ""),
                    ad_id=str(row.get("ad_id", "")),
                    ad_name=row.get("ad_name", ""),
                    country=row.get("country", "ALL"),
                    attribution_model=row.get("attribution_model", "aggregate"),
                    signal_confidence=row.get("signal_confidence", "medium"),
                    currency=row.get("currency", "USD"),
                    attributed_installs=row.get("attributed_installs", 0),
                    registrations=row.get("registrations", 0),
                    payers=row.get("payers", 0),
                    cost=row.get("cost", 0),
                    cost_usd=row.get("cost_usd", row.get("cost", 0)),
                    revenue=row.get("revenue", 0),
                    revenue_usd=row.get("revenue_usd", row.get("revenue", 0)),
                    roi_d0=row.get("roi_d0", 0),
                    roi_d1=row.get("roi_d1", 0),
                    roi_d3=row.get("roi_d3", 0),
                    roi_d7=row.get("roi_d7", 0),
                    roi_d14=row.get("roi_d14", 0),
                    roi_d30=row.get("roi_d30", 0),
                    retention_d1=row.get("retention_d1", 0),
                    retention_d3=row.get("retention_d3", 0),
                    retention_d7=row.get("retention_d7", 0),
                    retention_d14=row.get("retention_d14", 0),
                    retention_d30=row.get("retention_d30", 0),
                    source_row_hash=source_row_hash,
                    raw_row_json=row
                )

                do_nothing_stmt = insert_stmt.on_conflict_do_nothing(
                    index_elements=["source_row_hash"]
                )
                self.db.execute(do_nothing_stmt)
                saved_count += 1

        self.db.flush()
        return saved_count

    def create_run_record(self,
                          operation: str,
                          report_type: str,
                          date_from: date,
                          date_to: date,
                          account_id: str = "",
                          app_key: str = "",
                          params_json: Dict = None,
                          executed_by: int = None) -> int:
        """创建连接器运行记录"""
        from app.models.data import ConnectorRun

        run = ConnectorRun(
            app_id=self.app_id,
            connector=self.platform,
            source_type=self.source_type,
            operation=operation,
            report_type=report_type,
            date_from=date_from,
            date_to=date_to,
            account_id=account_id,
            app_key=app_key,
            params_json=params_json or {},
            status="running",
            raw_row_count=0,
            normalized_row_count=0,
            executed_by=executed_by
        )

        self.db.add(run)
        self.db.flush()
        self.run_id = run.id
        return run.id

    def update_run_success(self, raw_row_count: int, normalized_row_count: int, adapter_response_json: Dict = None):
        """更新运行记录为成功状态"""
        if not self.run_id:
            return

        from app.models.data import ConnectorRun
        import json

        # 确保日期被正确序列化
        def date_serializer(obj):
            if isinstance(obj, date):
                return obj.isoformat()
            raise TypeError(f"Type {type(obj)} not serializable")

        safe_response = {}
        if adapter_response_json:
            # 使用自定义序列化器确保日期都被转换
            json_str = json.dumps(adapter_response_json, default=date_serializer)
            safe_response = json.loads(json_str)

        run = self.db.query(ConnectorRun).filter(ConnectorRun.id == self.run_id).first()
        if run:
            run.status = "success"
            run.raw_row_count = raw_row_count
            run.normalized_row_count = normalized_row_count
            run.adapter_response_json = safe_response
            self.db.commit()

    def update_run_failed(self, error_detail: str):
        """更新运行记录为失败状态"""
        if not self.run_id:
            return

        from app.models.data import ConnectorRun

        run = self.db.query(ConnectorRun).filter(ConnectorRun.id == self.run_id).first()
        if run:
            run.status = "failed"
            run.error_detail = error_detail
            self.db.commit()

    def execute_pull(self,
                     date_from: date,
                     date_to: date,
                     report_type: str = "campaign_daily",
                     account_id: str = "",
                     app_key: str = "",
                     executed_by: int = None,
                     **kwargs) -> Dict[str, Any]:
        """完整的拉取执行流程"""
        try:
            run_id = self.create_run_record(
                operation="pull",
                report_type=report_type,
                date_from=date_from,
                date_to=date_to,
                account_id=account_id,
                app_key=app_key,
                executed_by=executed_by,
                params_json=kwargs
            )

            if not self.auth():
                self.update_run_failed("Authentication failed")
                return {"success": False, "error": "Authentication failed"}

            raw_data = self.pull(date_from, date_to, report_type, **kwargs)
            raw_rows = raw_data.get("raw_rows", [])
            metadata = raw_data.get("metadata", {})

            if not raw_rows:
                self.update_run_success(0, 0, metadata)
                return {"success": True, "raw_rows": 0, "normalized_rows": 0}

            normalized_rows = self.normalize(raw_rows)

            if not self.validate(normalized_rows):
                logger.warning("Data validation failed, proceeding with caution")

            self.save_ods(raw_data, run_id)
            normalized_count = self.save_dwd(normalized_rows, run_id)

            self.db.commit()
            self.update_run_success(len(raw_rows), normalized_count, metadata)

            return {
                "success": True,
                "raw_rows": len(raw_rows),
                "normalized_rows": normalized_count,
                "run_id": run_id
            }

        except Exception as e:
            self.db.rollback()
            error_msg = f"Connector execution failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self.update_run_failed(error_msg)
            return {"success": False, "error": error_msg}

    def apply_action(self, action: str, entity_id: str, **params) -> Dict[str, Any]:
        """通用写动作分发器：把 Agent Tool Registry 的动作映射到具体连接器方法。

        设计目的（见 docs/AGENTIC_AD_PLATFORM_UPGRADE.md）：
        Agent Loop 的写工具统一调用此方法，而非具体连接器方法，从而与连接器解耦——
        Meta 账户恢复后只需在工厂把 "mock" 换回 "meta"，上层 Tool Registry 与
        意图引擎零改动。子类可重写以实现自定义语义；默认实现映射到标准 update_* 方法。

        支持的动作：
        - update_campaign_status / update_campaign_budget / update_adset_bid
        - rotate_creative（仅当连接器实现了该方法，如 MockMediaConnector）
        """
        if action == "update_campaign_status":
            return self.update_campaign_status(entity_id, params.get("status", "ACTIVE"))
        if action == "update_campaign_budget":
            return self.update_campaign_budget(entity_id, float(params.get("daily_budget", 0)))
        if action == "update_adset_bid":
            return self.update_adset_bid(entity_id, float(params.get("bid_amount", 1.0)))
        if action == "rotate_creative":
            fn = getattr(self, "rotate_creative", None)
            if fn is None:
                return {"success": False, "error": f"{self.platform} 连接器不支持 rotate_creative"}
            return fn(entity_id)
        return {"success": False, "error": f"不支持的动作: {action}"}
