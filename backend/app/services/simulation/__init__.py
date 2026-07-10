"""有状态、可因果、可复现的投放模拟引擎。

该引擎为 SmartUA 的"进化闭环"（记忆-反思-学习）提供真实可控的数据土壤：
- 有状态：campaign 的预算/出价/状态/素材年龄持久化，动作会真正改变后续指标
- 可因果：指标由状态经响应曲线生成，pause/budget/bid/rotate 各自有可解释效果
- 可复现：给定 seed，序列完全确定，便于回归测试与 agent 实验复现

注意：这是 mock 媒体（替代当前被封的 Meta），但区别于旧 mock 的"无状态随机"——
本引擎让"agent 动作 → 未来指标"形成闭环，是 Phase 0/2/3 验证的前提。
"""

from .engine import (
    CampaignState,
    DayRow,
    SimulationEngine,
    ActionEffect,
)

__all__ = ["CampaignState", "DayRow", "SimulationEngine", "ActionEffect"]
