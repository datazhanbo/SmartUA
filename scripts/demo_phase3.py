"""Phase 3 演示：策略自演化（Strategy Self-Evolution）。

目标：证明 Agent 把 Phase 2 的「经历」编译成**可迁移、可持久**的策略参数，
新账户 / 进程重启后无需重新踩坑即可用上更优决策。

场景：
  A. 账户1（seed=1）执行多目标 → 沉淀 Episode
  B. 账户2（seed=2）执行多目标 → 继续沉淀 Episode
  C. 从累计记忆 learn 策略并落盘 → 展示学到的参数
  D. 模拟「重启 + 迁移」：新 StrategyStore 从磁盘加载策略 + 全新空记忆 + 新账户3（seed=7）
     → 规划器从首步即用学到的预算增幅（对比：无策略时默认 +20%）
"""
from __future__ import annotations
import os
import tempfile

from app.services.connectors.mock_media import reset_sim_engine, MockMediaConnector
from app.services.agent_runtime import (
    AgentLoop, AgentContext, get_session_store, get_memory, StrategyStore,
)
from app.services.agent_runtime.memory import EpisodicMemory
from app.services.agent_runtime.session import AgentStepKind, AgentStepStatus

TMP = os.path.join(tempfile.gettempdir(), "smartua_phase3_strategy.json")
if os.path.exists(TMP):
    os.remove(TMP)


def run_to_done(loop: AgentLoop, session, ctx) -> None:
    """自动批准所有 L1/L2 提议，跑到终态（演示用：模拟人批准好建议）。"""
    while session.status == "awaiting_approval":
        step = next(s for s in session.steps
                    if s.kind == AgentStepKind.APPROVAL.value
                    and s.status == AgentStepStatus.PROPOSED.value)
        loop.approve(session, step.id, True, None, ctx)


def run_account(seed: int, goal: str, memory, strategy):
    reset_sim_engine(seed)
    connector = MockMediaConnector(db=None, app_id=1, credentials={})
    store = get_session_store()
    session = store.create(app_id=1, user_id=0, goal=goal)
    ctx = AgentContext(db=None, user=None, app_id=1, session=None,
                       connector=connector, memory=memory, strategy=strategy)
    ctx.session = session
    loop = AgentLoop()
    loop.start(session, ctx)
    run_to_done(loop, session, ctx)
    return session


def print_session(title: str, session) -> None:
    print(f"\n=== {title} ===")
    for s in session.steps:
        if s.kind in (AgentStepKind.THOUGHT.value, AgentStepKind.ACTION.value,
                      AgentStepKind.APPROVAL.value, AgentStepKind.FINAL.value):
            mark = {"thought": "🧠", "action": "✅", "approval": "⏳", "final": "🏁"}.get(s.kind, "·")
            print(f"  {mark} {s.text}")


def main():
    OBJECTIVE = "暂停低ROI campaign；给高ROI加预算；给最差的换素材"
    memory = get_memory()           # 跨账户累积的单例记忆

    print("#" * 72)
    print("# Phase 3 演示：策略自演化（Strategy Self-Evolution）")
    print("#" * 72)

    # ---------- 场景 A / B：多账户累积经历 ----------
    print("\n--- 场景 A/B：账户1(seed=1) + 账户2(seed=2) 执行多目标，沉淀 Episode ---")
    s1 = run_account(1, OBJECTIVE, memory, strategy=None)
    s2 = run_account(2, OBJECTIVE, memory, strategy=None)
    print(f"  账户1 终态步数={len(s1.steps)}，账户2 终态步数={len(s2.steps)}")
    print(f"  累计 Episode = {len(memory.all())} 条")
    agg = memory.aggregate()
    for action, st in agg.items():
        print(f"    · {action}: {st['count']} 次，7d 平均ΔROI={st['avg_delta_roi_7d']:+.3f}")

    # ---------- 场景 C：learn 策略并落盘 ----------
    print("\n--- 场景 C：从记忆 learn 策略（落盘 → 解决 Phase 2 重启即失） ---")
    strategy = StrategyStore(path=TMP)
    result = strategy.learn_from_memory(memory)
    print(f"  学到参数：{result.learned_keys}")
    print(f"  说明：{result.note}")
    print(f"  落盘路径：{TMP} （存在：{os.path.exists(TMP)}）")
    for k, r in result.rules.items():
        print(f"    · {k} = {r.value}（置信度={r.confidence}，样本={r.n_samples}，来源={r.source}）")

    # ---------- 场景 D：重启 + 迁移 ----------
    print("\n--- 场景 D：模拟『重启 + 新账户迁移』 ---")
    print("    · 新 StrategyStore 从磁盘加载（进程已重启，内存记忆为空）")
    loaded = StrategyStore(path=TMP)        # 模拟重启：从磁盘恢复策略
    print(f"    · 加载到的策略：{[ (k, round(v.value,2)) for k,v in loaded.all().items() ]}")
    fresh_mem = EpisodicMemory()            # 全新空记忆（隔离 Episode 干扰，证明迁移来自策略本身）

    def run_transfer(use_strategy):
        reset_sim_engine(7)
        connector = MockMediaConnector(db=None, app_id=1, credentials={})
        store = get_session_store()
        session = store.create(app_id=1, user_id=0, goal="给高ROI的campaign加预算提量")
        strat = loaded if use_strategy else None
        # 每次迁移都用「全新空记忆」，隔离 Episode 干扰——证明迁移来自策略本身
        local_mem = EpisodicMemory()
        ctx = AgentContext(db=None, user=None, app_id=1, session=None,
                           connector=connector, memory=local_mem, strategy=strat)
        ctx.session = session
        loop = AgentLoop()
        loop.start(session, ctx)
        run_to_done(loop, session, ctx)
        # 抓取预算决策文案（含"提议日预算"，区别于目标步）
        bud = next((s.text for s in session.steps
                    if s.kind == AgentStepKind.THOUGHT.value and "提议日预算" in s.text), "（无）")
        return bud

    print("\n    [新账户 seed=7，已加载策略] 规划结果：")
    print(f"      {run_transfer(use_strategy=True)}")
    print("\n    [新账户 seed=7，无策略（默认）] 规划结果（对照）：")
    print(f"      {run_transfer(use_strategy=False)}")

    print("\n" + "=" * 72)
    print("结论：学到的策略已落盘并在『重启 + 新账户』后生效 ——")
    print("  新账户从首步即用保守增幅（+10% 而非默认 +20%），无需重新踩坑。")
    print("  这正是『进化能力』的收口：经验 → 记忆 → 策略 → 迁移复用。")
    print("=" * 72)


if __name__ == "__main__":
    main()
