"""Reflection —— Phase 2 反思层。

把 EpisodicMemory 中的 Episode 复盘为：
- 自然语言摘要（最近发生了什么）
- 可执行的启发式规则（什么动作在什么情形下有效 / 无效）
- 对新一轮目标的建议（反哺规划，闭环「进化」）

默认走规则引擎（无 LLM 依赖，演示可复现）；若 settings.agent_use_llm_planning
且有可用 LLM，可走 LLM 摘要增强可读性（不阻塞主流程）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.config import settings
from app.services.agent_runtime.memory import EpisodicMemory


class ReflectionResult:
    def __init__(self, summary: str, rules: List[str], episodes_count: int,
                 aggregate: Dict[str, Any]):
        self.summary = summary
        self.rules = rules
        self.episodes_count = episodes_count
        self.aggregate = aggregate

    def to_dict(self) -> Dict[str, Any]:
        return {
            "episodes_count": self.episodes_count,
            "summary": self.summary,
            "rules": self.rules,
            "aggregate": self.aggregate,
        }


class Reflector:
    """把记忆复盘为摘要 + 规则 + 建议。"""

    def reflect(self, memory: EpisodicMemory, goal: Optional[str] = None) -> ReflectionResult:
        eps = memory.recent(50)
        agg = memory.aggregate()
        rules = self._extract_rules(agg)
        summary = self._summarize(eps, agg, goal)
        return ReflectionResult(summary, rules, len(eps), agg)

    # ----------------------------------------------------------------- #
    # 摘要
    # ----------------------------------------------------------------- #
    def _summarize(self, eps: List, agg: Dict[str, Any], goal: Optional[str]) -> str:
        if not eps:
            return "（暂无记忆：Agent 尚未执行过任何写动作，无法复盘。先跑一轮目标吧。）"
        lines = [f"🧠 复盘 {len(eps)} 次动作经历："]
        for action, st in agg.items():
            line = (f"  · {action}: {st['count']} 次，成功率 {st['success_rate']:.0%}，"
                    f"7d 平均ΔROI={st['avg_delta_roi_7d']:+.3f}")
            if st["total_spend_saved"]:
                line += f"，累计止损花费 ≈ {st['total_spend_saved']:.0f}"
            lines.append(line)
        if goal:
            lines.append(f"本轮目标：{goal}")
        return "\n".join(lines)

    # ----------------------------------------------------------------- #
    # 规则提取（核心：把经历凝练成可复用启发式）
    # ----------------------------------------------------------------- #
    def _extract_rules(self, agg: Dict[str, Any]) -> List[str]:
        rules: List[str] = []
        if "pause_campaign" in agg:
            st = agg["pause_campaign"]
            rules.append(
                f"止损规则：暂停低ROI campaign 可立即止血（{st['count']} 次，"
                f"累计止损花费 ≈ {st['total_spend_saved']:.0f}，ΔROI 虽为负但 spend→0，净正向）。"
                f"建议作为「低ROI(<1.0)」的默认处置。")
        if "adjust_budget" in agg:
            st = agg["adjust_budget"]
            avg = st["avg_delta_roi_7d"]
            if avg < 0:
                rules.append(
                    f"预算边际递减：加预算 {st['count']} 次，7d 平均ΔROI={avg:+.3f}"
                    f"（越多花费换越少 ROI），建议增幅收敛至 ≤10%，避免无效扩量。")
            else:
                rules.append(
                    f"预算扩张有效：加预算 {st['count']} 次，7d 平均ΔROI={avg:+.3f}，可保持当前增幅。")
        if "rotate_creative" in agg:
            st = agg["rotate_creative"]
            rules.append(
                f"素材疲劳：换素材 {st['count']} 次，7d 平均ΔROI={st['avg_delta_roi_7d']:+.3f}，"
                f"属短期提振且衰减，建议在素材疲劳（creative_age 偏高）时周期刷新，而非一次性。")
        if "adjust_bid" in agg:
            st = agg["adjust_bid"]
            rules.append(
                f"出价调整：{st['count']} 次，7d 平均ΔROI={st['avg_delta_roi_7d']:+.3f}，"
                f"提价通常伤 ROI，需结合转化质量谨慎使用（L2 审批）。")
        return rules

    # ----------------------------------------------------------------- #
    # 反哺规划：给规划器用的轻量修正
    # ----------------------------------------------------------------- #
    def advise(self, goal: str, memory: EpisodicMemory) -> Dict[str, Any]:
        """返回对「默认决策」的修正（目前聚焦预算增幅收敛）。"""
        return {"budget_increase_cap": memory.suggest_budget_increase_cap()}
