"""Strategy Store —— Phase 3 策略自演化层。

把 Phase 2 沉淀的 Episode 记忆「编译」成**可查询、可复用、可持久**的策略参数，
使规划器从「硬编码默认值」升级为「数据驱动的策略」：

- learn_from_memory(memory): 从 Episode 中挖掘最优参数
    · budget_increase_cap     加预算增幅上限（边际递减 → 收敛）
    · pause_roi_threshold     低 ROI 暂停阈值（从成功止损的最高 ROI 反推）
    · rotate_when_roi_below   换素材触发 ROI 下限（从有效轮换的最低 ROI 反推）
- advise(key, default): 返回学到的参数；无/低置信度时回退默认（优雅降级）
- to_json / from_json + 落盘：解决 Phase 2「重启即失」风险，策略可跨进程 / 跨账户迁移

这是「进化能力」的收口：Phase 1 规划 → Phase 2 记忆/反思 → Phase 3 把经验固化为
可复用的策略参数，新账户/重启后无需重新踩坑。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import settings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StrategyRule:
    """一条可学习策略参数。"""
    key: str
    value: float
    confidence: float = 0.0       # 0~1：依样本量与一致度
    n_samples: int = 0
    source: str = ""              # 如 "learned:adjust_budget"
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StrategyLearnResult:
    rules: Dict[str, StrategyRule]
    learned_keys: List[str]
    note: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "learned_keys": self.learned_keys,
            "note": self.note,
            "rules": {k: v.to_dict() for k, v in self.rules.items()},
        }


class StrategyStore:
    def __init__(self, path: Optional[str] = None):
        self.path = path
        self._rules: Dict[str, StrategyRule] = {}
        if path and os.path.exists(path):
            self._load()

    # ----------------------------------------------------------------- #
    # 查询（规划器用）：学到的策略优先，默认兜底
    # ----------------------------------------------------------------- #
    def advise(self, key: str, default: float) -> float:
        r = self._rules.get(key)
        if r is None:
            return default
        return r.value

    def has_learned(self, key: str, min_conf: float = 0.3) -> bool:
        r = self._rules.get(key)
        return r is not None and r.confidence >= min_conf

    def all(self) -> Dict[str, StrategyRule]:
        return dict(self._rules)

    # ----------------------------------------------------------------- #
    # 学习：从 Episode 记忆挖掘策略参数
    # ----------------------------------------------------------------- #
    def learn_from_memory(self, memory, min_samples: int = 1) -> StrategyLearnResult:
        """Phase 4.3 —— 只从 usable_for_learning=True 的 Episode 学习。

        样本门禁：Episode 必须
        (1) execution_mode == "live"（Mock/Sandbox 永不进策略）；
        (2) data_quality.impact_kind ∈ {observed, attributed}（predicted 只是模型猜测，不算真凭据）；
        (3) completeness > 0（延迟回采到过真实数据）。
        以上三条由 EpisodicMemory.promote_usable_for_learning 在回采完成后统一提权。

        若没有可用样本 → 不修改任何策略，返回明确的 note 说明。
        """
        usable_getter = getattr(memory, "usable_episodes", None)
        eps = usable_getter() if callable(usable_getter) else [
            e for e in memory.all() if getattr(e, "usable_for_learning", False)
        ]
        if not eps:
            return StrategyLearnResult(
                dict(self._rules), [],
                "无可用真实样本：仅有 Mock/Sandbox 或 predicted-only Episode，策略保持不变。"
            )
        learned: Dict[str, StrategyRule] = {}
        notes: List[str] = []

        # 1) 加预算增幅上限
        budget_eps = [e for e in eps if e.action == "adjust_budget"]
        if len(budget_eps) >= min_samples:
            pcts = [e.params.get("_pct") for e in budget_eps if e.params.get("_pct") is not None]
            avg7 = sum(e.avg_delta_roi_7d() for e in budget_eps) / len(budget_eps)
            if avg7 < 0:
                cap = 10.0
                note = (f"加预算 {len(budget_eps)} 次，7d 平均ΔROI={avg7:+.3f}<0，"
                        f"边际递减明显，增幅收敛至 {cap:.0f}%")
            else:
                best = max(budget_eps, key=lambda e: e.avg_delta_roi_7d())
                cap = float(best.params.get("_pct", 20))
                note = (f"加预算 {len(budget_eps)} 次，7d 平均ΔROI={avg7:+.3f}≥0，"
                        f"保留历史最优增幅 {cap:.0f}%")
            conf = round(min(1.0, len(budget_eps) / 5.0), 2)
            learned["budget_increase_cap"] = StrategyRule(
                "budget_increase_cap", cap, conf, len(budget_eps),
                "learned:adjust_budget", _now())
            notes.append(note)

        # 2) 暂停 ROI 阈值：从成功止损的最高 ROI 反推
        pause_eps = [e for e in eps if e.action == "pause_campaign"]
        if len(pause_eps) >= min_samples:
            rois = [e.pre_state.get("roi") for e in pause_eps
                    if e.pre_state.get("roi") is not None]
            if rois:
                threshold = min(max(rois), 2.0)   # 成功止血过的最高 ROI，封顶 2.0
                conf = round(min(1.0, len(pause_eps) / 5.0), 2)
                learned["pause_roi_threshold"] = StrategyRule(
                    "pause_roi_threshold", float(threshold), conf, len(pause_eps),
                    "learned:pause_campaign", _now())
                notes.append(f"暂停 {len(pause_eps)} 次成功止血，最高 ROI={threshold:.2f}，阈值参考 {threshold:.2f}")

        # 3) 换素材触发 ROI 下限：从有效轮换的最低 ROI 反推
        rot_eps = [e for e in eps if e.action == "rotate_creative"]
        if len(rot_eps) >= min_samples:
            rois = [e.pre_state.get("roi") for e in rot_eps
                    if e.pre_state.get("roi") is not None]
            if rois:
                low = min(rois)
                conf = round(min(1.0, len(rot_eps) / 5.0), 2)
                learned["rotate_when_roi_below"] = StrategyRule(
                    "rotate_when_roi_below", float(low), conf, len(rot_eps),
                    "learned:rotate_creative", _now())
                notes.append(f"换素材 {len(rot_eps)} 次，最低触发 ROI={low:.2f}")

        for k, r in learned.items():
            self._rules[k] = r
        self._save()
        head = f"[usable={len(eps)} 条真实样本] "
        joined = "；".join(notes) or "无新学习"
        return StrategyLearnResult(self._rules, list(learned.keys()), head + joined)

    # ----------------------------------------------------------------- #
    # 持久化（落盘，跨进程迁移）
    # ----------------------------------------------------------------- #
    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._rules = {k: StrategyRule(**v) for k, v in data.get("rules", {}).items()}
        except Exception:
            self._rules = {}

    def _save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"rules": {k: v.to_dict() for k, v in self._rules.items()}},
                      f, ensure_ascii=False, indent=2)

    def reset(self) -> None:
        self._rules = {}
        self._save()


_strategy: Optional[StrategyStore] = None


def get_strategy() -> StrategyStore:
    """全局策略单例（落盘路径由 settings.agent_strategy_path 指定）。"""
    global _strategy
    if _strategy is None:
        _strategy = StrategyStore(path=getattr(settings, "agent_strategy_path", None))
    return _strategy
