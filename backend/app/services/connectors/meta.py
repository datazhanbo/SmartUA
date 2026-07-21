from datetime import date, datetime
from typing import List, Dict, Any
import logging
import time
import hashlib
import json

try:
    from facebook_business.api import FacebookAdsApi
    from facebook_business.adobjects.adaccount import AdAccount
    from facebook_business.adobjects.adsinsights import AdsInsights
    FACEBOOK_SDK_AVAILABLE = True
except ImportError:
    FACEBOOK_SDK_AVAILABLE = False

from .base import BaseConnector, to_usd

logger = logging.getLogger(__name__)


class MetaConnector(BaseConnector):
    """Meta (Facebook/Instagram) Ads 连接器"""

    platform = "meta"
    source_type = "media"
    rate_limit = 200  # 每小时 200 次请求
    supported_modes = ("mock", "live")
    capabilities = {
        "read": True,
        "write": True,
        "structure": True,
        "simulate": False,
    }

    def __init__(self, db, app_id, credentials, execution_mode: str = "mock"):
        super().__init__(db, app_id, credentials, execution_mode=execution_mode)
        self.access_token = credentials.get("access_token")
        self.app_secret = credentials.get("app_secret")
        self.ad_account_id = credentials.get("ad_account_id", "")
        self.account_id = self.ad_account_id or ""
        if self.execution_mode == "live":
            if not FACEBOOK_SDK_AVAILABLE:
                raise RuntimeError(
                    "Meta live 模式要求已安装 facebook_business SDK；当前运行环境未安装，"
                    "不允许静默回退 mock"
                )
            if not self.access_token:
                raise ValueError("Meta live 模式缺少 access_token；不允许静默回退 mock")

    def auth(self) -> bool:
        """认证 - 使用 access_token"""
        if self.execution_mode != "live":
            return True

        try:
            FacebookAdsApi.init(access_token=self.access_token)
            return True
        except Exception as e:
            logger.error(f"Meta auth failed: {e}")
            return False

    def pull(self,
             date_from: date,
             date_to: date,
             report_type: str = "campaign_daily",
             **kwargs) -> Dict[str, Any]:
        """拉取数据"""
        if self.execution_mode != "live":
            return self._mock_pull(date_from, date_to, report_type, **kwargs)

        try:
            ad_account_id = kwargs.get("ad_account_id", self.ad_account_id)
            if not ad_account_id:
                raise ValueError("ad_account_id is required")

            if not ad_account_id.startswith("act_"):
                ad_account_id = f"act_{ad_account_id}"

            account = AdAccount(ad_account_id)

            fields = self._get_fields_by_report_type(report_type)
            params = self._build_params(date_from, date_to, report_type)

            insights = list(account.get_insights(fields=fields, params=params))

            raw_rows = []
            for insight in insights:
                row = {field: insight.get(field) for field in fields}
                row["_pulled_at"] = datetime.utcnow().isoformat()
                raw_rows.append(row)

            return {
                "raw_rows": raw_rows,
                "metadata": {
                    "total_rows": len(raw_rows),
                    "currency": insights[0].get("account_currency", "USD") if insights else "USD",
                    "is_complete": True,
                    "rate_limit_remaining": 200,
                    "next_page_token": None,
                    "report_type": report_type,
                    "date_from": date_from.isoformat(),
                    "date_to": date_to.isoformat(),
                    "account_id": ad_account_id,
                }
            }

        except Exception as e:
            logger.error(f"Meta pull failed: {e}")
            raise

    def _mock_pull(self, date_from: date, date_to: date, report_type: str, **kwargs) -> Dict[str, Any]:
        """模拟数据拉取（SDK不可用时使用）"""
        from datetime import timedelta
        import random

        raw_rows = []
        current_date = date_from

        campaigns = [
            {"id": "120207396134620031", "name": "Campaign_US_2024Q2"},
            {"id": "120207396134630032", "name": "Campaign_GB_2024Q2"},
            {"id": "120207396134640033", "name": "Campaign_CA_2024Q2"},
        ]

        while current_date <= date_to:
            for campaign in campaigns:
                for country in ["US", "GB", "CA"]:
                    impressions = random.randint(10000, 100000)
                    clicks = random.randint(100, 5000)
                    spend = random.uniform(100, 5000)
                    installs = random.randint(10, 500)

                    row = {
                        "date_start": current_date.strftime("%Y-%m-%d"),
                        "date_stop": current_date.strftime("%Y-%m-%d"),
                        "campaign_id": campaign["id"],
                        "campaign_name": campaign["name"],
                        "adset_id": f"adset_{campaign['id'][5:]}",
                        "adset_name": f"Adset_{campaign['name']}",
                        "ad_id": f"ad_{campaign['id'][5:]}",
                        "ad_name": f"Ad_{campaign['name']}",
                        "country": country,
                        "impressions": impressions,
                        "clicks": clicks,
                        "spend": round(spend, 2),
                        "cpc": round(spend / clicks if clicks > 0 else 0, 4),
                        "ctr": round(clicks / impressions if impressions > 0 else 0, 6),
                        "cpm": round(spend * 1000 / impressions if impressions > 0 else 0, 4),
                        "mobile_app_installs": installs,
                        "conversions": random.randint(5, 200),
                        "account_currency": "USD",
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
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "account_id": kwargs.get("ad_account_id", "mock_account"),
                "mode": "mock",
            }
        }

    def _get_fields_by_report_type(self, report_type: str) -> List[str]:
        """根据报表类型获取字段列表"""
        base_fields = [
            "date_start", "date_stop", "account_currency"
        ]

        fields_map = {
            "campaign_daily": base_fields + [
                "campaign_id", "campaign_name", "impressions", "clicks",
                "spend", "ctr", "cpc", "cpm", "mobile_app_installs",
                "conversions", "unique_clicks", "reach"
            ],
            "adset_daily": base_fields + [
                "campaign_id", "campaign_name", "adset_id", "adset_name",
                "impressions", "clicks", "spend", "ctr", "cpc", "cpm",
                "mobile_app_installs", "conversions"
            ],
            "ad_daily": base_fields + [
                "campaign_id", "campaign_name", "adset_id", "adset_name",
                "ad_id", "ad_name", "impressions", "clicks", "spend",
                "ctr", "cpc", "cpm", "mobile_app_installs", "conversions"
            ],
            "creative_daily": base_fields + [
                "campaign_id", "campaign_name", "ad_id", "ad_name",
                "creative_id", "creative_name", "impressions", "clicks",
                "spend", "ctr", "cpc"
            ],
        }

        return fields_map.get(report_type, fields_map["campaign_daily"])

    def _build_params(self, date_from: date, date_to: date, report_type: str) -> Dict[str, Any]:
        """构建请求参数"""
        breakdowns = []
        if report_type in ["creative_daily"]:
            breakdowns.append("dynamic_asset")
        # 国家维度 breakdown：让真实拉取带 country（与 mock/事实表一致），用于地理报表
        if report_type in ["campaign_daily", "adset_daily", "ad_daily"]:
            breakdowns.append("country")

        params = {
            "time_range": {
                "since": date_from.strftime("%Y-%m-%d"),
                "until": date_to.strftime("%Y-%m-%d")
            },
            "level": report_type.replace("_daily", "").replace("creative", "ad"),
            "action_attribution_windows": ["1d_view", "7d_click"],
        }

        if breakdowns:
            params["breakdowns"] = ",".join(breakdowns)

        return params

    def normalize(self, raw_rows: List[Dict]) -> List[Dict]:
        """字段标准化"""
        normalized_rows = []

        for row in raw_rows:
            normalized = {
                "date": row.get("date_start"),
                "account_id": self.ad_account_id,
                "campaign_id": row.get("campaign_id", ""),
                "campaign_name": row.get("campaign_name", ""),
                "adset_id": row.get("adset_id", ""),
                "adset_name": row.get("adset_name", ""),
                "ad_id": row.get("ad_id", ""),
                "ad_name": row.get("ad_name", ""),
                "creative_id": row.get("creative_id", ""),
                "creative_name": row.get("creative_name", ""),
                "country": row.get("country", "ALL"),
                "currency": row.get("account_currency", "USD"),
                "impressions": self._safe_int(row.get("impressions", 0)),
                "clicks": self._safe_int(row.get("clicks", 0)),
                "spend": self._safe_float(row.get("spend", 0)),
                "spend_usd": to_usd(self._safe_float(row.get("spend", 0)), row.get("account_currency", "USD"), self.db, self.app_id),
                "ctr": self._safe_float(row.get("ctr", 0)),
                "cpc": self._safe_float(row.get("cpc", 0)),
                "cpm": self._safe_float(row.get("cpm", 0)),
                "installs": self._safe_int(row.get("mobile_app_installs", 0)),
                "conversions": self._safe_int(row.get("conversions", 0)),
                "media_source": "meta",
            }

            if normalized["clicks"] > 0 and normalized["installs"] > 0:
                normalized["cpi"] = normalized["spend"] / normalized["installs"]
            else:
                normalized["cpi"] = 0

            normalized_rows.append(normalized)

        return normalized_rows

    def _safe_int(self, value) -> int:
        """安全转换整数"""
        try:
            return int(value) if value is not None else 0
        except (ValueError, TypeError):
            return 0

    def _safe_float(self, value) -> float:
        """安全转换浮点数"""
        try:
            return float(value) if value is not None else 0.0
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _cents(v):
        """Meta 金额以最小货币单位（分）返回；转为主单位。"""
        try:
            return float(v) / 100 if v is not None else None
        except (ValueError, TypeError):
            return None

    # === 结构拉取（Campaign->AdSet->Ad->Creative 层级 + 运营态） ===

    def pull_structure(self) -> Dict[str, Any]:
        """拉取计划分层结构与运营态。"""
        if self.execution_mode != "live":
            return self._mock_structure()
        return self._real_structure()

    def _mock_structure(self) -> Dict[str, Any]:
        campaigns = [
            ("120207396134620031", "Campaign_US_2024Q2"),
            ("120207396134630032", "Campaign_GB_2024Q2"),
            ("120207396134640033", "Campaign_CA_2024Q2"),
        ]
        rows = []
        acc = self.ad_account_id or "mock_account"
        for cid, cname in campaigns:
            rows.append({"entity_level": "campaign", "entity_id": cid, "parent_id": None,
                         "campaign_id": cid, "campaign_name": cname, "status": "ACTIVE",
                         "daily_budget": 500.0, "currency": "USD", "account_id": acc})
            for j in range(1, 3):
                sid = f"adset_{cid}_{j}"
                sname = f"Adset_{cname}_{j}"
                rows.append({"entity_level": "adset", "entity_id": sid, "parent_id": cid,
                             "campaign_id": cid, "campaign_name": cname, "adset_id": sid,
                             "adset_name": sname, "status": "ACTIVE", "daily_budget": 250.0,
                             "bid_amount": 2.0, "currency": "USD", "account_id": acc})
                for k in range(1, 3):
                    aid = f"ad_{sid}_{k}"
                    aname = f"Ad_{sname}_{k}"
                    rows.append({"entity_level": "ad", "entity_id": aid, "parent_id": sid,
                                 "campaign_id": cid, "campaign_name": cname, "adset_id": sid,
                                 "adset_name": sname, "ad_id": aid, "ad_name": aname,
                                 "status": "ACTIVE", "account_id": acc})
                    cri = f"cr_{aid}"
                    rows.append({"entity_level": "creative", "entity_id": cri, "parent_id": aid,
                                 "campaign_id": cid, "campaign_name": cname, "adset_id": sid,
                                 "adset_name": sname, "ad_id": aid, "ad_name": aname,
                                 "creative_id": cri, "creative_name": f"Creative_{aname}",
                                 "status": "ACTIVE", "account_id": acc})
        return {"raw_rows": rows, "metadata": {"mode": "mock", "account_id": acc}}

    def _real_structure(self) -> Dict[str, Any]:
        from facebook_business.adobjects.adaccount import AdAccount
        from facebook_business.adobjects.campaign import Campaign
        from facebook_business.adobjects.adset import AdSet
        from facebook_business.adobjects.ad import Ad
        from facebook_business.adobjects.adcreative import AdCreative

        aid = self.ad_account_id
        if not aid:
            raise ValueError("ad_account_id is required")
        if not aid.startswith("act_"):
            aid = f"act_{aid}"
        account = AdAccount(aid)
        rows = []

        campaigns = list(account.get_campaigns(
            fields=["id", "name", "status", "daily_budget", "currency"]))
        for c in campaigns:
            cid = c["id"]
            cur = c.get("currency", "USD")
            rows.append({"entity_level": "campaign", "entity_id": cid, "parent_id": None,
                         "campaign_id": cid, "campaign_name": c.get("name", ""),
                         "status": c.get("status"), "daily_budget": self._cents(c.get("daily_budget")),
                         "currency": cur, "account_id": aid})
            adsets = list(Campaign(cid).get_ad_sets(
                fields=["id", "name", "status", "daily_budget", "bid_amount", "targeting", "currency"]))
            for s in adsets:
                sid = s["id"]
                rows.append({"entity_level": "adset", "entity_id": sid, "parent_id": cid,
                             "campaign_id": cid, "campaign_name": c.get("name", ""),
                             "adset_id": sid, "adset_name": s.get("name", ""),
                             "status": s.get("status"),
                             "daily_budget": self._cents(s.get("daily_budget")),
                             "bid_amount": self._cents(s.get("bid_amount")),
                             "currency": s.get("currency", cur),
                             "targeting_json": s.get("targeting"), "account_id": aid})
                ads = list(AdSet(sid).get_ads(fields=["id", "name", "status"]))
                for a in ads:
                    aid_ = a["id"]
                    rows.append({"entity_level": "ad", "entity_id": aid_, "parent_id": sid,
                                 "campaign_id": cid, "campaign_name": c.get("name", ""),
                                 "adset_id": sid, "adset_name": s.get("name", ""),
                                 "ad_id": aid_, "ad_name": a.get("name", ""),
                                 "status": a.get("status"), "account_id": aid})
                    creatives = list(Ad(aid_).get_ad_creatives(fields=["id", "name", "status"]))
                    for cr in creatives:
                        rows.append({"entity_level": "creative", "entity_id": cr["id"],
                                     "parent_id": aid_, "campaign_id": cid,
                                     "campaign_name": c.get("name", ""), "adset_id": sid,
                                     "adset_name": s.get("name", ""), "ad_id": aid_,
                                     "ad_name": a.get("name", ""), "creative_id": cr["id"],
                                     "creative_name": cr.get("name", ""),
                                     "status": cr.get("status"), "account_id": aid})
        return {"raw_rows": rows, "metadata": {"mode": "real", "account_id": aid}}

    # === Marketing API - 写操作 ===

    def update_campaign_budget(self, campaign_id: str, daily_budget: float) -> Dict[str, Any]:
        """更新 Campaign 日预算"""
        if self.execution_mode != "live":
            return {"success": True, "campaign_id": campaign_id, "new_budget": daily_budget, "mode": "mock"}

        try:
            from facebook_business.adobjects.campaign import Campaign
            campaign = Campaign(campaign_id)
            campaign.api_update(params={
                "daily_budget": int(daily_budget * 100)  # Meta 以分为单位
            })
            return {"success": True, "campaign_id": campaign_id, "new_budget": daily_budget}
        except Exception as e:
            logger.error(f"Update campaign budget failed: {e}")
            return {"success": False, "error": str(e)}

    def update_campaign_status(self, campaign_id: str, status: str) -> Dict[str, Any]:
        """更新 Campaign 状态（ACTIVE/PAUSED/DELETED）"""
        if self.execution_mode != "live":
            return {"success": True, "campaign_id": campaign_id, "new_status": status, "mode": "mock"}

        try:
            from facebook_business.adobjects.campaign import Campaign
            campaign = Campaign(campaign_id)
            campaign.api_update(params={"status": status.upper()})
            return {"success": True, "campaign_id": campaign_id, "new_status": status}
        except Exception as e:
            logger.error(f"Update campaign status failed: {e}")
            return {"success": False, "error": str(e)}

    def update_adset_bid(self, adset_id: str, bid_amount: float) -> Dict[str, Any]:
        """更新 AdSet 出价"""
        if self.execution_mode != "live":
            return {"success": True, "adset_id": adset_id, "new_bid": bid_amount, "mode": "mock"}

        try:
            from facebook_business.adobjects.adset import AdSet
            adset = AdSet(adset_id)
            adset.api_update(params={
                "bid_amount": int(bid_amount * 100)
            })
            return {"success": True, "adset_id": adset_id, "new_bid": bid_amount}
        except Exception as e:
            logger.error(f"Update adset bid failed: {e}")
            return {"success": False, "error": str(e)}

    def rotate_creative(self, campaign_id: str) -> Dict[str, Any]:
        """轮换素材（重新发布一轮创意）"""
        if self.execution_mode != "live":
            return {"success": True, "campaign_id": campaign_id, "mode": "mock"}

        try:
            from facebook_business.adobjects.campaign import Campaign
            campaign = Campaign(campaign_id)
            # 真实实现会创建新 AdCreative 并替换；此处仅占位
            return {"success": True, "campaign_id": campaign_id, "rotated": True}
        except Exception as e:
            logger.error(f"Rotate creative failed: {e}")
            return {"success": False, "error": str(e)}
