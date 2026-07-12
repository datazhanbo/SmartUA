"""Tool / Skill Registry —— 平台与 Agent Loop 的桥接层。

设计思想（见 docs/AGENTIC_AD_PLATFORM_UPGRADE.md）：
> 平台提供经护栏的工具（读/写），Agent Loop 负责编排与决策。

每个工具带风险元数据（L0-L3）与副作用（read/write）：
- read 工具：Agent 直接调用，用于观察/筛选/预测。
- write 工具 L0：Agent 自动执行（如换素材）。
- write 工具 L1/L2/L3：Agent **只提议**，由 Agent Loop 转为人机审批（人在环）。

写工具通过 `MockMediaConnector`（背后是因果模拟引擎）真实修改状态，并回填
`impact_2h/24h/7d_json`（闭环学习空壳被填上真实——尽管是模拟——数据）。
审计（IntentExecution + ActionLog）在有 DB 时落库，无 DB 时跳过（demo 友好）。
"""
from __future__ import annotations

import os
import re
import uuid
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx
from app.services.intent_engine import RISK_LEVEL_MAP


# --------------------------------------------------------------------------- #
# 上下文：Agent Loop 一次运行所需的依赖
# --------------------------------------------------------------------------- #
class AgentContext:
    """一次 Agent 运行的上下文。db/user 可为 None（无 DB 的 demo 场景）。"""

    def __init__(self, db, user, app_id: int, session, connector, memory=None, strategy=None):
        self.db = db
        self.user = user
        self.app_id = app_id
        self.session = session
        self.connector = connector  # MockMediaConnector（或任何 BaseConnector）
        self.memory = memory       # EpisodicMemory 单例（Phase 2 记忆层，可空）
        self.strategy = strategy   # StrategyStore 单例（Phase 3 策略自演化层，可空）


# --------------------------------------------------------------------------- #
# 工具定义
# --------------------------------------------------------------------------- #
@dataclass
class ToolResult:
    ok: bool
    observation: str
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Tool:
    name: str
    description: str
    risk_level: str          # L0 / L1 / L2 / L3
    side_effect: str         # "read" / "write"
    params_hint: str
    handler: Callable[[Dict[str, Any], AgentContext], ToolResult]


# 工具名 -> 引擎动作 的映射（供 Agent Loop 预测影响）
TOOL_TO_ACTION: Dict[str, Any] = {
    "pause_campaign":   ("update_campaign_status", lambda p: {"status": "PAUSED"}),
    "resume_campaign":  ("update_campaign_status", lambda p: {"status": "ACTIVE"}),
    "adjust_budget":    ("update_campaign_budget", lambda p: {"daily_budget": float(p["daily_budget"])}),
    "adjust_bid":       ("update_adset_bid", lambda p: {"bid_amount": float(p["bid_amount"])}),
    "rotate_creative":  ("rotate_creative", lambda p: {}),
}


# --------------------------------------------------------------------------- #
# 读工具（观察 / 筛选 / 预测）
# --------------------------------------------------------------------------- #
def _observe(params: Dict, ctx: AgentContext) -> ToolResult:
    summary = ctx.connector.current_summary()
    ctx.session.context["summary"] = summary
    if not summary:
        return ToolResult(ok=True, observation="（账户暂无数据）", data={"summary": []})
    lines = [
        f"{s['campaign_id']:<12}{s['country']:<4}{s['status']:<8}"
        f"spend={s['spend']:>7.0f} roi={s['roi']:>5.2f} cpi={s['cpi']:>6.2f}"
        for s in summary
    ]
    obs = "当前账户概览（最新一天）：\n" + "\n".join(lines)
    return ToolResult(ok=True, observation=obs, data={"summary": summary})


