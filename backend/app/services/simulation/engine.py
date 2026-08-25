"""有状态因果投放模拟引擎（mock 媒体）。

为什么需要它：
现有 MetaConnector 的 mock 模式是"无状态随机"——每次 pull 重新随机、写操作只返回
success 而不改任何内部状态。因此"agent 动作 → 后续指标"之间不存在因果链，记忆/反思
闭环拿不到可用于学习的样本。

本引擎用确定性的响应曲线替代随机，使动作产生可解释、可复现、可被 reflection 提取
经验的效果，从而成为 agent 进化能力的真实数据土壤（在 Meta 账户恢复前即可验证）。

因果模型（每个 ACTIVE campaign 每天生成一次）：
  spend      = budget * bid_mult（受预算上限，±噪声）
  cpm        = base_cpm * bid_mult            # 出价越高单价越高
  impressions= spend / cpm * 1000
  ctr        = base_ctr * fatigue(age) * fresh(age)   # 素材疲劳 + 换素材短期提振
  clicks     = impressions * ctr
  installs   = capacity * (1 - exp(-spend / k))       # 预算饱和（边际 ROI 递减）
  payers     = installs * payer_rate
  revenue    = payers * ltv_per_payer
  roi        = revenue / spend
  cpi        = spend / installs

动作效果：
  pause      → 次日 spend/installs/revenue=0（"止损"可被反思识别）
  budget +x% → spend↑ 但 installs 次线性↑ → ROI 略降（"预算扩张边际递减"）
  bid +x%    → cpm↑ → cpi↑、ROI↓（"提价伤 ROI"）
  rotate     → age 归零，fresh 因子短期 +CTR → ROI 短期抬升后衰减（"换素材短期有效"）
"""
from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class CampaignState:
    """单个 campaign 的持久状态（会被动作修改，并驱动后续每日指标）。"""

    id: str
    name: str
    country: str
    status: str = "ACTIVE"          # ACTIVE / PAUSED
    daily_budget: float = 500.0     # USD
    bid_mult: float = 1.0           # 出价倍率（1.0=基准）
    creative_age: int = 0           # 距上次换素材的天数（驱动疲劳）

    # —— 隐藏"质量"参数（每个 campaign 由 seed 决定，模拟真实差异）——
    base_cpm: float = 8.0
    base_ctr: float = 0.009
    capacity: float = 300.0         # 预算→安装的饱和容量
    sat_k: float = 400.0            # 饱和曲线斜率（spend 标度）
    payer_rate: float = 0.12        # install→payer
    ltv_per_payer: float = 30.0     # 单个 payer 生命周期价值
    fatigue_rate: float = 0.06      # 素材每日疲劳系数
    fresh_lift: float = 0.25        # 换素材瞬时 CTR 提升
    fresh_tau: float = 4.0          # 换素材效果衰减时间常数（天）
    noise: float = 0.05             # 指标噪声（相对）


@dataclass
class AdSetState:
    """单个 AdSet（广告组）的持久状态。归属某个 campaign，拥有独立出价与状态。"""

    id: str
    name: str
    campaign_id: str
    status: str = "ACTIVE"          # ACTIVE / PAUSED
    bid: float = 1.0               # 出价倍率（1.0=基准）
    # 质量参数（由 id 派生，模拟广告组间差异）
    base_ctr: float = 0.01
    ctr_fatigue: float = 0.0       # 创意疲劳累积（驱动 evaluate_creative）
    cpi: float = 0.0
    roi: float = 0.0
    spend: float = 0.0


@dataclass
class AdState:
    """单个 Ad（广告）的状态。归属某个 AdSet，挂载一个 creative。"""

    id: str
    name: str
    adset_id: str
    creative_id: str
    status: str = "ACTIVE"
    creative_age: int = 0
    ctr: float = 0.0
    cpi: float = 0.0
    roi: float = 0.0
    spend: float = 0.0


@dataclass
class DayRow:
    """某 campaign 某天的指标快照。"""

    date: date
    campaign_id: str
    campaign_name: str
    country: str
    status: str
    impressions: int
    clicks: int
    installs: int
    payers: int
    spend: float
    revenue: float
    ctr: float
    cpc: float
    cpm: float
    cpi: float
    roi: float

    def to_raw(self) -> Dict:
        """转换为接近 Meta Insights 的原始行（供 connector.pull 复用）。"""
        return {
            "date_start": self.date.isoformat(),
            "date_stop": self.date.isoformat(),
            "campaign_id": self.campaign_id,
            "campaign_name": self.campaign_name,
            "country": self.country,
            "impressions": self.impressions,
            "clicks": self.clicks,
            "mobile_app_installs": self.installs,
            "conversions": self.payers,
            "spend": round(self.spend, 2),
            "ctr": round(self.ctr, 6),
            "cpc": round(self.cpc, 4),
            "cpm": round(self.cpm, 4),
            "cpi": round(self.cpi, 4),
            "revenue": round(self.revenue, 2),
            "payers": self.payers,
            "roi": round(self.roi, 4),
            "account_currency": "USD",
        }


