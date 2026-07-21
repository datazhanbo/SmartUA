"""Phase A 冒烟测试：验证 A1 持久化（重启可读回）、A2 TikTok 注册、A3 真实连接器接地。

- 使用独立临时 DB（/tmp/smartua_phaseA_test.db），不污染真实 smartua.db。
- 通过「重置单例全局 → 新建 store 实例」模拟进程重启，验证数据可从 DB 读回。
- A3：用 Meta/TikTok 连接器的 mock 拉取填充 FactMediaDaily，验证 current_summary
  能从真实数据聚合（roi 在缺 MMP 时为 None，检测器已做跳过处理），account_status/
  simulate_impact 不崩溃。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 必须在导入任何 app 模块之前设定，使 engine 指向隔离测试库
os.environ["DATABASE_URL"] = "sqlite:////tmp/smartua_phaseA_test.db"

from datetime import date, timedelta

from app.db.base import Base, engine, SessionLocal
import app.models.data          # noqa: F401  注册 FactMediaDaily/FactMMPDaily/ConnectorRun
from app.models import agent_runtime as _agent_runtime_models  # noqa: F401  注册 Agent 表

from app.services.agent_runtime.session import (
    AgentSession, AgentStep, AgentStepKind, AgentStepStatus, get_session_store,
)
from app.services.agent_runtime.memory import Episode, get_memory
from app.services.agent_runtime.autonomy import AutonomyAlert, Anomaly, get_autonomy_store
from app.services.connectors import ConnectorFactory
from app.services.connectors.meta import MetaConnector
from app.services.connectors.tiktok import TikTokConnector

# 确保测试库表结构存在
Base.metadata.create_all(bind=engine)

fails = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    if not cond:
        fails.append(name)


print("=== Phase A1：状态持久化（重启可读回）===")

# ---- 会话 ----
store = get_session_store()
s = store.create(app_id=1, user_id=1, goal="t-goal")
s.add_step(AgentStep(kind="thought", text="s1"))
s.status = "done"
store.persist(s)
sid = s.id
import app.services.agent_runtime.session as _sm
_sm._session_store = None
loaded = get_session_store().get(sid)
check("会话：重启后可读回目标/状态/步骤",
      loaded is not None and loaded.status == "done"
      and len(loaded.steps) == 1 and loaded.goal == "t-goal")
get_session_store().delete(sid)

# ---- 记忆（Episode）----
mem = get_memory()
mem.record(Episode(action="adjust_budget", goal="g", params={"x": 1},
                   pre_state={"roi": 1.2}, impact={"impact_24h": {"delta_roi": 0.1}},
                   outcome=True))
import app.services.agent_runtime.memory as _mm
_mm._memory = None
eps = get_memory().by_action("adjust_budget")
check("记忆：重启后可读回 Episode",
      len(eps) == 1 and eps[0].action == "adjust_budget")
get_memory().clear()

# ---- 告警流 ----
ast = get_autonomy_store()
an = Anomaly(app_id=1, type="roi_drop", title="tt", campaign_id="c1")
al = AutonomyAlert(app_id=1, anomaly=an, status="pending_approval")
ast.add_alert(al)
import app.services.agent_runtime.autonomy as _am
_am._autonomy_store = None
fa = get_autonomy_store()
check("告警：重启后可读回 AutonomyAlert",
      any(x.id == al.id for x in fa.list_alerts()))
get_autonomy_store().clear()


print("\n=== Phase A2：TikTok 连接器注册 ===")
check("ConnectorFactory 含 tiktok 且指向 TikTokConnector",
      ConnectorFactory._connectors.get("tiktok") is TikTokConnector)


print("\n=== Phase A3：真实连接器接地（current_summary / account_status / simulate_impact）===")
db = SessionLocal()

# Meta（无 SDK → mock 拉取填充 FactMediaDaily，source_platform=meta）
meta = MetaConnector(db, 1, {}, execution_mode="mock")
r_meta = meta.execute_pull(date.today() - timedelta(days=2), date.today(), "campaign_daily")
check("Meta execute_pull 成功", r_meta.get("success") is True)
sum_meta = meta.current_summary()
check("Meta current_summary 非空（来自 FactMediaDaily 聚合）", len(sum_meta) > 0)
check("Meta summary 含兼容键 campaign_id/roi/spend",
      all(("campaign_id" in r and "roi" in r and "spend" in r) for r in sum_meta))
# 缺 MMP 时 roi 应为 None（而非抛错），检测器已做跳过处理
check("Meta summary 缺 MMP 时 roi 为 None（安全）",
      all(r.get("roi") is None for r in sum_meta))
check("Meta account_status 默认 ok", meta.account_status() == "ok")
imp = meta.simulate_impact("update_campaign_status", "x", {"status": "PAUSED"}, 7)
check("Meta simulate_impact 返回 ImpactEstimation(7 维)",
      hasattr(imp, "delta_roi") and len(imp.delta_roi) == 7)

# TikTok
tk = TikTokConnector(db, 1, {}, execution_mode="mock")
r_tk = tk.execute_pull(date.today() - timedelta(days=1), date.today(), "campaign_daily")
check("TikTok execute_pull 成功", r_tk.get("success") is True)
sum_tk = tk.current_summary()
check("TikTok current_summary 非空", len(sum_tk) > 0)

# db=None 安全
check("current_summary 在 db=None 时返回 []（不崩溃）",
      MetaConnector(None, 1, {}, execution_mode="mock").current_summary() == [])

db.close()


print("\n" + "=" * 60)
if fails:
    print(f"结果：{len(fails)} 项失败 -> {fails}")
    rc = 1
else:
    print("结果：全部通过 ✅")
    rc = 0

# 清理临时测试库
for suffix in ("", "-wal", "-shm"):
    p = f"/tmp/smartua_phaseA_test.db{suffix}"
    if os.path.exists(p):
        try:
            os.remove(p)
        except Exception:
            pass

sys.exit(rc)