def _filter(params: Dict, ctx: AgentContext) -> ToolResult:
    summary = ctx.connector.current_summary()
    max_roi = params.get("max_roi")
    min_roi = params.get("min_roi")
    country = params.get("country")
    status = params.get("status")
    rows = summary
    if max_roi is not None:
        rows = [r for r in rows if r["roi"] <= float(max_roi)]
    if min_roi is not None:
        rows = [r for r in rows if r["roi"] >= float(min_roi)]
    if country:
        rows = [r for r in rows if r["country"] == country]
    if status:
        rows = [r for r in rows if r["status"] == status]
    obs = "筛选结果：\n" + "\n".join(
        f"{r['campaign_id']:<12}{r['country']:<4} roi={r['roi']:>5.2f} spend={r['spend']:.0f}"
        for r in rows
    ) if rows else "（无匹配 campaign）"
    return ToolResult(ok=True, observation=obs, data={"rows": rows})


def _simulate(params: Dict, ctx: AgentContext) -> ToolResult:
    action = params.get("action")
    entity_id = params.get("entity_id")
    ap = params.get("action_params", {})
    horizon = int(params.get("horizon", 3))
    if not action or not entity_id:
        return ToolResult(ok=False, observation="缺少 action / entity_id", data={})
    eff = ctx.connector.simulate_impact(action, entity_id, ap, horizon)
    d_roi = eff.delta_roi
    d_spend = eff.delta_spend
    avg = lambda xs: sum(xs) / len(xs) if xs else 0.0
    obs = (f"动作 {action} 对 {entity_id} 的 {horizon} 天预测影响：\n"
           f"  ΔROI(首日)={d_roi[0] if d_roi else 0:+.3f}，"
           f"7天均值ΔROI={avg(d_roi):+.3f}\n"
           f"  ΔSpend(首日)={d_spend[0] if d_spend else 0:+.1f}")
    return ToolResult(ok=True, observation=obs,
                      data={"delta_roi": d_roi, "delta_spend": d_spend, "delta_cpi": eff.delta_cpi})


def _report(params: Dict, ctx: AgentContext) -> ToolResult:
    summary = ctx.connector.current_summary()
    if not summary:
        return ToolResult(ok=True, observation="（暂无数据可报告）", data={})
    active = [s for s in summary if s["status"] == "ACTIVE"]
    low = [s for s in summary if s["roi"] < 1.0]
    best = max(active, key=lambda s: s["roi"]) if active else None
    worst = min(summary, key=lambda s: s["roi"]) if summary else None
    total_spend = sum(s["spend"] for s in summary)
    obs = (f"诊断报告：活跃 {len(active)} / 共 {len(summary)} 个 campaign，"
           f"总花费 {total_spend:.0f}。\n"
           f"  ⚠️ 低 ROI(<1.0) 待处置：{', '.join(s['campaign_id'] for s in low) or '无'}\n"
           f"  🏆 最优：{best['campaign_id']} (ROI={best['roi']:.2f})\n"
           f"  🔻 最差：{worst['campaign_id']} (ROI={worst['roi']:.2f})")
    return ToolResult(ok=True, observation=obs, data={"summary": summary})


