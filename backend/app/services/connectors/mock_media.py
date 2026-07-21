"""Mock 媒体连接器（替代被封的 Meta，作为 Phase 0 真实执行的数据土壤）。

与 MetaConnector 旧 mock 的本质区别：
- 旧 mock：pull 每次重新随机、写操作只返回 success 不改状态 → 无因果链。
- 本连接器：背后是一个有状态的 SimulationEngine。写操作真实修改 campaign 状态，
  pull 返回的"历史"会反映这些动作的效果 → 形成 动作→指标 的因果闭环，
  可直接被记忆/反思模块消费。

切换真实 Meta 时，只需在 ConnectorFactory 把 "mock" 换回 "meta"，
上层 Tool/Skill Registry 与 intent 引擎无需改动（这正是 Connector 抽象的价值）。
"""
from datetime import date, datetime, timedelta
from typing import Dict, Any, List, Optional

from .base import BaseConnector
from app.services.simulation.engine import SimulationEngine

# 进程内单例：让多次 pull / 多次写操作共享同一份模拟状态（dev/mock 场景可接受）。
_engine: Optional[SimulationEngine] = None


def get_sim_engine(seed: int = 42) -> SimulationEngine:
    """获取（或惰性初始化）共享的模拟引擎。"""
    global _engine
    if _engine is None:
        _engine = SimulationEngine(seed=seed).seed_demo_account()
        _engine.advance_days(3)  # 预置 3 天历史，使 current_summary() 立即有数据可观察
    return _engine


def reset_sim_engine(seed: int = 42) -> SimulationEngine:
    """重置模拟引擎（测试/演示用）。"""
    global _engine
    _engine = SimulationEngine(seed=seed).seed_demo_account()
    _engine.advance_days(3)
    return _engine


class MockMediaConnector(BaseConnector):
    """Mock 媒体连接器：读=历史快照，写=修改模拟状态。"""

    platform = "mock"
    source_type = "media"
    rate_limit = 1000  # mock 不限流
    supported_modes = ("mock",)
    capabilities = {
        "read": True,
        "write": True,
        "structure": True,
        "simulate": True,
    }

    def __init__(self, db, app_id, credentials, execution_mode: str = "mock"):
        super().__init__(db, app_id, credentials, execution_mode=execution_mode)
        self.engine = get_sim_engine(credentials.get("seed", 42))
        self.account_id = "mock-sim-account"

    # ---------------- 认证 ---------------- #
    def auth(self) -> bool:
        # mock 无需真实凭证
        return True

    # ---------------- 读：拉取数据 ---------------- #
    def pull(self, date_from: date, date_to: date,
             report_type: str = "campaign_daily", **kwargs) -> Dict[str, Any]:
        """返回 [date_from, date_to] 内的每日指标快照。

        若引擎尚未推进到 date_to，则先补齐（仅追加新日期，不会重复），
        保证 pull 总能拿到数据；重复 pull 同一区间不会重复生成。
        """
        self._ensure_advanced(date_to)
        history = self.engine.get_history(date_from, date_to)

        raw_rows: List[Dict] = []
        for snap in history:
            for row in snap["rows"]:
                raw_rows.append(row.to_raw())

        return {
            "raw_rows": raw_rows,
            "metadata": {
                "total_rows": len(raw_rows),
                "currency": "USD",
                "is_complete": True,
                "rate_limit_remaining": 1000,
                "next_page_token": None,
                "report_type": report_type,
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "account_id": kwargs.get("ad_account_id", "mock_account"),
                "mode": "mock-sim",
            },
        }

    def _ensure_advanced(self, date_to: date):
        """把引擎推进到 date_to（仅追加缺失日期）。"""
        eng = self.engine
        if eng._today is None:
            cur = date_to - timedelta(days=13)  # 默认补 14 天历史
            cur = max(cur, date(2024, 1, 1))
            eng._today = cur - timedelta(days=1)
        while eng._today < date_to:
            eng.advance_day(eng._today + timedelta(days=1))

    def normalize(self, raw_rows: List[Dict]) -> List[Dict]:
        """字段标准化（与 Meta normalize 对齐，并保留 roi/revenue 供 agent 使用）。"""
        normalized = []
        for row in raw_rows:
            installs = self._safe_int(row.get("mobile_app_installs", 0))
            spend = self._safe_float(row.get("spend", 0))
            normalized.append({
                "date": row.get("date_start"),
                "account_id": self.ad_account_id if hasattr(self, "ad_account_id") else "",
                "campaign_id": row.get("campaign_id", ""),
                "campaign_name": row.get("campaign_name", ""),
                "country": row.get("country", "ALL"),
                "currency": row.get("account_currency", "USD"),
                "impressions": self._safe_int(row.get("impressions", 0)),
                "clicks": self._safe_int(row.get("clicks", 0)),
                "spend": spend,
                "spend_usd": spend,
                "installs": installs,
                "conversions": self._safe_int(row.get("conversions", 0)),
                "ctr": self._safe_float(row.get("ctr", 0)),
                "cpc": self._safe_float(row.get("cpc", 0)),
                "cpm": self._safe_float(row.get("cpm", 0)),
                "cpi": self._safe_float(row.get("cpi", 0)),
                "revenue": self._safe_float(row.get("revenue", 0)),
                "roi": self._safe_float(row.get("roi", 0)),
                "media_source": "mock",
                "creative_age": 0,
            })
        return normalized

    # ---------------- 写：真实修改模拟状态 ---------------- #
    def update_campaign_status(self, campaign_id: str, status: str) -> Dict[str, Any]:
        return self.engine.apply_action("update_campaign_status", campaign_id, status=status)

    def update_campaign_budget(self, campaign_id: str, daily_budget: float) -> Dict[str, Any]:
        return self.engine.apply_action("update_campaign_budget", campaign_id, daily_budget=daily_budget)

    def update_adset_bid(self, adset_id: str, bid_amount: float) -> Dict[str, Any]:
        return self.engine.apply_action("update_adset_bid", adset_id, bid_amount=bid_amount)

    def rotate_creative(self, campaign_id: str) -> Dict[str, Any]:
        return self.engine.apply_action("rotate_creative", campaign_id)

    # ---------------- agent 辅助接口 ---------------- #
    def account_status(self) -> str:
        """返回媒体账户状态；主动自治检测器据此判断是否被封/受限（Meta appeal 等）。

        委托给共享的 SimulationEngine（单例），使账户状态在多次 get_connector 间持久。
        """
        return self.engine.account_status

    def simulate_account_disabled(self, disabled: bool = True) -> None:
        """演示用：模拟账户被封 / 恢复，触发主动自治的 ACCOUNT_DISABLED 告警。"""
        self.engine.set_account_status("DISABLED" if disabled else "ok")

    def current_summary(self) -> List[Dict]:
        """返回基于实时状态的账户概览（供 agent 决策/展示）。

        用 engine.live_summary() 而非 summary()：前者反映动作后的实时状态
        （如暂停后该 campaign 立即显示 PAUSED、spend=0），避免 Agent 基于过期快照
        重复提议已被处置的 campaign。
        """
        return self.engine.live_summary()

    def simulate_impact(self, action: str, entity_id: str, params: Dict, horizon: int = 7):
        """包装引擎的影响评估，供反思模块调用。"""
        return self.engine.simulate_action_impact(action, entity_id, params, horizon)

    @staticmethod
    def _safe_int(v) -> int:
        try:
            return int(v) if v is not None else 0
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _safe_float(v) -> float:
        try:
            return float(v) if v is not None else 0.0
        except (ValueError, TypeError):
            return 0.0
