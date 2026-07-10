"""Phase 2 演示：记忆 + 反思闭环（Agent 如何"越做越准"）。

场景A：模糊多目标 → Agent 拆步执行（人在环批准 L1）→ 每次写动作沉淀为 Episode
场景B：反思 → 提取启发式规则（如"加预算边际递减，增幅收敛≤10%"）
场景C：新账户 + 类似目标 → 规划器 consult 记忆，自动收敛预算增幅（学习生效）

运行：python scripts/demo_phase2.py  （无需 DB / 第三方包，系统 Python 即可）
"""
from app.config import settings
from app.services.connectors import ConnectorFactory
from app.services.connectors.mock_media import reset_sim_engine
from app.services.agent_runtime import (
    AgentLoop, AgentContext, get_session_store, get_memory,
)


def make_connector():
    # 每次取新实例，绑定当前（可能已 reset）的引擎单例
    return ConnectorFactory.get_connector("mock", db=None, app_id=1, credentials={})


def make_ctx(connector):
    return AgentContext(db=None, user=None, app_id=1, session=None,
                        connector=connector, memory=get_memory())


def run_goal(goal: str, connector, label: str):
    store = get_session_store()
    loop = AgentLoop()
    session = store.create(app_id=1, user_id=1, goal=goal)
    ctx = make_ctx(connector)
    ctx.session = session
    session = loop.start(session, ctx)

    # 模拟"人在环"：自动批准所有待审批的高风险动作
    guard = 0
    while session.status == "awaiting_approval" and guard < 12:
        pend = session.pending_approval()
        if not pend:
            break
        session = loop.approve(session, pend.id, approved=True,
                               reason="demo 自动批准", ctx=ctx)
        guard += 1

    print(f"\n{'=' * 72}\n{label}：{goal}\n{'=' * 72}")
    for s in session.plan_view():
        print("  " + s)
    return session


def main():
    mem = get_memory()
    print("# Phase 2 · 记忆 / 反思闭环演示（Agent 越做越准）")

    # ---- 场景A：多目标执行，沉淀 Episode ----
    reset_sim_engine(42)
    conn_a = make_connector()
    run_goal("把低 ROI 的暂停，给高 ROI 加 20% 预算，换掉最差的素材",
             conn_a, "场景A · 多目标执行（经历沉淀）")

    # ---- 场景B：反思 ----
    print(f"\n{'=' * 72}\n场景B · 复盘（基于 {len(mem.all())} 条 Episode 记忆）\n{'=' * 72}")
    res = AgentLoop().reflect(make_ctx(conn_a))
    print(res.summary)
    print("\n📌 提取的启发式规则：")
    for r in res.rules:
        print("  - " + r)

    # ---- 场景C：新账户 + 类似目标，验证学习 ----
    reset_sim_engine(7)  # 换个种子 = 换个"新账户"，但记忆是跨账户持久的单例
    conn_c = make_connector()
    cap = mem.suggest_budget_increase_cap(default_cap=20)
    print(f"\n{'=' * 72}\n场景C · 新账户 + 类似目标（验证记忆收敛）\n{'=' * 72}")
    note = "（历史加预算边际递减 → 增幅收敛至 +10%）" if cap < 20 else ""
    print(f"  记忆收敛后的预算增幅上限 = +{cap:.0f}%  {note}")
    run_goal("给高 ROI 提量", conn_c, "场景C · 新账户复用记忆")


if __name__ == "__main__":
    main()
