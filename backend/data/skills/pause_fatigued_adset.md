---
name: pause_fatigued_adset
description: 素材疲劳且 ROI 走低的 AdSet 先暂停止损，再考虑换素材而非直接提价
target_tool: pause_adset
when: evaluate_creative 返回 health=fatigued 且该 adset ROI < 1.0
---

执行流程：

1. 调 `observe_adsets` 列出低 ROI（< 1.0）的 AdSet。
2. 对每个候选调 `evaluate_creative`：
   - 若 `health=fatigued` 且 `suggested_action=rotate_creative`，**优先提议 `rotate_creative`**（L0 自动），而不是暂停。
   - 若 `health=underperforming` 且持续 3 天以上，提议 `pause_adset`（L1，需用户确认）。
3. 不要对同一 AdSet 同时提议暂停和换素材——先换素材观察 24h，再决定是否暂停。

这个 skill 不改变 `pause_adset` 的 L1 风险分级；它只指导"什么时候该提议它"。
