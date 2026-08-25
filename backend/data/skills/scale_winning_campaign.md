---
name: scale_winning_campaign
description: 给高 ROI campaign 小幅加预算（默认 +20%，不超过预算护栏），而不是一次性翻倍
target_tool: adjust_budget
params:
  _pct: 0.20
when: 用户要求"放量/scale/加预算"，且目标 campaign 的 ROI 高于账户均值
---

执行流程：

1. 先用 `observe_campaigns` 找到 ROI ≥ 1.5 且状态 ACTIVE 的 campaign。
2. 用 `simulate_impact` 预测 +20% 预算的 7 天影响（ΔROI 不应显著为负）。
3. 调用 `adjust_budget`，`daily_budget = 当前预算 × 1.20`。
   - 若触发 BudgetGuard（增幅超 50%），先向用户说明并请求确认是否分多步加。
4. 加预算后在下一轮观察 spend 是否真的上涨、ROI 是否保持。

参数 `_pct=0.20` 会被 StrategyStore 学到的 `budget_increase_cap` 覆盖——若历史最优增幅更低，以策略为准。
