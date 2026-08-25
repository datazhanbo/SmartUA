"""规则引擎兜底规划器 + 提案/摘要辅助。

从 loop.py 迁出，保持纯函数形态，便于测试和替换。
LLM 规划路径仍留在 loop._llm_decide（不改 LLM 调用方式）。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.agent_runtime.loop import Decision
    from app.services.agent_runtime.session import AgentSession
    from app.services.agent_runtime.tools import AgentContext, Tool


def propose_text(tool: "Tool", params: Dict[str, Any]) -> str:
    eid = params.get("entity_id", "?")
    if tool.name == "pause_campaign":
        return f"暂停 {eid}（止损，L1 需确认）"
    if tool.name == "resume_campaign":
        return f"恢复 {eid}（L1 需确认）"
    if tool.name == "adjust_budget":
        return f"调整 {eid} 日预算 → {float(params.get('daily_budget', 0)):.0f}（L1 需确认）"
    if tool.name == "adjust_bid":
        return f"调整 {eid} 出价 → {float(params.get('bid_amount', 0)):.2f}x（L2 需确认）"
    return f"{tool.name}({params})"


def extract_roi_threshold(goal: str) -> Optional[float]:
    m = re.search(r'roi\s*(低于|小于|<|低)\s*([0-9.]+)', goal)
    if not m:
        m = re.search(r'([0-9.]+)\s*以下', goal)
    if m:
        try:
            return float(m.group(2) if m.group(1) in ("低于", "小于", "<", "低") else m.group(1))
        except (ValueError, TypeError):
            return None
    return None


def extract_pct(goal: str) -> Optional[float]:
    m = re.search(r'([0-9]+)\s*%', goal)
    if m:
        try:
            return float(m.group(1))
        except (ValueError, TypeError):
            return None
    m = re.search(r'增加\s*([0-9.]+)', goal)
    if m:
        try:
            return float(m.group(1))
        except (ValueError, TypeError):
            return None
    return None


def extract_country(goal: str) -> Optional[str]:
    mapping = {"美国": "US", "美区": "US", "us": "US", "日本": "JP", "jp": "JP",
               "英国": "UK", "uk": "UK", "德国": "DE", "de": "DE",
               "加拿大": "CA", "ca": "CA", "巴西": "BR", "br": "BR"}
    for k, v in mapping.items():
        if k in goal:
            return v
    return None


def final_summary(session: "AgentSession", ctx: "AgentContext") -> str:
    from app.services.agent_runtime.session import AgentStepKind, AgentStepStatus
    summary = ctx.connector.current_summary()
    executed = [s for s in session.steps
                if s.kind == AgentStepKind.ACTION.value and s.status == AgentStepStatus.EXECUTED.value]
    proposed = [s for s in session.steps
                if s.kind == AgentStepKind.APPROVAL.value and s.status == AgentStepStatus.PROPOSED.value]
    lines = ["✅ 已执行动作："]
    lines += [f"  - {s.text}" for s in executed] or ["  （无）"]
    if proposed:
        lines.append("⏳ 待你审批：")
        lines += [f"  - {s.text}" for s in proposed]
    lines.append("📊 当前账户：")
    for s in summary:
        r = s.get("roi")
        roi_s = f"{r:.2f}" if isinstance(r, (int, float)) else "N/A"
        lines.append(f"  {s['campaign_id']:<12}{s['country']:<4}{s['status']:<8}"
                     f"roi={roi_s:<6}spend={s['spend']:.0f}")
    if not summary:
        lines.append("  （无数据）")
    return "\n".join(lines)


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    try:
        s = text.find("{")
        e = text.rfind("}") + 1
        if s >= 0 and e > s:
            return json.loads(text[s:e])
    except Exception:
        return None
    return None


def rule_based_decide(session: "AgentSession", ctx: "AgentContext") -> "Decision":
    """确定性规划：暂停低 ROI / 给高 ROI 加预算 / 换素材 / 出报告。

    作为无 LLM 或 LLM 异常时的兜底，逻辑与原 loop._rule_based_decide 完全一致。
    """
    from app.services.agent_runtime.loop import Decision

    goal = session.goal.lower()
    summary = ctx.connector.current_summary()
    done = session.context.setdefault("done", [])
    rejected = session.context.get("rejected", [])
    active = [s for s in summary if s["status"] == "ACTIVE"]

    # 1) 暂停低 ROI
    if any(k in goal for k in ("暂停", "pause", "停掉", "下线", "关掉")) and "lowroi_pause" not in done:
        if ctx.strategy is not None and ctx.strategy.has_learned("pause_roi_threshold"):
            threshold = ctx.strategy.advise("pause_roi_threshold", 1.0)
        else:
            threshold = extract_roi_threshold(goal) or 1.0
        country = extract_country(goal)
        targets = [s for s in summary if s.get("roi") is not None and s["roi"] < threshold
                   and s["status"] == "ACTIVE"
                   and (not country or s["country"] == country)
                   and ("pause_campaign", s["campaign_id"]) not in rejected]
        if targets:
            t = targets[0]
            remain = [x for x in targets if x["campaign_id"] != t["campaign_id"]]
            if not remain:
                done.append("lowroi_pause")
            note = f"（另有 {len(remain)} 个待处置）" if remain else ""
            return Decision(
                action="pause_campaign", params={"entity_id": t["campaign_id"]},
                thought=f"目标含'暂停低ROI'。{t['campaign_id']} ROI={t['roi']:.2f}<{threshold}，"
                        f"提议暂停止损{note}")
        done.append("lowroi_pause")

    # 2) 给高 ROI 加预算
    if any(k in goal for k in ("加预算", "预算", "budget", "增加预算", "提量", "放量", "加量")) and "highroi_budget" not in done:
        if active and any(k in goal for k in ("高", "roi", "top", "提", "优", "最好")):
            top = max(active, key=lambda s: s["roi"])
            if ("adjust_budget", top["campaign_id"]) not in rejected:
                inc = extract_pct(goal) or 20
                learned = False
                learn_src = ""
                if ctx.strategy is not None and ctx.strategy.has_learned("budget_increase_cap"):
                    cap = ctx.strategy.advise("budget_increase_cap", inc)
                    learn_src = "策略"
                elif ctx.memory is not None:
                    cap = ctx.memory.suggest_budget_increase_cap(default_cap=inc)
                    learn_src = "记忆" if cap < inc else ""
                else:
                    cap = inc
                if cap < inc:
                    inc, learned = cap, True
                camp = getattr(ctx.connector, "engine", None)
                cur_b = None
                if camp is not None:
                    c = camp.campaigns.get(top["campaign_id"])
                    cur_b = c.daily_budget if c else None
                if cur_b:
                    new_b = round(cur_b * (1 + inc / 100), 2)
                    done.append("highroi_budget")
                    learn_note = (f"（{learn_src}收敛：历史加预算边际递减，增幅已收敛至 +%.0f%%）" % inc) if learned else ""
                    return Decision(
                        action="adjust_budget",
                        params={"entity_id": top["campaign_id"], "daily_budget": new_b, "_pct": inc},
                        thought=f"目标含'给高ROI加预算'。{top['campaign_id']} ROI 最高({top['roi']:.2f})，"
                                f"提议日预算 +{inc}% → {new_b:.0f}{learn_note}")
        done.append("highroi_budget")

    # 3) 换素材
    if any(k in goal for k in ("换素材", "creative", "素材", "疲劳", "下滑", "衰退")) and "rotate_creative" not in done:
        worst = min(active, key=lambda s: s["roi"]) if active else None
        if worst and ("rotate_creative", worst["campaign_id"]) not in rejected:
            done.append("rotate_creative")
            return Decision(
                action="rotate_creative", params={"entity_id": worst["campaign_id"]},
                thought=f"目标含'换素材'。{worst['campaign_id']} ROI 最低({worst['roi']:.2f})、素材最疲劳，"
                        f"提议轮换（L0 自动执行）")
        done.append("rotate_creative")

    # 4) 分析 / 报告
    if any(k in goal for k in ("报告", "report", "分析", "诊断", "看看", "查一下", "状态")) and "report" not in done:
        done.append("report")
        return Decision(action="generate_report", params={},
                        thought="目标为分析/报告，调用 generate_report")

    return Decision(final=True, text=final_summary(session, ctx))