# --------------------------------------------------------------------------- #
# 写工具（真实执行 + 审计 + 影响回采）；L1/L2 由 Loop 转审批，L0 自动执行
# --------------------------------------------------------------------------- #
def _write(ctx: AgentContext, action: str, entity_id: str, ap: Dict,
           risk_level: str, intent_class: str, desc: str, tool_name: str) -> ToolResult:
    """真实执行写动作，并回填 impact_*（闭环学习），同时沉淀为 Episode（Phase 2 记忆）。

    注意顺序：先读动作前快照 + 算影响（control = 动作前状态），再真实 apply。
    否则动作已改变引擎状态，simulate_impact 的对照基线也会变成"已施加动作"的态，导致 Δ 全为 0。
    """
    # 动作前快照（live 状态，尚未被 apply 改变）
    pre = next((s for s in ctx.connector.current_summary()
                if s["campaign_id"] == entity_id), None)
    impact = _compute_impact(ctx, action, entity_id, ap)
    result = ctx.connector.apply_action(action, entity_id, **ap)
    ok = result.get("success", False)

    if ctx.db is not None and ctx.user is not None:
        _record_execution(ctx, intent_class=intent_class, risk_level=risk_level,
                          entity_id=entity_id, ap=ap, action=action, desc=desc,
                          result=result, impact=impact, auto=(risk_level == "L0"))

    # 记忆：把这次经历沉淀为 Episode（闭环学习的核心燃料）
    if ctx.memory is not None:
        from app.services.agent_runtime.memory import Episode
        ctx.memory.record(Episode(
            session_id=getattr(ctx.session, "id", None),
            goal=getattr(ctx.session, "goal", "") or "",
            action=tool_name,
            action_label=desc,
            intent_class=intent_class,
            params={"entity_id": entity_id, **ap},
            pre_state={
                "roi": (pre or {}).get("roi"),
                "spend": (pre or {}).get("spend"),
                "status": (pre or {}).get("status"),
                "country": (pre or {}).get("country"),
            },
            impact=impact,
            outcome=ok,
            note=desc,
        ))

    state = result.get("new_state", result.get("error", ""))
    obs = f"{desc} → {'成功' if ok else '失败'}：{state}"
    return ToolResult(ok=ok, observation=obs, data={"result": result, "impact": impact})


def _pause(params: Dict, ctx: AgentContext) -> ToolResult:
    eid = params["entity_id"]
    return _write(ctx, "update_campaign_status", eid, {"status": "PAUSED"},
                  "L1", "campaign.pause", f"暂停 {eid}（止损）", "pause_campaign")


def _resume(params: Dict, ctx: AgentContext) -> ToolResult:
    eid = params["entity_id"]
    return _write(ctx, "update_campaign_status", eid, {"status": "ACTIVE"},
                  "L1", "campaign.resume", f"恢复 {eid}", "resume_campaign")


def _budget(params: Dict, ctx: AgentContext) -> ToolResult:
    eid = params["entity_id"]
    b = float(params["daily_budget"])
    ap = {"daily_budget": b}
    # 把增幅透传进 Episode，供 Phase 3 策略层挖掘「历史最优增幅」
    if "_pct" in params:
        ap["_pct"] = params["_pct"]
    return _write(ctx, "update_campaign_budget", eid, ap,
                  "L1", "campaign.budget_adjust", f"调整 {eid} 日预算为 {b:.0f}", "adjust_budget")


def _bid(params: Dict, ctx: AgentContext) -> ToolResult:
    eid = params["entity_id"]
    b = float(params["bid_amount"])
    return _write(ctx, "update_adset_bid", eid, {"bid_amount": b},
                  "L2", "campaign.bid_adjust", f"调整 {eid} 出价为 {b:.2f}x", "adjust_bid")


def _rotate(params: Dict, ctx: AgentContext) -> ToolResult:
    eid = params["entity_id"]
    return _write(ctx, "rotate_creative", eid, {},
                  "L0", "creative.rotate", f"为 {eid} 轮换素材（重置疲劳）", "rotate_creative")


# --------------------------------------------------------------------------- #
# 影响评估（回填 impact_*）
# --------------------------------------------------------------------------- #
def _compute_impact(ctx: AgentContext, action: str, entity_id: str,
                    ap: Dict) -> Dict[str, Any]:
    """用引擎的反事实克隆评估动作影响（不污染共享状态）。"""
    try:
        eff = ctx.connector.simulate_impact(action, entity_id, ap, horizon=7)
    except Exception:
        return {}
    d_roi, d_spend, d_cpi = eff.delta_roi, eff.delta_spend, eff.delta_cpi
    avg = lambda xs: round(sum(xs) / len(xs), 4) if xs else 0.0
    return {
        "impact_2h": {
            "delta_roi": round((d_roi[0] if d_roi else 0) * (2 / 24), 4),
            "note": "daily sim; 2h 为线性外推近似",
        },
        "impact_24h": {
            "delta_roi": round(d_roi[0], 4) if d_roi else 0,
            "delta_spend": round(d_spend[0], 2) if d_spend else 0,
            "delta_cpi": round(d_cpi[0], 4) if d_cpi else 0,
        },
        "impact_7d": {
            "avg_delta_roi": avg(d_roi),
            "avg_delta_spend": avg(d_spend),
            "avg_delta_cpi": avg(d_cpi),
        },
    }