@dataclass
class ActionEffect:
    """施加某动作后，目标 campaign 在 horizon 天内的"对照 vs 处理"对比。"""

    campaign_id: str
    action: str
    params: Dict
    applied_on: date
    horizon: int
    control: List[Dict]   # 不施加动作（baseline）
    treatment: List[Dict] # 施加动作
    delta_roi: List[float]
    delta_spend: List[float]
    delta_cpi: List[float]


# --------------------------------------------------------------------------- #
# 引擎
# --------------------------------------------------------------------------- #
class SimulationEngine:
    """有状态因果模拟引擎。"""

    def __init__(self, seed: int = 42):
        self.seed = seed
        self._rng = random.Random(seed)
        self.campaigns: Dict[str, CampaignState] = {}
        self.adsets: Dict[str, AdSetState] = {}
        self.ads: Dict[str, AdState] = {}
        self.history: List[Dict] = []   # [{"date":..., "rows":[DayRow,...]}, ...]
        self._today: Optional[date] = None
        self.account_status: str = "ok"   # 媒体账户状态（主动自治检测器据此判断是否被封/受限）

    # ----------------------------- 初始化 ----------------------------- #
    def add_campaign(self, c: CampaignState) -> "SimulationEngine":
        """注册一个 campaign（质量参数未指定时按 id 派生，保证可复现且彼此不同）。"""
        if c.base_cpm == 8.0 and c.capacity == 300.0:  # 走默认 → 派生差异化
            h = int(abs(hash(c.id)) % 10000)
            r = random.Random(h)
            c.base_cpm = round(r.uniform(5.0, 12.0), 2)
            c.base_ctr = round(r.uniform(0.006, 0.013), 4)
            c.capacity = round(r.uniform(180.0, 380.0), 1)
            c.sat_k = round(r.uniform(300.0, 550.0), 1)
            c.payer_rate = round(r.uniform(0.08, 0.18), 3)
            c.ltv_per_payer = round(r.uniform(20.0, 45.0), 1)
            c.fatigue_rate = round(r.uniform(0.04, 0.08), 3)
        self.campaigns[c.id] = c
        return self

    def seed_demo_account(self, n: int = 4) -> "SimulationEngine":
        """注入一组典型海外 UA campaign（US/GB/CA/JP），含高/低 ROI 样本。"""
        specs = [
            ("camp_uk_001", "Campaign_GB_ROAS", "GB", 520.0, 1.0, 0.014, 340.0, 0.16, 42.0),
            ("camp_us_002", "Campaign_US_SCALE", "US", 800.0, 1.0, 0.011, 360.0, 0.13, 33.0),
            ("camp_ca_003", "Campaign_CA_LOWROI", "CA", 600.0, 1.0, 0.007, 260.0, 0.10, 22.0),
            ("camp_jp_004", "Campaign_JP_TEST", "JP", 450.0, 1.0, 0.009, 300.0, 0.12, 38.0),
        ]
        for i, (cid, name, country, budget, _, ctr, cap, pr, ltv) in enumerate(specs[:n]):
            c = CampaignState(
                id=cid, name=name, country=country, daily_budget=budget,
                base_ctr=ctr, capacity=cap, payer_rate=pr, ltv_per_payer=ltv,
            )
            self.add_campaign(c)
            self._seed_adsets_for(cid, ctr, i)
        return self

    def _seed_adsets_for(self, campaign_id: str, base_ctr: float, salt: int) -> None:
        """每个 campaign 挂 2 个 AdSet（一好一差），每个 AdSet 挂 2 个 Ad。"""
        rng = random.Random(hash(("adset", campaign_id, salt)) & 0xFFFFFFFF)
        specs = [
            ("win", 1.05, 0.0),   # 高出价、低疲劳（优质组）
            ("fatigued", 0.95, 0.6),  # 低出价、高疲劳（待换素材/暂停）
        ]
        for j, (tag, bid, fatigue) in enumerate(specs):
            aid = f"{campaign_id}_as{j+1}"
            ctr = round(base_ctr * (1.15 if tag == "win" else 0.7) * rng.uniform(0.9, 1.1), 5)
            spend = round(rng.uniform(80, 320), 2)
            cpi = round(rng.uniform(0.8, 3.5), 2)
            roi = round(rng.uniform(1.4, 2.2) if tag == "win" else rng.uniform(0.3, 0.9), 3)
            self.adsets[aid] = AdSetState(
                id=aid, name=f"AdSet_{tag.upper()}", campaign_id=campaign_id,
                bid=bid, base_ctr=ctr, ctr_fatigue=fatigue,
                cpi=cpi, roi=roi, spend=spend,
            )
            for k in range(2):
                ad_id = f"{aid}_ad{k+1}"
                cr_id = f"{aid}_cr{k+1}"
                ad_ctr = round(ctr * rng.uniform(0.8, 1.2), 5)
                self.ads[ad_id] = AdState(
                    id=ad_id, name=f"Ad_{k+1}", adset_id=aid, creative_id=cr_id,
                    creative_age=int(fatigue * 10) + k, ctr=ad_ctr,
                    cpi=round(cpi * rng.uniform(0.9, 1.2), 2),
                    roi=round(roi * rng.uniform(0.85, 1.15), 3),
                    spend=round(spend * rng.uniform(0.3, 0.6), 2),
                )

    # ----------------------------- 时间推进 ----------------------------- #
    def advance_day(self, dt: Optional[date] = None) -> List[DayRow]:
        """推进一天，按当前状态生成所有 campaign 的当日指标并写入 history。"""
        if dt is None:
            dt = (self._today + timedelta(days=1)) if self._today else date.today()
        self._today = dt

        rows: List[DayRow] = []
        for c in self.campaigns.values():
            row = self._generate_day(c, dt)
            rows.append(row)
            # 仅 ACTIVE 且未暂停时素材才疲劳；PAUSED 冻结年龄
            if c.status == "ACTIVE":
                c.creative_age += 1
        self.history.append({"date": dt, "rows": rows})
        return rows

    def advance_days(self, days: int, start: Optional[date] = None) -> List[DayRow]:
        out: List[DayRow] = []
        cur = start or (self._today or date.today())
        for _ in range(days):
            out.extend(self.advance_day(cur))
            cur = cur + timedelta(days=1)
        return out

    # ----------------------------- 动作 ----------------------------- #
    def apply_action(self, action: str, entity_id: str, **params) -> Dict:
        """施加一个写动作，真实修改 campaign / adset 状态。返回执行结果。"""
        # AdSet 层动作：先于 campaign 查找，避免把 adset_id 误判为 campaign 缺失
        if action in ("update_adset_bid", "update_adset_status"):
            return self._apply_adset(action, entity_id, params)

        c = self.campaigns.get(entity_id)
        if not c:
            return {"success": False, "error": f"campaign not found: {entity_id}"}

        if action == "update_campaign_status":
            status = str(params.get("status", "")).upper()
            if status not in ("ACTIVE", "PAUSED"):
                return {"success": False, "error": f"invalid status: {status}"}
            c.status = status
        elif action == "update_campaign_budget":
            new_b = float(params.get("daily_budget", c.daily_budget))
            if new_b <= 0:
                return {"success": False, "error": "budget must be positive"}
            c.daily_budget = new_b
        elif action == "rotate_creative":
            c.creative_age = 0  # 重置疲劳并触发 fresh 提升
        else:
            return {"success": False, "error": f"unknown action: {action}"}
        return self._ok(action, entity_id, c)

    def _apply_adset(self, action: str, entity_id: str, params: Dict) -> Dict:
        a = self.adsets.get(entity_id)
        if not a:
            return {"success": False, "error": f"adset not found: {entity_id}"}
        if action == "update_adset_bid":
            bid = float(params.get("bid_amount", a.bid))
            if bid <= 0:
                return {"success": False, "error": "bid must be positive"}
            a.bid = bid
        else:  # update_adset_status
            status = str(params.get("status", "")).upper()
            if status not in ("ACTIVE", "PAUSED"):
                return {"success": False, "error": f"invalid status: {status}"}
            a.status = status
        return {
            "success": True, "action": action, "entity_id": entity_id,
            "new_state": {"status": a.status, "bid": a.bid,
                          "campaign_id": a.campaign_id, "name": a.name},
            "mode": "mock-sim",
        }

    def _ok(self, action: str, entity_id: str, c: CampaignState) -> Dict:
        return {
            "success": True, "action": action, "entity_id": entity_id,
            "new_state": {
                "status": c.status,
                "daily_budget": c.daily_budget,
                "bid_mult": c.bid_mult,
                "creative_age": c.creative_age,
            },
            "mode": "mock-sim",
        }

    # ----------------------------- AdSet/Ad 读取 ----------------------------- #
    def adsets_summary(self, campaign_id: Optional[str] = None) -> List[Dict]:
        """返回 AdSet 层概览，供 observe_adsets / evaluate_creative 使用。"""
        out = []
        for a in self.adsets.values():
            if campaign_id and a.campaign_id != campaign_id:
                continue
            out.append({
                "adset_id": a.id, "name": a.name, "campaign_id": a.campaign_id,
                "status": a.status, "bid": a.bid, "ctr": round(a.base_ctr * (1.0 - a.ctr_fatigue), 5),
                "cpi": a.cpi, "roi": a.roi, "spend": a.spend,
                "fatigue": round(a.ctr_fatigue, 2),
            })
        return out

    def evaluate_creative_health(self, adset_id: Optional[str] = None) -> List[Dict]:
        """评估 Ad 层素材健康度：基于 ctr/疲劳/ROI 给出 healthy/fatigued/underperforming。"""
        out = []
        for ad in self.ads.values():
            if adset_id and ad.adset_id != adset_id:
                continue
            fatigue = ad.creative_age
            if fatigue >= 8 or ad.roi < 0.8:
                health = "fatigued"
                suggest = "rotate_creative"
            elif ad.roi < 1.0:
                health = "underperforming"
                suggest = "observe_adsets"
            else:
                health = "healthy"
                suggest = None
            out.append({
                "ad_id": ad.id, "name": ad.name, "adset_id": ad.adset_id,
                "creative_id": ad.creative_id, "creative_age": fatigue,
                "ctr": ad.ctr, "cpi": ad.cpi, "roi": ad.roi, "spend": ad.spend,
                "health": health, "suggested_action": suggest,
            })
        return out

    # ----------------------------- 读取 ----------------------------- #
    def get_history(self, date_from: date, date_to: date) -> List[Dict]:
        return [h for h in self.history if date_from <= h["date"] <= date_to]

    def latest_day_rows(self) -> List[DayRow]:
        return self.history[-1]["rows"] if self.history else []

    def summary(self) -> List[Dict]:
        """返回最近一天的每 campaign 关键指标，便于 agent 决策/展示。"""
        rows = self.latest_day_rows()
        return [
            {
                "campaign_id": r.campaign_id,
                "name": r.campaign_name,
                "country": r.country,
                "status": r.status,
                "spend": round(r.spend, 2),
                "installs": r.installs,
                "revenue": round(r.revenue, 2),
                "roi": round(r.roi, 3),
                "cpi": round(r.cpi, 2),
            }
            for r in rows
        ]

    def live_summary(self) -> List[Dict]:
        """返回基于**实时状态**的账户概览（反映动作后但尚未推进日期的变化）。

        与 summary() 的区别：summary() 读的是历史最后一天的快照，动作（如 pause）
        改的是 campaign 实时状态，不会立即反映到快照里。Agent 在做"下一步决策"时
        需要看到动作后的真实状态（例如暂停后该 campaign 应显示为 PAUSED、spend=0），
        否则会基于过期快照重复提议。

        实现上只把实时 status 覆盖到快照并清零暂停项的指标，不重新生成、不消耗 rng，
        因此不会污染后续 advance_day 的确定性。
        """
        base = self.summary()
        if not base:
            return base
        by_id = {cid: c for cid, c in self.campaigns.items()}
        out: List[Dict] = []
        for r in base:
            c = by_id.get(r["campaign_id"])
            if c is None:
                out.append(r)
                continue
            if c.status != "ACTIVE":
                out.append({**r, "status": c.status, "spend": 0.0,
                            "installs": 0, "revenue": 0.0, "roi": 0.0, "cpi": 0.0,
                            "creative_age": c.creative_age, "daily_budget": c.daily_budget})
            else:
                out.append({**r, "status": c.status,
                            "creative_age": c.creative_age, "daily_budget": c.daily_budget})
        return out

    # ----------------------------- 影响评估（反思原料） ----------------------------- #
    def simulate_action_impact(self, action: str, entity_id: str,
                               params: Dict, horizon: int = 7) -> ActionEffect:
        """克隆引擎，在副本上施加动作并推进 horizon 天，返回 对照 vs 处理 的每日对比。

        这是"记忆-反思"闭环的核心原料：agent 每做一个动作，都能拿到可量化的因果影响，
        用于判断该动作是否达成了目标（如"暂停低 ROI campaign 是否真止损"）。
        """
        applied_on = self._today or date.today()
        start = applied_on + timedelta(days=1)

        control = self._clone_and_advance(horizon, start, None, None)
        treatment = self._clone_and_advance(horizon, start, action, entity_id, params)

        def extract(seq: List[List[DayRow]], cid: str):
            out = []
            for day_rows in seq:
                r = next((x for x in day_rows if x.campaign_id == cid), None)
                if r:
                    out.append({"date": r.date.isoformat(), "roi": r.roi,
                                "spend": r.spend, "cpi": r.cpi, "revenue": r.revenue})
            return out

        c_seq = extract(control, entity_id)
        t_seq = extract(treatment, entity_id)
        n = min(len(c_seq), len(t_seq))
        delta_roi = [round(t_seq[i]["roi"] - c_seq[i]["roi"], 4) for i in range(n)]
        delta_spend = [round(t_seq[i]["spend"] - c_seq[i]["spend"], 2) for i in range(n)]
        delta_cpi = [round(t_seq[i]["cpi"] - c_seq[i]["cpi"], 3) for i in range(n)]

        return ActionEffect(
            campaign_id=entity_id, action=action, params=params,
            applied_on=applied_on, horizon=horizon,
            control=c_seq, treatment=t_seq,
            delta_roi=delta_roi, delta_spend=delta_spend, delta_cpi=delta_cpi,
        )

    # ----------------------------- 内部 ----------------------------- #
    def _clone_and_advance(self, horizon: int, start: date,
                           action: Optional[str], entity_id: str = "",
                           params: Dict = None) -> List[List[DayRow]]:
        """克隆当前引擎，可选施加动作，推进 horizon 天，返回每日 DayRow 列表。"""
        clone = copy.deepcopy(self)
        if action:
            clone.apply_action(action, entity_id, **(params or {}))
        seq: List[List[DayRow]] = []
        cur = start
        for _ in range(horizon):
            seq.append(clone.advance_day(cur))
            cur = cur + timedelta(days=1)
        return seq

    def _generate_day(self, c: CampaignState, dt: date) -> DayRow:
        rnd = self._rng
        if c.status != "ACTIVE":
            return DayRow(dt, c.id, c.name, c.country, c.status, 0, 0, 0, 0,
                          0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        nz = lambda v: max(0.0, v * (1.0 + rnd.uniform(-c.noise, c.noise)))

        spend = nz(c.daily_budget * c.bid_mult)
        cpm = nz(c.base_cpm * c.bid_mult)
        impressions = int(spend / cpm * 1000) if cpm > 0 else 0

        # 素材疲劳 + 换素材短期提振
        fatigue = max(0.5, 1.0 - c.fatigue_rate * c.creative_age)
        fresh = 1.0 + c.fresh_lift * math.exp(-c.creative_age / c.fresh_tau)
        ctr_factor = fatigue * fresh
        ctr = nz(c.base_ctr * ctr_factor)
        clicks = int(impressions * ctr)

        # 预算饱和：installs 随 spend 次线性增长（边际 ROI 递减），
        # 同时随素材质量(ctr_factor)线性缩放——换素材短期提升 CTR 即提升 installs/ROI。
        installs = int(c.capacity * ctr_factor * (1.0 - math.exp(-spend / c.sat_k)))
        installs = max(0, nz(installs))
        payers = max(0, int(nz(installs * c.payer_rate)))
        revenue = payers * c.ltv_per_payer

        cpc = spend / clicks if clicks > 0 else 0.0
        cpi = spend / installs if installs > 0 else 0.0
        roi = revenue / spend if spend > 0 else 0.0

        return DayRow(
            date=dt, campaign_id=c.id, campaign_name=c.name, country=c.country,
            status=c.status, impressions=impressions, clicks=clicks,
            installs=installs, payers=payers, spend=round(spend, 2),
            revenue=round(revenue, 2), ctr=round(ctr, 6), cpc=round(cpc, 4),
            cpm=round(cpm, 4), cpi=round(cpi, 4), roi=round(roi, 4),
        )

    def reset(self) -> "SimulationEngine":
        self.campaigns.clear()
        self.adsets.clear()
        self.ads.clear()
        self.history.clear()
        self._today = None
        self.account_status = "ok"
        return self

    def set_account_status(self, status: str) -> None:
        """设置媒体账户状态（演示用：模拟 Meta 被封 / appeal）。"""
        self.account_status = status
