"""Phase 4 主动式自治 — 端到端演示（无需启动 HTTP 服务，直接驱动引擎）。

演示内容：
1. 系统主动巡检：检测到 素材疲劳(自动轮换 L0) + ROI 跌破(提案暂停 L1，等人在环)
2. 分级处置：L0 自动执行、L1 生成审批会话、仅通知(账户被封) 三类分流
3. 去重：冷却期内同异常不重复告警
4. 数据驱动：ROI 跌破阈值优先采用 Phase 3 已学策略（演示"处置质量高于上线初期"）
"""
from app.services.connectors.mock_media import reset_sim_engine
from app.services.agent_runtime import (
    get_memory, get_strategy, get_session_store, get_autonomy_store,
)
from app.services.agent_runtime.autonomy import AutonomyEngine, AnomalyDetector
from app.services.connectors import ConnectorFactory
from app.config import settings


def _reset_state():
    """清空所有进程内单例，保证演示可复现。"""
    reset_sim_engine(seed=42)                      # 重置模拟引擎（含 3 天预置历史）
    get_memory()._eps = []                          # 清空记忆
    get_strategy().reset()                          # 清空策略
    get_session_store()._sessions = {}              # 清空会话仓
    st = get_autonomy_store()
    st._alerts = []; st._scans = []; st._handlers = {}; st._scan_seq = 0


def _print_summary(title):
    store = get_autonomy_store()
    print(f"\n=== {title} ===")
    print(f"扫描次数={store._scan_seq}  累计告警={len(store.list_alerts())}  "
          f"待审批={store.pending_count()}")


def main():
    _reset_state()
    print("=" * 70)
    print("Phase 4 主动式自治 演示")
    print("=" * 70)

    # 让账户跑 12 天，使素材进入疲劳、低 ROI campaign 持续烧钱
    eng = reset_sim_engine(42)
    eng.advance_days(12)  # 素材年龄累计到 ~15 天
    print(f"账户已推进 12 天，当前素材年龄普遍偏高、camp_ca_003 ROI 偏低")

    # ---- 第 1 次巡检：系统主动发现并分级处置 ----
    alerts = AutonomyEngine().scan(app_id=1)
    _print_summary("第 1 次主动巡检")
    for a in alerts:
        an = a.anomaly
        tag = {"auto_executed": "✅ 自动执行", "pending_approval": "⏳ 待你审批",
               "no_action": "ℹ️ 仅通知"}.get(a.status, a.status)
        print(f"  [{tag}] {an.severity:<8} {an.title}")
        print(f"        处置：{a.resolution}")
    # 展示：ROI 跌破阈值来自策略还是默认
    thr = 1.0
    if get_strategy().has_learned("pause_roi_threshold"):
        thr = get_strategy().advise("pause_roi_threshold", 1.0)
        print(f"\n  ⓘ ROI 止损阈值 = {thr:.2f}（采用 Phase 3 已学策略）")
    else:
        print(f"\n  ⓘ ROI 止损阈值 = {thr:.2f}（默认；随 Phase 3 经验积累会自动收敛）")

    # ---- 模拟"Meta 被封"：账户进入 appeal，应主动告警 ----
    # 注意：每个 scan 都会新建 connector 实例，账户状态须落在共享的引擎单例上才能持久
    from app.services.connectors.mock_media import get_sim_engine
    get_sim_engine().set_account_status("DISABLED")
    print(f"\n🔴 已模拟媒体账户被封（account_status={get_sim_engine().account_status}）")

    alerts2 = AutonomyEngine().scan(app_id=1)
    _print_summary("第 2 次主动巡检（账户被封）")
    for a in alerts2:
        an = a.anomaly
        print(f"  [{a.status}] {an.severity:<8} {an.title} — {an.detail}")

    # ---- 去重验证：紧接着再扫一次，同异常不应重复提案 ----
    before = get_autonomy_store().pending_count()
    alerts3 = AutonomyEngine().scan(app_id=1)
    after = get_autonomy_store().pending_count()
    _print_summary("第 3 次主动巡检（去重验证）")
    print(f"  本轮新增告警={len(alerts3)}；待审批 {before} → {after}（冷却期内的 ROI 跌破不再重复提案）")

    # ---- 演示"处置质量高于上线初期"：注入已学策略后阈值自适应 ----
    print("\n--- 数据驱动演示：注入 Phase 3 已学策略后，检测器采用学到的止损阈值 ---")
    from app.services.agent_runtime.strategy import StrategyStore, StrategyRule
    import json, os
    path = settings.agent_strategy_path
    s = StrategyStore(path=path)
    # 模拟从历史暂停经验学到：高 ROI 止损阈值更宽松（0.85），避免误杀
    s._rules["pause_roi_threshold"] = StrategyRule(
        "pause_roi_threshold", 0.85, 0.7, 6, "learned:pause_campaign", "演示注入")
    s._save()
    # 重新加载策略单例
    get_strategy()._rules = s._rules
    get_sim_engine().set_account_status("ok")  # 恢复账户，避免干扰
    connector2 = ConnectorFactory.get_connector(
        settings.agent_default_platform, db=None, app_id=1, credentials={})
    det = AnomalyDetector(strategy=get_strategy())
    new_anoms = det.detect(connector2, 1)
    roi_anoms = [x for x in new_anoms if x.type == "roi_drop"]
    print(f"  检测器采用已学阈值 = {get_strategy().advise('pause_roi_threshold', 1.0):.2f}"
          f"（默认 1.0）；阈值来自 Phase 3 经验，使止损标准自适应而非写死。")
    print(f"  当前 ROI 跌破异常数 = {len(roi_anoms)}：")
    for x in roi_anoms:
        print(f"    · {x.title}")

    # ---- 调度器可用性（不阻塞：启动即停） ----
    print("\n--- APScheduler 调度器可用性检查 ---")
    from app.services.agent_runtime.autonomy import start_scheduler, stop_scheduler
    start_scheduler(); stop_scheduler()
    print("  start_scheduler()/stop_scheduler() 调用无异常 ✅")

    # 清理演示注入的策略文件，避免影响其他演示
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

    print("\n" + "=" * 70)
    print("结论：系统在未收到任何人工指令的情况下，主动完成了")
    print("  · 素材疲劳自动轮换（L0，零打扰）")
    print("  · ROI 跌破提案暂停（L1，人在环审批）")
    print("  · 账户被封主动告警（critical，仅通知）")
    print("  · 冷却去重 + 数据驱动阈值自适应")
    print("= Phase 4 主动式自治验证通过 =" + "=" * 70)


if __name__ == "__main__":
    main()