def _record_execution(ctx: AgentContext, *, intent_class: str, risk_level: str,
                      entity_id: str, ap: Dict, action: str, desc: str,
                      result: Dict, impact: Dict, auto: bool):
    """审计落库：IntentExecution + ActionLog，并把影响回填到 execution。"""
    from app.models.intent import IntentExecution, ActionLog
    from datetime import datetime as _dt

    execution = IntentExecution(
        app_id=ctx.app_id,
        user_id=ctx.user.id,
        intent_text=ctx.session.goal,
        intent_class=intent_class,
        confidence=1.0,
        risk_level=risk_level,
        parameters_json={**ap, "entity_id": entity_id},
        affected_count=1,
        affected_campaigns_json=[{"id": entity_id}],
        estimated_impact_json={},
        approval_status="auto_executed" if auto else "approved",
        auto_execute_on_timeout=False,
        execution_status="success" if result.get("success") else "failed",
        executed_at=_dt.utcnow(),
        impact_24h_json=impact.get("impact_24h"),
        impact_7d_json=impact.get("impact_7d"),
        impact_2h_json=impact.get("impact_2h"),
    )
    ctx.db.add(execution)
    ctx.db.flush()

    log = ActionLog(
        app_id=ctx.app_id,
        user_id=ctx.user.id,
        intent_execution_id=execution.id,
        action_type=intent_class,
        campaign_id=entity_id,
        reason=desc,
        platform=getattr(ctx.connector, "platform", "mock"),
        platform_response_json=result,
        status="success" if result.get("success") else "failed",
    )
    ctx.db.add(log)
    ctx.db.commit()


# --------------------------------------------------------------------------- #
# 外部检索工具：market_research（真实搜索优先 + 内置行业基准库兜底）
# --------------------------------------------------------------------------- #
# 内置行业基准库（示例数据，覆盖常见品类×国家×渠道）。
# 标注：生产环境应接入 Sensor Tower / AppTweak / 点点数据 / AppsFlyer 等真实数据源。
BENCHMARK_DB: Dict[tuple, Dict[str, float]] = {
    ("ai_video_editor", "US", "Meta"):   {"cpi": 3.2, "cpa": 11.5, "roas": 1.45},
    ("ai_video_editor", "US", "TikTok"): {"cpi": 2.4, "cpa": 9.0,  "roas": 1.60},
    ("ai_video_editor", "US", "Google"): {"cpi": 3.8, "cpa": 13.0, "roas": 1.30},
    ("ai_video_editor", "UK", "Meta"):   {"cpi": 3.5, "cpa": 12.5, "roas": 1.40},
    ("ai_video_editor", "UK", "TikTok"): {"cpi": 2.6, "cpa": 9.8,  "roas": 1.55},
    ("ai_video_editor", "CA", "Meta"):   {"cpi": 3.3, "cpa": 12.0, "roas": 1.42},
    ("ai_video_editor", "JP", "Meta"):   {"cpi": 4.1, "cpa": 15.0, "roas": 1.30},
    ("game", "US", "Meta"):              {"cpi": 4.5, "cpa": 18.0, "roas": 1.20},
    ("game", "US", "TikTok"):            {"cpi": 3.0, "cpa": 12.0, "roas": 1.50},
    ("game", "UK", "Meta"):              {"cpi": 4.8, "cpa": 19.0, "roas": 1.18},
    ("ecommerce", "US", "Meta"):         {"cpi": 2.8, "cpa": 10.0, "roas": 1.80},
    ("ecommerce", "US", "Google"):       {"cpi": 3.0, "cpa": 10.5, "roas": 1.70},
    ("ecommerce", "CA", "Meta"):         {"cpi": 2.9, "cpa": 10.2, "roas": 1.75},
}


