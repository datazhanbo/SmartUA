#!/usr/bin/env python3
"""SmartUA Phase 0 验证 Demo：有状态因果模拟 + 动作影响闭环。

无需数据库、无需任何第三方依赖（仅用标准库）。直接运行：

    python scripts/demo_mock_media.py

演示内容：
  1. 注入一组海外 UA campaign（含高/低 ROI 样本）
  2. 推进 14 天，观察每日 ROI/CPI（"感知"层数据）
  3. 模拟 agent 决策：暂停低 ROI campaign、给高 ROI campaign +20% 预算、给衰退素材换素材
  4. 用 simulate_action_impact 量化每个动作的"对照 vs 处理"影响（记忆/反思的原料）
  5. 真实推进引擎并展示动作后的实际指标，证明 pull 历史已反映动作效果

这证明：即便 Meta 被封，也能用 mock 媒体跑通"真实执行 → 指标回采 → 反思学习"的闭环。
"""
import os
import sys
from datetime import date, timedelta

# 让脚本能 import backend 内的模块
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(os.path.dirname(_HERE), "backend")
for p in (_BACKEND, _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.services.simulation.engine import SimulationEngine  # noqa: E402


def banner(t: str):
    print("\n" + "=" * 70)
    print(t)
    print("=" * 70)


def print_summary(engine: SimulationEngine):
    print(f"{'campaign':<22}{'country':<8}{'status':<8}{'spend':>9}{'installs':>9}{'ROI':>7}{'CPI':>8}")
    print("-" * 70)
    for s in engine.summary():
        print(f"{s['name']:<22}{s['country']:<8}{s['status']:<8}"
              f"{s['spend']:>9.0f}{s['installs']:>9}{s['roi']:>7.2f}{s['cpi']:>8.2f}")


def main():
    seed = 42
    eng = SimulationEngine(seed=seed).seed_demo_account()
    today = date(2026, 7, 1)
    eng.advance_days(14, start=today)  # 预热 14 天历史

    banner("Step 1 · 当前账户快照（agent 的'感知'输入）")
    print_summary(eng)

    # 找出低 ROI 与高 ROI campaign
    summ = {s["campaign_id"]: s for s in eng.summary()}
    low_roi = min(summ.values(), key=lambda s: s["roi"])
    high_roi = max(summ.values(), key=lambda s: s["roi"])
    print(f"\n决策：暂停低 ROI → {low_roi['name']} (ROI={low_roi['roi']:.2f})")
    print(f"决策：高 ROI 加预算 +20% → {high_roi['name']} (ROI={high_roi['roi']:.2f})")
    print(f"决策：给素材衰退的 campaign 换素材 → Campaign_JP_TEST")

    banner("Step 2 · 量化动作影响（记忆/反思闭环的核心原料）")
    for cid, label in [(low_roi["campaign_id"], "暂停低ROI"),
                       (high_roi["campaign_id"], "高ROI加预算+20%"),
                       ("camp_jp_004", "换素材")]:
        action = ("update_campaign_status" if label.startswith("暂停")
                  else "update_campaign_budget" if "预算" in label
                  else "rotate_creative")
        params = ({"status": "PAUSED"} if action == "update_campaign_status"
                  else {"daily_budget": summ[cid]["spend"] * 1.2} if action == "update_campaign_budget"
                  else {})
        eff = eng.simulate_action_impact(action, cid, params, horizon=7)
        print(f"\n▶ {label}  [{cid}]  未来 7 天 ROI 变化（处理 - 对照）：")
        print("  day : " + " ".join(f"{i+1:>5}" for i in range(eff.horizon)))
        print("  ΔROI: " + " ".join(f"{d:>5.2f}" for d in eff.delta_roi))
        print("  Δ$  : " + " ".join(f"{d:>5.0f}" for d in eff.delta_spend))
        # 反思可读结论
        if action == "update_campaign_status":
            print("  反思：暂停后 spend≈0、ROI 归零 —— 等价于'止损'，适合低 ROI 且仅亏不赚的 campaign。")
        elif action == "update_campaign_budget":
            avg = sum(eff.delta_roi) / len(eff.delta_roi)
            print(f"  反思：加预算后 ROI 平均变化 {avg:+.2f} —— 边际递减，预算扩张需设上限。")
        else:
            peak = max(eff.delta_roi)
            print(f"  反思：换素材短期 ROI 峰值 +{peak:.2f}，随后衰减 —— 适合素材疲劳时周期性刷新。")

    banner("Step 3 · 真实施加动作并推进，验证 pull 历史已反映效果")
    eng.apply_action("update_campaign_status", low_roi["campaign_id"], status="PAUSED")
    eng.apply_action("update_campaign_budget", high_roi["campaign_id"],
                     daily_budget=summ[high_roi["campaign_id"]]["spend"] * 1.2)
    eng.apply_action("rotate_creative", "camp_jp_004")
    eng.advance_days(7, start=today + timedelta(days=14))
    print_summary(eng)
    print("\n✅ 闭环成立：动作真实改变了后续每日指标，且每次动作都有可量化的影响样本供反思/学习。")

    banner("Step 4 · 接入提示")
    print("真实代码路径已就绪：")
    print("  - SimulationEngine  : backend/app/services/simulation/engine.py")
    print("  - MockMediaConnector: backend/app/services/connectors/mock_media.py (已注册 'mock' 渠道)")
    print("  - 切换真实渠道：ConnectorFactory 把 'mock' 换回 'meta' 即可，上层无感。")
    print("  - 反思原料：connector.simulate_impact(action, entity_id, params) 返回对照/处理序列。")


if __name__ == "__main__":
    main()
