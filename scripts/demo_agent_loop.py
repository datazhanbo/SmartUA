"""Agent Loop 端到端演示（无需真实 LLM / 无需 DB）。

演示目标：一个"模糊的多目标指令"如何被 Agent 拆成多步、对高风险动作走人在环审批、
对低风险动作自动执行、并回填每个动作的影响（闭环学习的数据土壤）。

执行平台：mock 因果模拟引擎（Meta 被封期间的替代数据土壤）。
运行：python scripts/demo_agent_loop.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services.agent_runtime import AgentLoop, AgentContext, get_session_store
from app.services.connectors.mock_media import reset_sim_engine
from app.services.connectors import ConnectorFactory
from app.config import settings


def banner(title: str):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def build_ctx(db=None, user=None, app_id=1):
    """构造 AgentContext（demo 无 DB：审计落库自动跳过）。"""
    reset_sim_engine(42)  # 每次演示都从确定状态开始
    connector = ConnectorFactory.get_connector(
        settings.agent_default_platform, db=db, app_id=app_id, credentials={})
    return AgentContext(db=db, user=user, app_id=app_id, session=None, connector=connector)


def run_with_human(loop: AgentLoop, session, ctx, auto_approve=True):
    """模拟人在环：遇到待审批就打印提议+预测，然后批准/驳回并续跑，直到结束。"""
    while session.status == "awaiting_approval":
        step = session.pending_approval()
        if not step:
            break
        print(f"\n  ⏳ 待审批（{step.risk_level}）: {step.text}")
        pred = step.predicted_impact or {}
        if pred:
            print(f"     预测影响: ΔROI首日={pred.get('delta_roi_first',0):+.3f}, "
                  f"7天均值ΔROI={pred.get('delta_roi_avg7',0):+.3f}, "
                  f"ΔSpend首日={pred.get('delta_spend_first',0):+.1f}")
        decision = "批准" if auto_approve else "驳回"
        print(f"  👤 用户{decision}该动作")
        loop.approve(session, step.id, approved=auto_approve, reason=None, ctx=ctx)
    print("\n  --- 执行时间线 ---")
    for line in session.plan_view():
        print("   " + line)


def print_impacts(session):
    print("\n  --- 已执行动作的影响回采（impact_*） ---")
    for s in session.steps:
        if s.kind == "action" and s.status == "executed":
            imp = (s.result or {}).get("impact", {})
            i24 = imp.get("impact_24h", {})
            i7 = imp.get("impact_7d", {})
            print(f"  • {s.tool} ({s.params.get('entity_id')}): "
                  f"24h ΔROI={i24.get('delta_roi',0):+.3f}, "
                  f"7d 均值ΔROI={i7.get('avg_delta_roi',0):+.3f}")


def scenario_1_full_approve():
    banner("场景 1：模糊多目标 → 拆多步 + 人在环（全部批准）")
    goal = ("把 ROI 低于 1.0 的 campaign 暂停，给 ROI 最高的 campaign 加 20% 预算，"
            "并给表现最差的 campaign 换素材")
    print(f"用户目标：{goal}\n")
    ctx = build_ctx()
    loop = AgentLoop()
    store = get_session_store()
    session = store.create(app_id=1, user_id=1, goal=goal)
    ctx.session = session
    loop.start(session, ctx)
    run_with_human(loop, session, ctx, auto_approve=True)
    print_impacts(session)
    print(f"\n最终结论:\n{session.steps[-1].text}")


def scenario_2_analysis_only():
    banner("场景 2：纯分析目标 → 无审批，直接出诊断报告")
    goal = "分析一下当前账户并生成诊断报告"
    print(f"用户目标：{goal}\n")
    ctx = build_ctx()
    loop = AgentLoop()
    store = get_session_store()
    session = store.create(app_id=1, user_id=1, goal=goal)
    ctx.session = session
    loop.start(session, ctx)
    for line in session.plan_view():
        print("   " + line)
    print(f"\n最终结论:\n{session.steps[-1].text}")


def scenario_3_reject_branch():
    banner("场景 3：驳回高风险动作 → 重新规划（不重复提议被驳动作）")
    goal = "把 ROI 低于 1.0 的 campaign 暂停"
    print(f"用户目标：{goal}\n")
    ctx = build_ctx()
    loop = AgentLoop()
    store = get_session_store()
    session = store.create(app_id=1, user_id=1, goal=goal)
    ctx.session = session
    loop.start(session, ctx)
    # 第一次遇到审批 → 驳回
    step = session.pending_approval()
    print(f"\n  ⏳ 待审批: {step.text}")
    print("  👤 用户驳回该动作（理由：先观察一天）")
    loop.approve(session, step.id, approved=False, reason="先观察一天", ctx=ctx)
    print("\n  --- 驳回后 Agent 重新规划的时间线 ---")
    for line in session.plan_view():
        print("   " + line)
    print(f"\n最终结论:\n{session.steps[-1].text}")


if __name__ == "__main__":
    print("SmartUA Agent Loop 演示（执行平台 =", settings.agent_default_platform,
          "| LLM 规划 =", settings.agent_use_llm_planning, "）")
    scenario_1_full_approve()
    scenario_2_analysis_only()
    scenario_3_reject_branch()
    banner("演示结束")
    print("说明：本环境未配置 LLM API Key，决策走规则引擎兜底；配置后 Agent Loop 会自动")
    print("切换为 LLM 规划（ReAct JSON 解析），工具清单与风险护栏完全一致。")