def _norm_category(c: Optional[str]) -> Optional[str]:
    if not c:
        return None
    c = c.lower()
    if "video" in c or "剪辑" in c or "editor" in c or "剪映" in c or "capcut" in c:
        return "ai_video_editor"
    if "game" in c or "游戏" in c:
        return "game"
    if "ecom" in c or "电商" in c or "shop" in c or "零售" in c:
        return "ecommerce"
    return None


def _norm_country(co: Optional[str]) -> Optional[str]:
    if not co:
        return None
    co = co.upper()
    return co if co in ("US", "UK", "CA", "JP", "DE", "BR", "AU") else None


def _norm_channel(ch: Optional[str]) -> Optional[str]:
    if not ch:
        return None
    ch = ch.lower()
    if "meta" in ch or "facebook" in ch or " fb" in ch:
        return "Meta"
    if "tiktok" in ch or "tt" in ch:
        return "TikTok"
    if "google" in ch or "adwords" in ch:
        return "Google"
    return None


def _infer_category(query: str) -> Optional[str]:
    return _norm_category(query)


def _web_search(query: str, max_results: int = 3) -> Optional[List[Dict[str, str]]]:
    """真实网络检索（经本地代理出网）。失败/超时/无结果返回 None，由调用方回退基准库。"""
    try:
        q = urllib.parse.quote(query)
        url = f"https://lite.duckduckgo.com/lite/?q={q}"
        proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
        headers = {"User-Agent": "Mozilla/5.0 (compatible; SmartUA/1.0)"}
        with httpx.Client(proxy=proxy, timeout=httpx.Timeout(15.0),
                          trust_env=True, follow_redirects=True) as c:
            r = c.get(url, headers=headers)
            r.raise_for_status()
            html = r.text
        items = []
        blocks = re.findall(
            r'class="result-link"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
            r'class="result-snippet">(.*?)</td>', html, re.S)
        for href, title, snippet in blocks[:max_results]:
            items.append({
                "title": re.sub(r"<[^>]+>", "", title).strip(),
                "url": href,
                "snippet": re.sub(r"<[^>]+>", "", snippet).strip(),
            })
        return items or None
    except Exception:
        return None


def _benchmark_lookup(category, country, channel) -> List[Dict[str, Any]]:
    cat = _norm_category(category)
    cty = _norm_country(country)
    ch = _norm_channel(channel)
    out = []
    for (c, co, chh), m in BENCHMARK_DB.items():
        if cat and c != cat:
            continue
        if cty and co != cty:
            continue
        if ch and chh != ch:
            continue
        out.append({"label": f"{c}/{co}/{chh}", **m})
    # 严格匹配无果但给了品类：放宽国家/渠道，返回该品类全渠道样本
    if not out and cat:
        for (c, co, chh), m in BENCHMARK_DB.items():
            if c == cat:
                out.append({"label": f"{c}/{co}/{chh}", **m})
    return out


