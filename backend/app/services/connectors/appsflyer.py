from datetime import date, datetime
from typing import List, Dict, Any
import logging

from .base import BaseConnector

logger = logging.getLogger(__name__)


class AppsFlyerConnector(BaseConnector):
    """AppsFlyer MMP 归因连接器"""

    platform = "appsflyer"
    source_type = "mmp"
    rate_limit = 200  # 每小时 200 次请求

    def __init__(self, db, app_id, credentials):
        super().__init__(db, app_id, credentials)
        self.api_key = credentials.get("api_key")
        self.app_id_list = credentials.get("app_ids", [])

    def auth(self) -> bool:
        """认证 - API Key"""
        if not self.api_key:
            logger.warning("AppsFlyer api_key not provided, using mock mode")
        return True

    def pull(self,
             date_from: date,
             date_to: date,
             report_type: str = "attribution",
             **kwargs) -> Dict[str, Any]:
        """拉取归因数据"""
        from datetime import timedelta
        import random

        raw_rows = []
        current_date = date_from

        app_keys = kwargs.get("app_ids", self.app_id_list or ["com.game.app1", "com.game.app2"])
        media_sources = ["meta", "google", "tiktok", "apple_search_ads"]

        while current_date <= date_to:
            for app_key in app_keys:
                for media_source in media_sources:
                    installs = random.randint(50, 1000)
                    registrations = int(installs * random.uniform(0.6, 0.9))
                    payers = int(registrations * random.uniform(0.1, 0.3))
                    cost = random.uniform(500, 10000)
                    revenue = random.uniform(300, 20000)

                    row = {
                        "date": current_date.strftime("%Y-%m-%d"),
                        "app_id": app_key,
                        "media_source": media_source,
                        "campaign_id": f"{media_source}_camp_{random.randint(1000, 9999)}",
                        "campaign": f"{media_source}_Campaign",
                        "adset_id": f"{media_source}_adset_{random.randint(1000, 9999)}",
                        "adset": f"{media_source}_Adset",
                        "ad_id": f"{media_source}_ad_{random.randint(1000, 9999)}",
                        "ad": f"{media_source}_Ad",
                        "country_code": random.choice(["US", "GB", "CA", "AU", "DE"]),
                        "platform": random.choice(["android", "ios"]),
                        "attributed_installs": installs,
                        "registrations": registrations,
                        "payers": payers,
                        "cost": round(cost, 2),
                        "revenue": round(revenue, 2),
                        "roi_d0": round(revenue / cost if cost > 0 else 0, 6),
                        "roi_d1": round(revenue * 1.2 / cost if cost > 0 else 0, 6),
                        "roi_d3": round(revenue * 1.5 / cost if cost > 0 else 0, 6),
                        "roi_d7": round(revenue * 1.8 / cost if cost > 0 else 0, 6),
                        "roi_d14": round(revenue * 2.0 / cost if cost > 0 else 0, 6),
                        "roi_d30": round(revenue * 2.3 / cost if cost > 0 else 0, 6),
                        "retention_d1": round(random.uniform(0.3, 0.6), 6),
                        "retention_d3": round(random.uniform(0.15, 0.35), 6),
                        "retention_d7": round(random.uniform(0.08, 0.2), 6),
                        "retention_d14": round(random.uniform(0.04, 0.12), 6),
                        "retention_d30": round(random.uniform(0.02, 0.08), 6),
                        "currency": "USD",
                        "_pulled_at": datetime.utcnow().isoformat(),
                    }
                    raw_rows.append(row)

            current_date += timedelta(days=1)

        return {
            "raw_rows": raw_rows,
            "metadata": {
                "total_rows": len(raw_rows),
                "currency": "USD",
                "is_complete": True,
                "rate_limit_remaining": 200,
                "next_page_token": None,
                "report_type": report_type,
                "date_from": date_from,
                "date_to": date_to,
                "mode": "mock",
            }
        }

    def normalize(self, raw_rows: List[Dict]) -> List[Dict]:
        """字段标准化"""
        normalized_rows = []

        for row in raw_rows:
            cost = self._safe_float(row.get("cost", 0))
            revenue = self._safe_float(row.get("revenue", 0))

            normalized = {
                "date": row.get("date"),
                "app_key": row.get("app_id", ""),
                "platform": row.get("platform", ""),
                "media_source": row.get("media_source", ""),
                "campaign_id": row.get("campaign_id", ""),
                "campaign_name": row.get("campaign", ""),
                "adset_id": row.get("adset_id", ""),
                "adset_name": row.get("adset", ""),
                "ad_id": row.get("ad_id", ""),
                "ad_name": row.get("ad", ""),
                "country": row.get("country_code", "ALL"),
                "attribution_model": "aggregate",
                "signal_confidence": "high" if self._safe_int(row.get("attributed_installs", 0)) > 100 else "medium",
                "currency": row.get("currency", "USD"),
                "attributed_installs": self._safe_int(row.get("attributed_installs", 0)),
                "registrations": self._safe_int(row.get("registrations", 0)),
                "payers": self._safe_int(row.get("payers", 0)),
                "cost": cost,
                "cost_usd": cost,
                "revenue": revenue,
                "revenue_usd": revenue,
                "roi_d0": self._safe_float(row.get("roi_d0", 0)),
                "roi_d1": self._safe_float(row.get("roi_d1", 0)),
                "roi_d3": self._safe_float(row.get("roi_d3", 0)),
                "roi_d7": self._safe_float(row.get("roi_d7", 0)),
                "roi_d14": self._safe_float(row.get("roi_d14", 0)),
                "roi_d30": self._safe_float(row.get("roi_d30", 0)),
                "retention_d1": self._safe_float(row.get("retention_d1", 0)),
                "retention_d3": self._safe_float(row.get("retention_d3", 0)),
                "retention_d7": self._safe_float(row.get("retention_d7", 0)),
                "retention_d14": self._safe_float(row.get("retention_d14", 0)),
                "retention_d30": self._safe_float(row.get("retention_d30", 0)),
            }

            normalized_rows.append(normalized)

        return normalized_rows

    def _safe_int(self, value) -> int:
        try:
            return int(value) if value is not None else 0
        except (ValueError, TypeError):
            return 0

    def _safe_float(self, value) -> float:
        try:
            return float(value) if value is not None else 0.0
        except (ValueError, TypeError):
            return 0.0
