"""Episodic Memory —— Phase 2 记忆层。

把 Agent 每一次「写动作」及其影响（impact_*）沉淀为 Episode，供 Reflection 模块
复盘、提取启发式规则，并反哺规划（让 Agent 越做越准）。

设计要点：
- 进程内单例（与 SessionStore / 模拟引擎同源），跨会话持久 —— 这正是「跨任务学习」的载体：
  Agent 在本周 A 账户上踩过的坑，下周换 B 账户时仍能调用。
- 无 DB 依赖（演示友好）；生产应落库为 EpisodicMemory 表（见 docs/CHANGELOG 风险项）。
- 同时被 tools._write（执行后记录）与 loop（规划前 consult / 终态 reflect）消费。

Episode 字段说明：
- pre_state：动作前该 campaign 的局部快照（roi/spend/status/country），用于复盘「当时情形」。
- impact   ：来自 tools._compute_impact 的 impact_2h/24h/7d_json，即动作的反事实因果效应。
- outcome  ：动作是否成功执行。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Episode:
    episode_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    timestamp: str = field(default_factory=_now)
    session_id: Optional[str] = None
    goal: str = ""
    action: str = ""            # 工具名，如 "adjust_budget"（用于聚合分组）
    action_label: str = ""      # 人类可读，如 "调整日预算"
    intent_class: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    pre_state: Dict[str, Any] = field(default_factory=dict)   # 动作前账户局部快照
    impact: Dict[str, Any] = field(default_factory=dict)      # impact_2h/24h/7d
    outcome: bool = True
    note: str = ""

    # --- 便捷取值（供聚合/反思） ---
    def delta_roi_24h(self) -> float:
        return float((self.impact.get("impact_24h") or {}).get("delta_roi", 0) or 0)

    def avg_delta_roi_7d(self) -> float:
        return float((self.impact.get("impact_7d") or {}).get("avg_delta_roi", 0) or 0)

    def delta_spend_24h(self) -> float:
        return float((self.impact.get("impact_24h") or {}).get("delta_spend", 0) or 0)


class EpisodicMemory:
    """进程内 Episode 仓库（跨会话持久）。"""

    def __init__(self):
        self._eps: List[Episode] = []

    def record(self, ep: Episode) -> Episode:
        self._eps.append(ep)
        return ep

    def all(self) -> List[Episode]:
        return list(self._eps)

    def recent(self, n: int = 50) -> List[Episode]:
        return self._eps[-n:]

    def by_action(self, action: str) -> List[Episode]:
        return [e for e in self._eps if e.action == action]

    def has_experience(self, action: str) -> bool:
        return len(self.by_action(action)) > 0

    # ----------------------------------------------------------------- #
    # 聚合统计：反思与规划的基础
    # ----------------------------------------------------------------- #
    def aggregate(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for action in {e.action for e in self._eps}:
            eps = self.by_action(action)
            n = len(eps)
            succ = sum(1 for e in eps if e.outcome)
            out[action] = {
                "count": n,
                "success_rate": round(succ / n, 3) if n else 0.0,
                "avg_delta_roi_24h": round(sum(e.delta_roi_24h() for e in eps) / n, 4) if n else 0.0,
                "avg_delta_roi_7d": round(sum(e.avg_delta_roi_7d() for e in eps) / n, 4) if n else 0.0,
                "avg_delta_spend_24h": round(sum(e.delta_spend_24h() for e in eps) / n, 2) if n else 0.0,
                "total_spend_saved": round(sum(
                    (e.pre_state.get("spend", 0) or 0) for e in eps
                    if e.action == "pause_campaign"), 2),
            }
        return out

    # ----------------------------------------------------------------- #
    # 反哺规划：把「经历」转成「决策修正」
    # ----------------------------------------------------------------- #
    def suggest_budget_increase_cap(self, default_cap: float = 20.0,
                                    roi_threshold: float = 0.0) -> float:
        """从过去「加预算」动作中学习增幅上限（边际递减 → 更保守）。

        若历史加预算的 7d 平均 ΔROI 转负（越多花费换越少 ROI），说明边际递减已现，
        将默认增幅收敛到 ≤10%，避免无效扩量。无历史则返回默认上限。
        """
        eps = self.by_action("adjust_budget")
        if not eps:
            return default_cap
        avg = sum(e.avg_delta_roi_7d() for e in eps) / len(eps)
        return default_cap if avg >= roi_threshold else min(default_cap, 10.0)


_memory: Optional[EpisodicMemory] = None


def get_memory() -> EpisodicMemory:
    """全局记忆单例（与 SessionStore / 模拟引擎同源，跨会话持久）。"""
    global _memory
    if _memory is None:
        _memory = EpisodicMemory()
    return _memory