def _market_research(params: Dict, ctx: AgentContext) -> ToolResult:
    """跳出平台内部数据，从市场/行业视角获取 CPI/CPA/ROAS 基准与外部检索结果。

    - 真实网络检索优先（经代理）；失败/无结果/无 query 时回退内置行业基准库。
    - 两者都给出，前端与模型即可获得"外部视角"，不再只依赖自有账户。
    """
    query = (params.get("query") or "").strip()
    category = params.get("category") or _infer_category(query)
    country = params.get("country")
    channel = params.get("channel")

    web = _web_search(query) if query else None
    bench = _benchmark_lookup(category, country, channel)

    parts: List[str] = []
    if bench:
        parts.append("【行业基准（内置库 · 示例数据）】")
        for b in bench:
            parts.append(f"  · {b['label']}：CPI≈${b['cpi']}  CPA≈${b['cpa']}  ROAS≈{b['roas']}x")
        parts.append("  ⚠️ 以上为示例行业基准，生产建议接入 Sensor Tower / AppTweak / 点点数据 等真实数据源。")
    if web:
        parts.append("【网络检索结果（实时）】")
        for w in web:
            parts.append(f"  · {w['title']}\n    {w['snippet'][:200]}\n    {w['url']}")
    if not parts:
        obs = f"未找到关于「{query or category}」的行业基准或网络信息。"
    else:
        obs = "\n".join(parts)
    return ToolResult(ok=True, observation=obs, data={"benchmark": bench, "web": web})


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
def _build_registry() -> Dict[str, Tool]:
    return {
        "observe_campaigns": Tool(
            "observe_campaigns", "读取当前账户各 campaign 最新指标（roi/spend/cpi/状态）",
            "L0", "read", "{}", _observe),
        "filter_campaigns": Tool(
            "filter_campaigns", "按 ROI/国家/状态筛选 campaign",
            "L0", "read",
            '{"max_roi":<float>,"min_roi":<float>,"country":<str>,"status":<"ACTIVE"/"PAUSED">}',
            _filter),
        "simulate_impact": Tool(
            "simulate_impact", "预测某动作在未来 N 天对指标的影响（ΔROI/ΔSpend）",
            "L0", "read",
            '{"action":<str>,"entity_id":<str>,"action_params":{},"horizon":<int>}',
            _simulate),
        "generate_report": Tool(
            "generate_report", "生成账户诊断报告（低ROI/最优/最差）",
            "L0", "read", "{}", _report),
        "pause_campaign": Tool(
            "pause_campaign", "暂停指定 campaign（止损）",
            "L1", "write", '{"entity_id":<str>}', _pause),
        "resume_campaign": Tool(
            "resume_campaign", "恢复指定 campaign",
            "L1", "write", '{"entity_id":<str>}', _resume),
        "adjust_budget": Tool(
            "adjust_budget", "调整 campaign 日预算",
            "L1", "write", '{"entity_id":<str>,"daily_budget":<float>}', _budget),
        "adjust_bid": Tool(
            "adjust_bid", "调整 AdSet 出价倍率",
            "L2", "write", '{"entity_id":<str>,"bid_amount":<float>}', _bid),
        "rotate_creative": Tool(
            "rotate_creative", "轮换素材（重置素材疲劳，短期提升 CTR）",
            "L0", "write", '{"entity_id":<str>}', _rotate),
        "market_research": Tool(
            "market_research",
            "跳出平台内部数据，从市场/行业视角检索 CPI/CPA/ROAS 基准与外部信息"
            "（真实网络检索优先，失败时回退内置行业基准库）",
            "L0", "read",
            '{"query":<str>,"category":<"ai_video_editor"/"game"/"ecommerce">,'
            '"country":<"US"/"UK"/"CA"/"JP">,"channel":<"Meta"/"TikTok"/"Google">}',
            _market_research),
    }


class ToolRegistry:
    def __init__(self):
        self._tools = _build_registry()

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def all(self) -> List[Tool]:
        return list(self._tools.values())

    def system_prompt_snippet(self) -> str:
        lines = []
        for t in self._tools.values():
            lines.append(f"- {t.name} [风险:{t.risk_level} | 副作用:{t.side_effect}]\n"
                         f"    描述：{t.description}\n"
                         f"    参数：{t.params_hint}")
        return "\n".join(lines)


_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
