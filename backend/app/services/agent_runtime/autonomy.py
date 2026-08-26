"""Phase 4 — 主动式自治（Proactive Autonomy）。

让 Agent 从"人召唤"升级为"主动守护"：

- 周期性（APScheduler）扫描账户实时状态，检测异常：
    · CPI 飙升 / ROI 跌破阈值 / 素材疲劳 / 花费异常 / 账户被封（Meta appeal 等）
- 检测到异常后，基于已沉淀的**策略与记忆**自主规划处置（复用 Phase 1~3 的全部能力）：
    · L0 动作（如换素材）→ 自动执行（系统替你做了，无需打扰）
    · L1/L2 动作（如暂停/调预算）→ 生成一条"主动提案"，进入人在环审批队列（前端可一键批准）
    · 仅需知会 / 不安全的 → 生成"仅通知"告警（如花费异常不盲目自动缩量）
- 主动汇报：扫描历史 + 告警流可在前端查看，体现"系统在替你盯盘"。

设计原则（与全局一致）：
- 平台做"身体+护栏"，Agent Loop 做"大脑"，Tool Registry 桥接。
- 主动≠失控：高风险动作**绝不自动执行**，一律回到人在环；L0 也只在低风险场景使用。
- 阈值数据驱动：ROI 跌破阈值优先用 Phase 3 学到的 `pause_roi_threshold`，回退默认 1.0。
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from app.config import settings
from app.db.base import SessionLocal
from app.models.agent_runtime import AutonomyAlertDB, AutonomyScanDB
from app.services.agent_runtime.session import (
    AgentSession, AgentStep, AgentStepKind, AgentStepStatus, get_session_store,
)
from app.services.agent_runtime.tools import AgentContext, get_tool_registry
from app.services.agent_runtime.loop import AgentLoop

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return datetime.utcnow()


def _fmt_dt(v):
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return v.isoformat()


# 系统发起会话使用的占位 user（前端审批走真实 /agent/sessions/{id}/approve，不校验归属）
SYSTEM_USER_ID = -1


class AnomalyType(str, Enum):
    CPI_SPIKE = "cpi_spike"
    ROI_DROP = "roi_drop"
    CREATIVE_FATIGUE = "creative_fatigue"
    SPEND_OVER = "spend_over_budget"
    ACCOUNT_DISABLED = "account_disabled"


@dataclass
class Anomaly:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    detected_at: str = field(default_factory=_now)
    app_id: int = 1
    campaign_id: Optional[str] = None
    type: str = ""
    title: str = ""
    severity: str = "info"          # info / warning / critical
    detail: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    suggested_tool: Optional[str] = None
    suggested_params: Dict[str, Any] = field(default_factory=dict)
    suggested_risk: Optional[str] = None   # L0/L1/L2/L3
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "detected_at": self.detected_at, "app_id": self.app_id,
            "campaign_id": self.campaign_id, "type": self.type, "title": self.title,
            "severity": self.severity, "detail": self.detail, "metrics": self.metrics,
            "suggested_tool": self.suggested_tool, "suggested_params": self.suggested_params,
            "suggested_risk": self.suggested_risk, "rationale": self.rationale,
        }


@dataclass
class AutonomyAlert:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    detected_at: str = field(default_factory=_now)
    app_id: int = 1
    anomaly: Anomaly = field(default_factory=Anomaly)
    status: str = "pending_approval"   # auto_executed / pending_approval / no_action / approved / rejected
    session_id: Optional[str] = None
    step_id: Optional[str] = None
    resolution: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "detected_at": self.detected_at, "app_id": self.app_id,
            "anomaly": self.anomaly.to_dict(), "status": self.status,
            "session_id": self.session_id, "step_id": self.step_id,
            "resolution": self.resolution,
        }


# --------------------------------------------------------------------------- #
# 检测器：把"实时账户状态"转成"异常"
# --------------------------------------------------------------------------- #
class AnomalyDetector:
    def __init__(self, strategy=None):
        self.strategy = strategy

    def detect(self, connector, app_id: int = 1) -> List[Anomaly]:
        summary = connector.current_summary()
        if not summary:
            return []
        active = [s for s in summary if s.get("status") == "ACTIVE"]

        # 1) 账户被封 / 受限（Meta appeal 等）：连接器暴露 account_status()
        acct = getattr(connector, "account_status", lambda: "ok")()
        anomalies: List[Anomaly] = []
        if str(acct).upper() not in ("OK", "ACTIVE", "ENABLED", ""):
            anomalies.append(Anomaly(
                app_id=app_id, type=AnomalyType.ACCOUNT_DISABLED,
                title="账户被封 / 受限", severity="critical",
                detail=f"媒体账户状态={acct}（疑似被封或处于 appeal）。建议暂停自动扩量、"
                       f"切备用渠道并联系平台方。",
                metrics={"account_status": acct},
                suggested_risk="L2", suggested_tool=None,
                rationale="账户不可投，需人工介入（切渠道 / 申诉），不自动处置。",
            ))

        # 2) ROI 跌破阈值：优先用 Phase 3 学到的阈值，回退默认 1.0
        threshold = 1.0
        learned = bool(self.strategy is not None and self.strategy.has_learned("pause_roi_threshold"))
        if learned:
            threshold = self.strategy.advise("pause_roi_threshold", 1.0)
        for s in active:
            if s.get("roi") is not None and s["roi"] < threshold:
                anomalies.append(Anomaly(
                    app_id=app_id, campaign_id=s["campaign_id"], type=AnomalyType.ROI_DROP,
                    title=f"{s['campaign_id']} ROI={s['roi']:.2f} 跌破 {threshold:.2f}",
                    severity="critical",
                    detail=f"ROI 已低于止损阈值 {threshold:.2f}（使用{'已学策略' if learned else '默认'}阈值）。",
                    metrics={"roi": s["roi"], "threshold": threshold, "cpi": s["cpi"]},
                    suggested_tool="pause_campaign",
                    suggested_params={"entity_id": s["campaign_id"]},
                    suggested_risk="L1", rationale="低 ROI 持续烧钱，暂停止损。",
                ))

        # 3) 素材疲劳：creative_age 偏高且 ROI 仍健康（否则走 ROI_DROP）
        fatigue_age = int(getattr(settings, "agent_fatigue_threshold_days", 8))
        for s in active:
            if s.get("roi") is not None and s["roi"] < threshold:
                continue
            age = int(s.get("creative_age", 0) or 0)
            if age >= fatigue_age:
                anomalies.append(Anomaly(
                    app_id=app_id, campaign_id=s["campaign_id"],
                    type=AnomalyType.CREATIVE_FATIGUE,
                    title=f"{s['campaign_id']} 素材疲劳（{age} 天）", severity="info",
                    detail=f"素材已 {age} 天未轮换，CTR 衰减中；ROI 仍健康，可自动轮换提效。",
                    metrics={"creative_age": age, "roi": s["roi"]},
                    suggested_tool="rotate_creative",
                    suggested_params={"entity_id": s["campaign_id"]},
                    suggested_risk="L0", rationale="换素材短期提振 CTR，L0 自动执行。",
                ))

        # 4) CPI 飙升：相对账户中位数偏高（且素材不疲劳，否则走疲劳分支）
        cpis = [s["cpi"] for s in active if s["cpi"] > 0]
        if cpis:
            med = sorted(cpis)[len(cpis) // 2]
            for s in active:
                age = int(s.get("creative_age", 0) or 0)
                if age >= fatigue_age:
                    continue  # 由 CREATIVE_FATIGUE 处理（L0 自动轮换更对症）
                if s["cpi"] > 0 and s["cpi"] >= max(med * 1.8, 12.0) \
                        and s.get("roi") is not None and s["roi"] >= threshold:
                    anomalies.append(Anomaly(
                        app_id=app_id, campaign_id=s["campaign_id"], type=AnomalyType.CPI_SPIKE,
                        title=f"{s['campaign_id']} CPI={s['cpi']:.2f} 飙升",
                        severity="warning",
                        detail=f"CPI 达 {s['cpi']:.2f}，约为账户中位数 {med:.2f} 的 "
                               f"{s['cpi']/med:.1f} 倍，且 ROI 健康 → 提案暂停核查。",
                        metrics={"cpi": s["cpi"], "median_cpi": med, "roi": s["roi"]},
                        suggested_tool="pause_campaign",
                        suggested_params={"entity_id": s["campaign_id"]},
                        suggested_risk="L1",
                        rationale="CPI 异常高、素材不疲劳，疑似定向/质量异常，提案暂停核查。",
                    ))

        # 5) 花费异常：当日 spend 远超日预算 → 仅通知（避免危险自动缩量）
        for s in active:
            b = float(s.get("daily_budget") or 0)
            if b > 0 and s["spend"] >= b * 1.5:
                anomalies.append(Anomaly(
                    app_id=app_id, campaign_id=s["campaign_id"], type=AnomalyType.SPEND_OVER,
                    title=f"{s['campaign_id']} 花费达预算 {s['spend']/b:.1f}x",
                    severity="warning",
                    detail=f"当日花费 {s['spend']:.0f} 已达日预算 {b:.0f} 的 "
                           f"{s['spend']/b:.1f} 倍，关注是否超投。",
                    metrics={"spend": s["spend"], "daily_budget": b},
                    suggested_risk=None, suggested_tool=None,
                    rationale="花费异常，仅通知优化师核查，不自动改预算（避免危险自动缩量）。",
                ))

        return anomalies


# --------------------------------------------------------------------------- #
# 自治引擎：检测 → 分级处置
# --------------------------------------------------------------------------- #
class AutonomyEngine:
    def __init__(self):
        self.store = get_autonomy_store()

    def scan(self, app_id: int = 1, db=None, user=None) -> List[AutonomyAlert]:
        """执行一次主动巡检：检测异常并按风险分级处置。可在调度器或手动端点调用。"""
        from app.services.connectors import ConnectorFactory, resolve_credentials
        from app.services.agent_runtime import get_memory, get_strategy

        connector = ConnectorFactory.get_connector(
            settings.agent_default_platform, db=db, app_id=app_id,
            credentials=resolve_credentials(settings.agent_default_platform, db=db, app_id=app_id),
            execution_mode=settings.agent_execution_mode)
        ctx = AgentContext(db=db, user=user, app_id=app_id, session=None,
                           connector=connector, memory=get_memory(), strategy=get_strategy())

        detector = AnomalyDetector(strategy=get_strategy())
        anomalies = detector.detect(connector, app_id)

        seq = self.store.next_seq()
        alerts: List[AutonomyAlert] = []
        for a in anomalies:
            if self.store.should_skip(a, seq):
                continue  # 冷却期内已处置过同 (类型, campaign)，跳过避免重复告警
            alert = self._remediate(a, ctx)
            self.store.mark_handled(a, seq)
            alerts.append(alert)

        self.store.record_scan(
            app_id, [a.to_dict() for a in anomalies], [al.to_dict() for al in alerts])
        return alerts

    def _remediate(self, a: Anomaly, ctx: AgentContext) -> AutonomyAlert:
        store = get_session_store()
        session = store.create(
            app_id=a.app_id, user_id=SYSTEM_USER_ID,
            goal=f"【系统主动监控】{a.title}")
        session.add_step(AgentStep(
            kind=AgentStepKind.THOUGHT.value,
            text=f"🔎 主动巡检发现：{a.title}。{a.detail}",
            status=AgentStepStatus.DONE.value))

        alert = AutonomyAlert(app_id=a.app_id, anomaly=a)
        ctx.session = session

        if not a.suggested_tool:
            # 仅通知（如花费异常、账户被封）：不自动改动，留给人工判断
            session.add_step(AgentStep(
                kind=AgentStepKind.FINAL.value,
                text=f"ℹ️ 已记录告警（仅通知，未自动处置）：{a.detail}",
                status=AgentStepStatus.DONE.value))
            session.status = "done"
            alert.status = "no_action"
            alert.resolution = "仅通知优化师，未自动处置"
            self.store.add_alert(alert)
            return alert

        registry = get_tool_registry()
        tool = registry.get(a.suggested_tool)
        risk = a.suggested_risk or (tool.risk_level if tool else "L1")

        if risk == "L0" and tool is not None:
            # L0 自动执行（如换素材）
            res = tool.handler(a.suggested_params, ctx)
            session.add_step(AgentStep(
                kind=AgentStepKind.ACTION.value, text=res.observation,
                tool=tool.name, params=a.suggested_params, risk_level="L0",
                status=AgentStepStatus.EXECUTED.value, result=res.data))
            session.status = "done"
            alert.status = "auto_executed"
            alert.resolution = res.observation
        else:
            # L1/L2/L3 → 人在环审批：生成待批准会话，由优化师在页面一键批准
            loop = AgentLoop()
            pred = loop._predict(ctx, tool.name, a.suggested_params) if tool else None
            step = AgentStep(
                kind=AgentStepKind.APPROVAL.value,
                text=f"系统提议{a.suggested_tool}：{a.detail}",
                tool=tool.name if tool else a.suggested_tool,
                params=a.suggested_params, risk_level=risk,
                predicted_impact=pred, status=AgentStepStatus.PROPOSED.value)
            session.add_step(step)
            session.status = "awaiting_approval"
            alert.status = "pending_approval"
            alert.session_id = session.id
            alert.step_id = step.id
            alert.resolution = "等待优化师审批"

        self.store.add_alert(alert)
        return alert


# --------------------------------------------------------------------------- #
# 存储（进程内单例）：扫描历史 + 告警流 + 调度配置
# --------------------------------------------------------------------------- #
class AutonomyStore:
    """扫描历史 + 告警流 + 调度配置：进程内缓存（快路径）+ SQLite 持久化（重启不丢，Phase A1）。

    - `_alerts` / `_scans` 为内存缓存，首次访问从 DB 载入；`add_alert` / `record_scan` 写库。
    - `_handlers` / `_scan_seq` 为进程内去重状态（重启后重置，去重退化为"本进程内"语义，可接受）。
    """

    def __init__(self):
        self._alerts: List[AutonomyAlert] = []
        self._scans: List[Dict[str, Any]] = []
        self._handlers: Dict[Any, int] = {}   # (type, campaign_id) -> 最近处理时的 scan_seq
        self._scan_seq: int = 0
        self._loaded = False
        self.enabled = bool(getattr(settings, "agent_autonomy_enabled", False))
        self.interval_seconds = int(getattr(settings, "agent_autonomy_interval_seconds", 120))
        self.last_scan_at: Optional[str] = None

    # ----- DB 加载 -----
    def _ensure_loaded(self):
        if self._loaded:
            return
        db = SessionLocal()
        try:
            scan_rows = db.query(AutonomyScanDB).order_by(AutonomyScanDB.id).all()
            self._scans = [{
                "at": _fmt_dt(r.at), "app_id": r.app_id,
                "n_anomalies": r.n_anomalies, "n_alerts": r.n_alerts,
            } for r in scan_rows]
            alert_rows = db.query(AutonomyAlertDB).order_by(AutonomyAlertDB.detected_at).all()
            self._alerts = [self._row_to_alert(r) for r in alert_rows]
        finally:
            db.close()
        self._loaded = True
        if self._scans:
            self.last_scan_at = self._scans[-1]["at"]

    @staticmethod
    def _row_to_alert(row: AutonomyAlertDB) -> AutonomyAlert:
        anomaly_dict = row.anomaly_json or {}
        anomaly = Anomaly(**{k: anomaly_dict.get(k) for k in (
            "id", "detected_at", "app_id", "campaign_id", "type", "title",
            "severity", "detail", "metrics", "suggested_tool",
            "suggested_params", "suggested_risk", "rationale")})
        return AutonomyAlert(
            id=row.id,
            detected_at=_fmt_dt(row.detected_at) or _now(),
            app_id=row.app_id,
            anomaly=anomaly,
            status=row.status,
            session_id=row.session_id,
            step_id=row.step_id,
            resolution=row.resolution or "",
        )

    # 调度配置
    def set_enabled(self, v: bool):
        self.enabled = v

    def set_interval(self, sec: int):
        self.interval_seconds = int(sec)

    # 扫描序号 + 冷却去重
    def next_seq(self) -> int:
        self._ensure_loaded()
        self._scan_seq += 1
        return self._scan_seq

    def should_skip(self, a: Anomaly, seq: int) -> bool:
        self._ensure_loaded()
        last = self._handlers.get((a.type, a.campaign_id))
        if last is None:
            return False
        cooldown = int(getattr(settings, "agent_autonomy_cooldown_scans", 3))
        return (seq - last) <= cooldown

    def mark_handled(self, a: Anomaly, seq: int):
        self._handlers[(a.type, a.campaign_id)] = seq

    # ----- 记录 -----
    def add_alert(self, alert: AutonomyAlert) -> None:
        """追加一条告警并落库（供 `AutonomyEngine._remediate` 调用，替代直接 `_alerts.append`）。"""
        self._ensure_loaded()
        self._alerts.append(alert)
        db = SessionLocal()
        try:
            db.add(AutonomyAlertDB(
                id=alert.id,
                detected_at=_parse_dt(alert.detected_at),
                app_id=alert.app_id,
                anomaly_json=alert.anomaly.to_dict(),
                status=alert.status,
                session_id=alert.session_id,
                step_id=alert.step_id,
                resolution=alert.resolution or "",
            ))
            db.commit()
        finally:
            db.close()

    def _persist_alert(self, alert: AutonomyAlert) -> None:
        """回写已存在告警的状态 / 处置结论（审批端点调用）。"""
        db = SessionLocal()
        try:
            row = db.get(AutonomyAlertDB, alert.id)
            if row is None:
                db.add(AutonomyAlertDB(
                    id=alert.id, detected_at=_parse_dt(alert.detected_at),
                    app_id=alert.app_id, anomaly_json=alert.anomaly.to_dict(),
                    status=alert.status, session_id=alert.session_id,
                    step_id=alert.step_id, resolution=alert.resolution or ""))
            else:
                row.status = alert.status
                row.resolution = alert.resolution or ""
            db.commit()
        finally:
            db.close()

    def record_scan(self, app_id: int, anomalies: List[Dict], alerts: List[Dict]):
        self.last_scan_at = _now()
        self._scans.append({
            "at": self.last_scan_at, "app_id": app_id,
            "n_anomalies": len(anomalies), "n_alerts": len(alerts),
        })
        if len(self._scans) > 100:
            self._scans = self._scans[-100:]
        db = SessionLocal()
        try:
            db.add(AutonomyScanDB(
                at=_parse_dt(self.last_scan_at), app_id=app_id,
                n_anomalies=len(anomalies), n_alerts=len(alerts)))
            db.commit()
        finally:
            db.close()

    def list_alerts(self, app_id: Optional[int] = None) -> List[AutonomyAlert]:
        self._ensure_loaded()
        if app_id is None:
            return list(self._alerts)
        return [a for a in self._alerts if a.app_id == app_id]

    def get_alert(self, alert_id: str) -> Optional[AutonomyAlert]:
        self._ensure_loaded()
        return next((a for a in self._alerts if a.id == alert_id), None)

    def pending_count(self) -> int:
        self._ensure_loaded()
        return sum(1 for a in self._alerts if a.status == "pending_approval")

    def clear(self) -> None:
        """清空全部告警与扫描记录（演示 / 测试用）。"""
        db = SessionLocal()
        try:
            db.query(AutonomyAlertDB).delete()
            db.query(AutonomyScanDB).delete()
            db.commit()
        finally:
            db.close()
        self._alerts = []
        self._scans = []
        self._handlers = {}
        self._scan_seq = 0
        self.last_scan_at = None
        self._loaded = True


# --------------------------------------------------------------------------- #
# Durable job handler
# --------------------------------------------------------------------------- #
def run_autonomy_scan_job(db, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """JobRunner 入口：跑一次 AutonomyEngine.scan。

    payload: {"app_id": int}
    """
    app_id = int(payload["app_id"])
    engine = AutonomyEngine()
    # AutonomyEngine.scan 自己开 SessionLocal；这里不需要用传入的 db 写结果，
    # 但把扫描摘要落进 job.result 便于审计。
    import time as _time
    started = _time.time()
    engine.scan(app_id=app_id)
    return {
        "app_id": app_id,
        "elapsed_ms": int((_time.time() - started) * 1000),
    }


def enqueue_autonomy_scan_jobs() -> int:
    """由调度器每个 interval 调用，为每个 monitor app 入队一条 autonomy_scan job。

    用时间桶做 idempotency_key：同一进程同一 interval 内多次触发只入队一条，
    崩溃重启后未跑完的上一桶仍会被 runner 拾起。
    `agent_autonomy_enabled=false` 时直接返回 0（job runner tick 仍跑，
    impact_collect 等其它 job_type 继续消费）。
    """
    if not settings.agent_autonomy_enabled:
        return 0
    from app.services.agent_runtime.jobs import get_job_runner
    store = get_autonomy_store()
    interval = max(30, int(store.interval_seconds))
    bucket = int(datetime.utcnow().timestamp() // interval) * interval
    runner = get_job_runner()
    n = 0
    db = SessionLocal()
    try:
        for app_id in settings.agent_monitor_app_ids:
            job = runner.enqueue(
                db,
                "autonomy_scan",
                payload={"app_id": int(app_id)},
                scheduled_at=datetime.utcnow(),
                idempotency_key=f"autonomy:scan:{app_id}:{bucket}",
                app_id=int(app_id),
                max_attempts=1,
            )
            if job is not None:
                n += 1
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("enqueue autonomy scan jobs failed")
    finally:
        db.close()
    return n


# --------------------------------------------------------------------------- #
# 调度器（APScheduler）：只做 tick，真正执行在 Durable JobRunner
# --------------------------------------------------------------------------- #
_scheduler = None


def _scheduled_enqueue():
    try:
        enqueue_autonomy_scan_jobs()
    except Exception as e:  # 调度任务内部异常不应拖垮整个进程
        logger.warning("autonomy enqueue failed: %s", e)


def _scheduled_run_pending():
    from app.services.agent_runtime.jobs import get_job_runner
    db = SessionLocal()
    try:
        runner = get_job_runner()
        runner.recover_stale(db)
        runner.run_pending(db, limit=100)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("job runner tick failed")
    finally:
        db.close()


def start_scheduler():
    """启动 APScheduler：一个 job 定时 enqueue autonomy_scan，一个 job 高频 tick runner。"""
    global _scheduler
    if _scheduler is not None:
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except Exception as e:
        logger.warning("APScheduler 不可用，主动巡检调度未启动：%s", e)
        return

    from app.services.agent_runtime.jobs import get_job_runner, register_default_handlers
    register_default_handlers()

    store = get_autonomy_store()
    tick_seconds = max(15, int(getattr(settings, "agent_jobs_tick_seconds", 30)))

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _scheduled_enqueue, "interval",
        seconds=store.interval_seconds, id="autonomy_enqueue",
        next_run_time=datetime.utcnow())  # 启动立即补一次
    _scheduler.add_job(
        _scheduled_run_pending, "interval",
        seconds=tick_seconds, id="job_runner_tick",
        next_run_time=datetime.utcnow())  # 启动立即补一次
    _scheduler.start()

    # 启动时立刻做一次 stale recover + run_pending，捡起离线期间到点的 job
    try:
        _scheduled_run_pending()
    except Exception:
        logger.exception("startup run_pending failed")

    logger.info(
        "Durable 调度已启动（autonomy 间隔 %ss, runner tick %ss）",
        store.interval_seconds, tick_seconds,
    )


def stop_scheduler():
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None
    logger.info("主动自治调度已停止")


def update_alert_for_session(session_id: str, approved: bool, resolution: str):
    """审批端点回写：把关联到该会话的待审批告警标记为已批准/已驳回，并落库。"""
    store = get_autonomy_store()
    store._ensure_loaded()
    for al in store._alerts:
        if al.session_id == session_id and al.status == "pending_approval":
            al.status = "approved" if approved else "rejected"
            al.resolution = resolution
            store._persist_alert(al)
            return al
    return None


# --------------------------------------------------------------------------- #
# 单例
# --------------------------------------------------------------------------- #
_autonomy_store: Optional[AutonomyStore] = None


def get_autonomy_store() -> AutonomyStore:
    global _autonomy_store
    if _autonomy_store is None:
        _autonomy_store = AutonomyStore()
    return _autonomy_store
