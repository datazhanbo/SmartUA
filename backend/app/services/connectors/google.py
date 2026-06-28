from datetime import date, datetime
from typing import List, Dict, Any
import logging

from .base import BaseConnector

logger = logging.getLogger(__name__)


class GoogleAdsConnector(BaseConnector):
    """Google Ads 连接器"""

    platform = "google"
    source_type = "media"
    rate_limit = 1000  # 每小时 1000 次请求

    def __init__(self, db, app_id, credentials):
        super().__init__(db, app_id, credentials)
        self.client_id = credentials.get("client_id")
        self.client_secret = credentials.get("client_secret")
        self.refresh_token = credentials.get("refresh_token")
        self.developer_token = credentials.get("developer_token")
        self.customer_id = credentials.get("customer_id", "")

    def auth(self) -> bool:
        """认证 - OAuth2"""
        if not all([self.client_id, self.client_secret, self.refresh_token, self.developer_token]):
            logger.warning("Google Ads credentials incomplete, using mock mode")
            return True

        try:
            # 实际项目中使用 google-ads 库
            logger.info("Google Ads auth successful (mock)")
            return True
        except Exception as e:
            logger.error(f"Google auth failed: {e}")
            return False

    def pull(self,
             date_from: date,
             date_to: date,
             report_type: str = "campaign_daily",
             **kwargs) -> Dict[str, Any]:
        """拉取数据"""
        from datetime import timedelta
        import random

        raw_rows = []
        current_date = date_from

        campaigns = [
            {"id": "14280694219", "name": "Google_US_App_Install"},
            {"id": "14280694220", "name": "Google_GB_App_Install"},
            {"id": "14280694221", "name": "Google_CA_App_Install"},
        ]

        while current_date <= date_to:
            for campaign in campaigns:
                for country in ["US", "GB", "CA"]:
                    impressions = random.randint(5000, 80000)
                    clicks = random.randint(50, 4000)
                    cost_micros = random.randint(100000000, 5000000000)  # 微美元
                    spend = cost_micros / 1000000
                    installs = random.randint(5, 400)

                    row = {
                        "segments.date": current_date.strftime("%Y-%m-%d"),
                        "campaign.id": campaign["id"],
                        "campaign.name": campaign["name"],
                        "ad_group.id": f"gid_{campaign['id']}",
                        "ad_group.name": f"AdGroup_{campaign['name']}",
                        "ad_group_ad.ad.id": f"gad_{campaign['id']}",
                        "ad_group_ad.ad.name": f"GAd_{campaign['name']}",
                        "customer.id": kwargs.get("customer_id", self.customer_id),
                        "metrics.impressions": impressions,
                        "metrics.clicks": clicks,
                        "metrics.cost_micros": cost_micros,
                        "metrics.ctr": clicks / impressions if impressions > 0 else 0,
                        "metrics.average_cpc": spend / clicks if clicks > 0 else 0,
                        "metrics.average_cpm": spend * 1000 / impressions if impressions > 0 else 0,
                        "metrics.installs": installs,
                        "metrics.conversions": random.randint(3, 150),
                        "customer.currency_code": "USD",
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
                "rate_limit_remaining": 1000,
                "next_page_token": None,
                "report_type": report_type,
                "date_from": date_from,
                "date_to": date_to,
                "customer_id": kwargs.get("customer_id", self.customer_id),
                "mode": "mock",
            }
        }

    def normalize(self, raw_rows: List[Dict]) -> List[Dict]:
        """字段标准化"""
        normalized_rows = []

        for row in raw_rows:
            spend = self._safe_float(row.get("metrics.cost_micros", 0)) / 1000000

            normalized = {
                "date": row.get("segments.date"),
                "account_id": self.customer_id,
                "campaign_id": row.get("campaign.id", ""),
                "campaign_name": row.get("campaign.name", ""),
                "adset_id": row.get("ad_group.id", ""),
                "adset_name": row.get("ad_group.name", ""),
                "ad_id": row.get("ad_group_ad.ad.id", ""),
                "ad_name": row.get("ad_group_ad.ad.name", ""),
                "country": row.get("country", "ALL"),
                "currency": row.get("customer.currency_code", "USD"),
                "impressions": self._safe_int(row.get("metrics.impressions", 0)),
                "clicks": self._safe_int(row.get("metrics.clicks", 0)),
                "spend": spend,
                "spend_usd": spend,
                "ctr": self._safe_float(row.get("metrics.ctr", 0)),
                "cpc": self._safe_float(row.get("metrics.average_cpc", 0)),
                "cpm": self._safe_float(row.get("metrics.average_cpm", 0)),
                "installs": self._safe_int(row.get("metrics.installs", 0)),
                "conversions": self._safe_int(row.get("metrics.conversions", 0)),
                "media_source": "google",
            }

            if normalized["installs"] > 0:
                normalized["cpi"] = spend / normalized["installs"]
            else:
                normalized["cpi"] = 0

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
