import logging
from datetime import date, datetime, timedelta
from typing import List, Dict, Any, Optional

from .base import BaseConnector, ImpactEstimation, to_usd

logger = logging.getLogger(__name__)

# 真实调用依赖 google-ads SDK（底层 grpcio）。沙箱无法安装 grpcio 时，凭证不全则自动回退 mock，
# 系统照常运行；在能装 google-ads 的环境（笔记本/生产/CI）里即为真实 API 链路。


class GoogleAdsConnector(BaseConnector):
    """Google Ads 连接器（真实 API + mock 数据土壤）

    Phase 1.1：mock 与 live 严格隔离。execution_mode='live' 但缺凭证/SDK 会 fail-closed
    抛错，绝不静默切换到 mock；execution_mode='mock' 使用本地占位数据用于开发/测试。
    """

    platform = "google"
    source_type = "media"
    rate_limit = 1000  # 每小时 1000 次请求
    supported_modes = ("mock", "live")
    capabilities = {
        "read": True,
        "write": True,
        "structure": True,
        "simulate": False,
    }

    def __init__(self, db, app_id, credentials, execution_mode: str = "mock"):
        super().__init__(db, app_id, credentials, execution_mode=execution_mode)
        self.client_id = credentials.get("client_id")
        self.client_secret = credentials.get("client_secret")
        self.refresh_token = credentials.get("refresh_token")
        self.developer_token = credentials.get("developer_token")
        self.customer_id = (credentials.get("customer_id") or "").replace("-", "")
        self.login_customer_id = (credentials.get("login_customer_id") or self.customer_id or "").replace("-", "")
        self.account_id = self.customer_id or ""
        self._sdk_available = self._sdk_available()
        if self.execution_mode == "live":
            missing = [k for k, v in {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "developer_token": self.developer_token,
                "customer_id": self.customer_id,
            }.items() if not v]
            if missing:
                raise ValueError(
                    f"Google Ads live 模式缺少凭证字段: {missing}；不允许静默回退 mock"
                )
            if not self._sdk_available:
                raise RuntimeError(
                    "Google Ads live 模式要求已安装 google-ads SDK；当前运行环境未安装，"
                    "不允许静默回退 mock"
                )
            self._is_mock = False
        else:
            # execution_mode == "mock"
            self._is_mock = True

    # ---------------- 真实客户端（懒加载 SDK） ----------------
    @staticmethod
    def _sdk_available() -> bool:
        """google-ads SDK 是否可用；不可用时连接器整体回退 mock，避免真实路径入口崩溃。"""
        try:
            import google.ads.googleads  # noqa: F401
            return True
        except Exception:
            return False

    def _real_client(self):
        """构建 google-ads GoogleAdsClient；SDK 未安装时抛 ImportError（由调用方兜底）。"""
        from google.ads.googleads.client import GoogleAdsClient
        return GoogleAdsClient.load_from_dict({
            "developer_token": self.developer_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "login_customer_id": self.login_customer_id,
            "use_proto_plus": True,
        })

    # ---------------- 认证 ----------------
    def auth(self) -> bool:
        if self._is_mock:
            return True
        try:
            client = self._real_client()
            client.get_service("GoogleAdsService")  # 结构校验，不发起网络
            return True
        except Exception as e:
            logger.error(f"Google Ads auth failed: {e}")
            return False

    # ---------------- 拉取（真实 / mock） ----------------
    def pull(self, date_from: date, date_to: date, report_type: str = "campaign_daily", **kwargs) -> Dict[str, Any]:
        if self._is_mock:
            return self._mock_pull(date_from, date_to, report_type, **kwargs)
        return self._real_pull(date_from, date_to, report_type, **kwargs)

    def _real_pull(self, date_from, date_to, report_type, **kwargs):
        client = self._real_client()
        ga_service = client.get_service("GoogleAdsService")
        start = date_from.strftime("%Y-%m-%d")
        end = date_to.strftime("%Y-%m-%d")
        customer_id = kwargs.get("customer_id", self.customer_id)
        query = f"""
            SELECT
                segments.date,
                campaign.id, campaign.name, campaign.status,
                ad_group.id, ad_group.name,
                ad_group_ad.ad.id, ad_group_ad.ad.name,
                customer.id, customer.currency_code,
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions, metrics.ctr, metrics.average_cpc, metrics.average_cpm
            FROM campaign
            WHERE segments.date BETWEEN '{start}' AND '{end}'
        """
        raw_rows = []
        response = ga_service.search(customer_id=customer_id, query=query)
        for row in response:
            raw_rows.append({
                "segments.date": row.segments.date,
                "campaign.id": str(row.campaign.id),
                "campaign.name": row.campaign.name,
                "campaign.status": row.campaign.status.name,
                "ad_group.id": str(row.ad_group.id),
                "ad_group.name": row.ad_group.name,
                "ad_group_ad.ad.id": str(row.ad_group_ad.ad.id),
                "ad_group_ad.ad.name": row.ad_group_ad.ad.name,
                "customer.id": customer_id,
                "customer.currency_code": row.customer.currency_code,
                "metrics.impressions": int(row.metrics.impressions),
                "metrics.clicks": int(row.metrics.clicks),
                "metrics.cost_micros": int(row.metrics.cost_micros),
                "metrics.conversions": float(row.metrics.conversions),
                "metrics.ctr": float(row.metrics.ctr),
                "metrics.average_cpc": float(row.metrics.average_cpc),
                "metrics.average_cpm": float(row.metrics.average_cpm),
                "_pulled_at": datetime.utcnow().isoformat(),
            })
        return {
            "raw_rows": raw_rows,
            "metadata": {
                "total_rows": len(raw_rows),
                "currency": raw_rows[0]["customer.currency_code"] if raw_rows else "USD",
                "is_complete": True,
                "rate_limit_remaining": self.rate_limit,
                "next_page_token": None,
                "report_type": report_type,
                "date_from": date_from,
                "date_to": date_to,
                "customer_id": customer_id,
                "mode": "real",
            },
        }

    def _mock_pull(self, date_from, date_to, report_type="campaign_daily", **kwargs):
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
                    cost_micros = random.randint(100000000, 5000000000)
                    spend = cost_micros / 1000000
                    installs = random.randint(5, 400)
                    raw_rows.append({
                        "segments.date": current_date.strftime("%Y-%m-%d"),
                        "campaign.id": campaign["id"],
                        "campaign.name": campaign["name"],
                        "campaign.status": "ENABLED",
                        "ad_group.id": f"gid_{campaign['id']}",
                        "ad_group.name": f"AdGroup_{campaign['name']}",
                        "ad_group_ad.ad.id": f"gad_{campaign['id']}",
                        "ad_group_ad.ad.name": f"GAd_{campaign['name']}",
                        "customer.id": kwargs.get("customer_id", self.customer_id),
                        "customer.currency_code": "USD",
                        "metrics.impressions": impressions,
                        "metrics.clicks": clicks,
                        "metrics.cost_micros": cost_micros,
                        "metrics.conversions": random.randint(3, 150),
                        "metrics.ctr": clicks / impressions if impressions > 0 else 0,
                        "metrics.average_cpc": spend / clicks if clicks > 0 else 0,
                        "metrics.average_cpm": spend * 1000 / impressions if impressions > 0 else 0,
                        "metrics.installs": installs,
                        "_pulled_at": datetime.utcnow().isoformat(),
                    })
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
            },
        }

    # ---------------- 字段标准化 ----------------
    def normalize(self, raw_rows: List[Dict]) -> List[Dict]:
        normalized_rows = []
        for row in raw_rows:
            spend = self._safe_float(row.get("metrics.cost_micros", 0)) / 1000000
            # 真实 Google 无 metrics.installs（安装来自 MMP/AppsFlyer）；app Campaign 以 conversions 近似 installs
            installs = self._safe_int(row.get("metrics.installs")) or self._safe_int(row.get("metrics.conversions", 0))
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
                "spend_usd": to_usd(spend, row.get("customer.currency_code", "USD"), self.db, self.app_id),
                "ctr": self._safe_float(row.get("metrics.ctr", 0)),
                "cpc": self._safe_float(row.get("metrics.average_cpc", 0)),
                "cpm": self._safe_float(row.get("metrics.average_cpm", 0)),
                "installs": installs,
                "conversions": self._safe_int(row.get("metrics.conversions", 0)),
                "media_source": "google",
            }
            normalized["cpi"] = spend / installs if installs > 0 else 0.0
            normalized_rows.append(normalized)
        return normalized_rows

    # ---------------- 结构拉取（Campaign->AdGroup->Ad->Creative 层级 + 运营态） ----------------

    def pull_structure(self) -> Dict[str, Any]:
        """拉取计划分层结构与运营态。凭证/SDK 缺失时走 mock。"""
        if self._is_mock:
            return self._mock_structure()
        return self._real_structure()

    def _mock_structure(self) -> Dict[str, Any]:
        campaigns = [
            ("14280694219", "Google_US_App_Install"),
            ("14280694220", "Google_GB_App_Install"),
            ("14280694221", "Google_CA_App_Install"),
        ]
        rows = []
        cur = "USD"
        for cid, cname in campaigns:
            rows.append({"entity_level": "campaign", "entity_id": cid, "parent_id": None,
                         "campaign_id": cid, "campaign_name": cname, "status": "ENABLED",
                         "daily_budget": 500.0, "currency": cur, "account_id": self.customer_id})
            for j in range(1, 3):
                gid = f"gid_{cid}_{j}"
                gname = f"AdGroup_{cname}_{j}"
                rows.append({"entity_level": "adset", "entity_id": gid, "parent_id": cid,
                             "campaign_id": cid, "campaign_name": cname, "adset_id": gid,
                             "adset_name": gname, "status": "ENABLED", "daily_budget": 250.0,
                             "currency": cur, "account_id": self.customer_id})
                for k in range(1, 3):
                    aid = f"gad_{gid}_{k}"
                    aname = f"GAd_{gname}_{k}"
                    rows.append({"entity_level": "ad", "entity_id": aid, "parent_id": gid,
                                 "campaign_id": cid, "campaign_name": cname, "adset_id": gid,
                                 "adset_name": gname, "ad_id": aid, "ad_name": aname,
                                 "status": "ENABLED", "account_id": self.customer_id})
                    cri = f"cr_{aid}"
                    rows.append({"entity_level": "creative", "entity_id": cri, "parent_id": aid,
                                 "campaign_id": cid, "campaign_name": cname, "adset_id": gid,
                                 "adset_name": gname, "ad_id": aid, "ad_name": aname,
                                 "creative_id": cri, "creative_name": f"Creative_{aname}",
                                 "status": "ENABLED", "account_id": self.customer_id})
        return {"raw_rows": rows, "metadata": {"mode": "mock", "account_id": self.customer_id}}

    def _real_structure(self) -> Dict[str, Any]:
        client = self._real_client()
        ga_service = client.get_service("GoogleAdsService")
        cid = self.customer_id
        cur = "USD"
        rows = []

        # 1) Campaigns（含预算）
        cq = (f"SELECT campaign.id, campaign.name, campaign.status, "
              f"campaign_budget.amount_micros, customer.currency_code "
              f"FROM campaign WHERE customer.id = '{cid}'")
        campaigns = list(ga_service.search(customer_id=cid, query=cq))
        for c in campaigns:
            cid_ = str(c.campaign.id)
            cur = c.customer.currency_code or "USD"
            budget = c.campaign_budget.amount_micros / 1_000_000 if c.campaign_budget else None
            rows.append({"entity_level": "campaign", "entity_id": cid_, "parent_id": None,
                         "campaign_id": cid_, "campaign_name": c.campaign.name,
                         "status": c.campaign.status.name, "daily_budget": budget,
                         "currency": cur, "account_id": cid})
            # 2) Ad Groups
            aq = (f"SELECT ad_group.id, ad_group.name, ad_group.status "
                  f"FROM ad_group WHERE campaign.id = '{cid_}'")
            for g in ga_service.search(customer_id=cid, query=aq):
                gid = str(g.ad_group.id)
                rows.append({"entity_level": "adset", "entity_id": gid, "parent_id": cid_,
                             "campaign_id": cid_, "campaign_name": c.campaign.name,
                             "adset_id": gid, "adset_name": g.ad_group.name,
                             "status": g.ad_group.status.name, "currency": cur,
                             "account_id": cid})
                # 3) Ads + creatives
                dq = (f"SELECT ad_group_ad.ad.id, ad_group_ad.ad.name, ad_group_ad.status, "
                      f"ad_group_ad.ad.creative.id, ad_group_ad.ad.creative.name "
                      f"FROM ad_group_ad WHERE ad_group.id = '{gid}'")
                for d in ga_service.search(customer_id=cid, query=dq):
                    aid = str(d.ad_group_ad.ad.id)
                    rows.append({"entity_level": "ad", "entity_id": aid, "parent_id": gid,
                                 "campaign_id": cid_, "campaign_name": c.campaign.name,
                                 "adset_id": gid, "adset_name": g.ad_group.name,
                                 "ad_id": aid, "ad_name": d.ad_group_ad.ad.name,
                                 "status": d.ad_group_ad.status.name, "account_id": cid})
                    cri = str(d.ad_group_ad.ad.creative.id)
                    rows.append({"entity_level": "creative", "entity_id": cri, "parent_id": aid,
                                 "campaign_id": cid_, "campaign_name": c.campaign.name,
                                 "adset_id": gid, "adset_name": g.ad_group.name,
                                 "ad_id": aid, "ad_name": d.ad_group_ad.ad.name,
                                 "creative_id": cri,
                                 "creative_name": d.ad_group_ad.ad.creative.name,
                                 "status": d.ad_group_ad.status.name, "account_id": cid})
        return {"raw_rows": rows, "metadata": {"mode": "real", "account_id": cid}}

    # ---------------- 写动作（真实 mutation / mock 回退） ----------------
    def update_campaign_status(self, campaign_id: str, status: str) -> Dict[str, Any]:
        if self._is_mock:
            return {"success": True, "mock": True, "action": "update_campaign_status",
                    "campaign_id": campaign_id, "status": status}
        try:
            client = self._real_client()
            svc = client.get_service("CampaignService")
            op = client.get_type("CampaignOperation")
            op.update.resource_name = svc.campaign_path(self.customer_id, campaign_id)
            status_enum = client.get_type("CampaignStatus")
            op.update.status = status_enum.PAUSED if str(status).upper() == "PAUSED" else status_enum.ENABLED
            client.copy_from(op.update_mask, ["status"])
            svc.mutate_campaigns(customer_id=self.customer_id, operations=[op])
            return {"success": True, "action": "update_campaign_status",
                    "campaign_id": campaign_id, "status": status}
        except Exception as e:
            logger.error(f"Google update_campaign_status failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def update_campaign_budget(self, campaign_id: str, daily_budget: float) -> Dict[str, Any]:
        if self._is_mock:
            return {"success": True, "mock": True, "action": "update_campaign_budget",
                    "campaign_id": campaign_id, "daily_budget": daily_budget}
        try:
            client = self._real_client()
            # 1) 取该 campaign 绑定的预算资源名
            ga_service = client.get_service("GoogleAdsService")
            budget_query = f"SELECT campaign.campaign_budget FROM campaign WHERE campaign.id = {campaign_id}"
            budget_rn = None
            for r in ga_service.search(customer_id=self.customer_id, query=budget_query):
                budget_rn = r.campaign.campaign_budget
                break
            if not budget_rn:
                return {"success": False, "error": f"campaign {campaign_id} 未找到绑定预算"}
            # 2) 改预算金额（micros）
            bsvc = client.get_service("CampaignBudgetService")
            bop = client.get_type("CampaignBudgetOperation")
            bop.update.resource_name = budget_rn
            bop.update.amount_micros = int(daily_budget * 1_000_000)
            client.copy_from(bop.update_mask, ["amount_micros"])
            bsvc.mutate_campaign_budgets(customer_id=self.customer_id, operations=[bop])
            return {"success": True, "action": "update_campaign_budget",
                    "campaign_id": campaign_id, "daily_budget": daily_budget}
        except Exception as e:
            logger.error(f"Google update_campaign_budget failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def update_adset_bid(self, adset_id: str, bid_amount: float) -> Dict[str, Any]:
        if self._is_mock:
            return {"success": True, "mock": True, "action": "update_adset_bid",
                    "adset_id": adset_id, "bid_amount": bid_amount}
        try:
            client = self._real_client()
            svc = client.get_service("AdGroupService")
            op = client.get_type("AdGroupOperation")
            op.update.resource_name = svc.ad_group_path(self.customer_id, adset_id)
            op.update.cpc_bid_micros = int(bid_amount * 1_000_000)
            client.copy_from(op.update_mask, ["cpc_bid_micros"])
            svc.mutate_ad_groups(customer_id=self.customer_id, operations=[op])
            return {"success": True, "action": "update_adset_bid",
                    "adset_id": adset_id, "bid_amount": bid_amount}
        except Exception as e:
            logger.error(f"Google update_adset_bid failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def rotate_creative(self, entity_id: str) -> Dict[str, Any]:
        """换素材：暂停指定广告（entity_id 支持 'adGroupId/adId' 或完整 resource_name）。

        注：Google 真实"换素材"需先上传新素材资源再启用；本实现先暂停旧广告，
        新素材请在 Google Ads 后台/资产库上传后由 agent 后续启用。"""
        if self._is_mock:
            return {"success": True, "mock": True, "action": "rotate_creative", "entity_id": entity_id}
        try:
            client = self._real_client()
            svc = client.get_service("AdGroupAdService")
            if "/" in str(entity_id):
                ad_group_id, ad_id = str(entity_id).split("/", 1)
                resource_name = svc.ad_group_ad_path(self.customer_id, ad_group_id, ad_id)
            else:
                resource_name = str(entity_id)  # 假定已是完整 resource_name
            op = client.get_type("AdGroupAdOperation")
            op.update.resource_name = resource_name
            op.update.status = client.get_type("AdGroupAdStatus").PAUSED
            client.copy_from(op.update_mask, ["status"])
            svc.mutate_ad_group_ads(customer_id=self.customer_id, operations=[op])
            return {"success": True, "action": "rotate_creative", "entity_id": entity_id, "note": "旧广告已暂停，请上传新素材后启用"}
        except Exception as e:
            logger.error(f"Google rotate_creative failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    # ---------------- 工具 ----------------
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
