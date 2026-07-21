from datetime import date, datetime, timedelta
from typing import List, Dict, Any
import logging
import random

from .base import BaseConnector

logger = logging.getLogger(__name__)


class TikTokConnector(BaseConnector):
    """TikTok for Business 连接器（Phase 1.1：mock 专用，真实 API 未实现前拒绝 live）。"""

    platform = "tiktok"
    source_type = "media"
    rate_limit = 600  # TikTok API 限流（每用户分钟级）
    supported_modes = ("mock",)
    capabilities = {
        "read": True,
        "write": False,
        "structure": False,
        "simulate": False,
    }

    def __init__(self, db, app_id, credentials, execution_mode: str = "mock"):
        super().__init__(db, app_id, credentials, execution_mode=execution_mode)
        self.access_token = credentials.get("access_token")
        self.app_id_tt = credentials.get("app_id")
        self.advertiser_id = credentials.get("advertiser_id", "")
        self.secret = credentials.get("secret")
        self.account_id = self.advertiser_id or ""

    def auth(self) -> bool:
        return True

    def pull(self,
             date_from: date,
             date_to: date,
             report_type: str = "campaign_daily",
             **kwargs) -> Dict[str, Any]:
        """拉取数据（Mock 待命：真实路径留作接入 TikTok Marketing API）。"""
        raw_rows = []
        current_date = date_from
        campaigns = [
            {"id": "tk_720001", "name": "TikTok_US_App_Install"},
            {"id": "tk_720002", "name": "TikTok_GB_App_Install"},
            {"id": "tk_720003", "name": "TikTok_JP_App_Install"},
        ]
        while current_date <= date_to:
            for campaign in campaigns:
                for country in ["US", "GB", "JP"]:
                    impressions = random.randint(8000, 90000)
                    clicks = random.randint(80, 5000)
                    spend = random.uniform(80, 4000)
                    installs = random.randint(8, 450)
                    row = {
                        "stat_time_day": current_date.strftime("%Y-%m-%d"),
                        "advertiser_id": self.advertiser_id,
                        "campaign_id": campaign["id"],
                        "campaign_name": campaign["name"],
                        "adgroup_id": f"tg_{campaign['id']}",
                        "adgroup_name": f"AdGroup_{campaign['name']}",
                        "ad_id": f"ta_{campaign['id']}",
                        "ad_name": f"Ad_{campaign['name']}",
                        "country": country,
                        "impressions": impressions,
                        "clicks": clicks,
                        "spend": round(spend, 2),
                        "ctr": round(clicks / impressions, 6) if impressions else 0,
                        "cpc": round(spend / clicks, 4) if clicks else 0,
                        "cpm": round(spend * 1000 / impressions, 4) if impressions else 0,
                        "installs": installs,
                        "conversions": random.randint(5, 180),
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
                "rate_limit_remaining": self.rate_limit,
                "next_page_token": None,
                "report_type": report_type,
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "account_id": self.advertiser_id,
                "mode": "mock",
            },
        }

    def normalize(self, raw_rows: List[Dict]) -> List[Dict]:
        """字段标准化（与 Meta/Google 对齐，便于统一写入 FactMediaDaily）。"""
        normalized_rows = []
        for row in raw_rows:
            spend = self._safe_float(row.get("spend", 0))
            installs = self._safe_int(row.get("installs", 0))
            normalized = {
                "date": row.get("stat_time_day"),
                "account_id": self.advertiser_id,
                "campaign_id": row.get("campaign_id", ""),
                "campaign_name": row.get("campaign_name", ""),
                "adset_id": row.get("adgroup_id", ""),
                "adset_name": row.get("adgroup_name", ""),
                "ad_id": row.get("ad_id", ""),
                "ad_name": row.get("ad_name", ""),
                "country": row.get("country", "ALL"),
                "currency": row.get("currency", "USD"),
                "impressions": self._safe_int(row.get("impressions", 0)),
                "clicks": self._safe_int(row.get("clicks", 0)),
                "spend": spend,
                "spend_usd": spend,
                "ctr": self._safe_float(row.get("ctr", 0)),
                "cpc": self._safe_float(row.get("cpc", 0)),
                "cpm": self._safe_float(row.get("cpm", 0)),
                "installs": installs,
                "conversions": self._safe_int(row.get("conversions", 0)),
                "media_source": "tiktok",
            }
            normalized["cpi"] = spend / installs if installs > 0 else 0
            normalized_rows.append(normalized)
        return normalized_rows

    # === Marketing API - 写操作（Mock 待命） ===
    def update_campaign_status(self, campaign_id: str, status: str) -> Dict[str, Any]:
        return {"success": True, "campaign_id": campaign_id,
                "new_status": status, "mode": "mock"}

    def update_campaign_budget(self, campaign_id: str, daily_budget: float) -> Dict[str, Any]:
        return {"success": True, "campaign_id": campaign_id,
                "new_budget": daily_budget, "mode": "mock"}

    def update_adset_bid(self, adset_id: str, bid_amount: float) -> Dict[str, Any]:
        return {"success": True, "adset_id": adset_id,
                "new_bid": bid_amount, "mode": "mock"}

    def rotate_creative(self, campaign_id: str) -> Dict[str, Any]:
        return {"success": True, "campaign_id": campaign_id, "mode": "mock"}

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
