"""Phase 4.4 —— Durable Background Jobs（P2 #4）。

最小可用的 DB-backed 任务运行器：

- Job 状态落 `agent_jobs` 表，APScheduler 只做高频 tick；
- 进程重启后 `recover_stale` 把超时 running 的 job 复位，`run_pending` 继续跑；
- 同 `idempotency_key` 的 job 只入队一次（UNIQUE 约束）；
- 不引入 Celery/Temporal/Redis——SQLite 单进程足够 SmartUA 当前量级。

Handler 签名：`Callable[[Session, dict], Optional[dict]]`，返回值写入 `result`。
抛异常 → job 落 `failed`，`attempts < max_attempts` 时由 `recover_stale` 复位重试。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.agent_runtime import JobDB

logger = logging.getLogger(__name__)


JobHandler = Callable[[Session, Dict[str, Any]], Optional[Dict[str, Any]]]

# Job 状态
SCHEDULED = "scheduled"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"


class JobRunner:
    """注册 handler、入队、claim 到点 job、执行、崩溃恢复。"""

    def __init__(self) -> None:
        self._handlers: Dict[str, JobHandler] = {}

    # ---- handler 注册 -------------------------------------------------- #
    def register(self, job_type: str, handler: JobHandler) -> None:
        if job_type in self._handlers:
            logger.warning("job handler %s already registered; replacing", job_type)
        self._handlers[job_type] = handler

    def has(self, job_type: str) -> bool:
        return job_type in self._handlers

    # ---- enqueue ------------------------------------------------------- #
    def enqueue(
        self,
        db: Session,
        job_type: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        scheduled_at: Optional[datetime] = None,
        idempotency_key: Optional[str] = None,
        app_id: Optional[int] = None,
        max_attempts: int = 1,
    ) -> Optional[JobDB]:
        """入队一条 job。

        - 已存在同 idempotency_key 的 job → 返回 None（不重复入队）。
        - 不传 idempotency_key → 用 uuid 生成（每次入队都是新 job）。
        - 不传 scheduled_at → 立即到点。
        """
        if not idempotency_key:
            idempotency_key = uuid.uuid4().hex
        scheduled_at = scheduled_at or datetime.utcnow()
        job = JobDB(
            id=uuid.uuid4().hex[:32],
            job_type=job_type,
            idempotency_key=idempotency_key,
            status=SCHEDULED,
            scheduled_at=scheduled_at,
            payload=payload or {},
            attempts=0,
            max_attempts=max(1, int(max_attempts)),
            app_id=app_id,
        )
        db.add(job)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return None
        return job

    # ---- recovery ------------------------------------------------------ #
    def recover_stale(
        self,
        db: Session,
        *,
        now: Optional[datetime] = None,
        timeout: timedelta = timedelta(minutes=10),
    ) -> int:
        """把超时仍在 running 的 job 复位。

        - attempts < max_attempts → 回 scheduled（at now），下次 tick 重试；
        - attempts >= max_attempts → 落 failed。
        返回复位条数。
        """
        now = now or datetime.utcnow()
        cutoff = now - timeout
        stuck: List[JobDB] = (
            db.query(JobDB)
            .filter(JobDB.status == RUNNING, JobDB.started_at < cutoff)
            .all()
        )
        n = 0
        for job in stuck:
            if job.attempts < job.max_attempts:
                job.status = SCHEDULED
                job.started_at = None
                job.last_error = (job.last_error or "") + f"\n[recover_stale @ {now.isoformat()}] reset to scheduled"
            else:
                job.status = FAILED
                job.finished_at = now
                job.last_error = (job.last_error or "") + f"\n[recover_stale @ {now.isoformat()}] exceeded max_attempts"
            n += 1
        if n:
            db.flush()
        return n

    # ---- run loop ------------------------------------------------------ #
    def run_pending(
        self,
        db: Session,
        *,
        now: Optional[datetime] = None,
        limit: int = 50,
        job_type: Optional[str] = None,
        app_id: Optional[int] = None,
    ) -> Dict[str, int]:
        """claim 并执行到点的 scheduled job，返回 {done, failed, missing_handler}。"""
        now = now or datetime.utcnow()
        q = db.query(JobDB).filter(
            JobDB.status == SCHEDULED,
            JobDB.scheduled_at <= now,
        )
        if job_type:
            q = q.filter(JobDB.job_type == job_type)
        if app_id is not None:
            q = q.filter(JobDB.app_id == app_id)
        jobs: List[JobDB] = (
            q.order_by(JobDB.scheduled_at.asc()).limit(limit).all()
        )
        stats = {"done": 0, "failed": 0, "missing_handler": 0}
        for job in jobs:
            self._run_one(db, job, now=now, stats=stats)
        return stats

    def _run_one(self, db: Session, job: JobDB, *, now: datetime, stats: Dict[str, int]) -> None:
        handler = self._handlers.get(job.job_type)
        if handler is None:
            logger.error("no handler for job_type=%s (job %s)", job.job_type, job.id)
            job.status = FAILED
            job.last_error = f"no handler registered for job_type={job.job_type!r}"
            job.finished_at = now
            job.attempts = (job.attempts or 0) + 1
            stats["missing_handler"] += 1
            db.flush()
            return

        # claim
        job.status = RUNNING
        job.started_at = now
        job.attempts = (job.attempts or 0) + 1
        job.last_error = None
        db.flush()

        try:
            result = handler(db, job.payload or {})
        except Exception as exc:  # noqa: BLE001 - 任何 handler 异常都不能拖垮 runner
            logger.exception("job %s (%s) raised", job.id, job.job_type)
            if job.attempts < job.max_attempts:
                # 留给下次 tick：保持 running → recover_stale 会复位
                # 但为了避免立即被同 tick 再 claim，主动回 scheduled
                job.status = SCHEDULED
                job.started_at = None
            else:
                job.status = FAILED
                job.finished_at = datetime.utcnow()
            job.last_error = f"{type(exc).__name__}: {exc}"
            stats["failed"] += 1
            db.flush()
            return

        job.status = DONE
        job.finished_at = datetime.utcnow()
        job.result = result
        stats["done"] += 1
        db.flush()


# --------------------------------------------------------------------------- #
# 单例
# --------------------------------------------------------------------------- #
_runner: Optional[JobRunner] = None
_default_handlers_registered = False


def get_job_runner() -> JobRunner:
    global _runner
    if _runner is None:
        _runner = JobRunner()
    return _runner


def register_default_handlers() -> None:
    """注册 SmartUA 内置 job_type。幂等。"""
    global _default_handlers_registered
    if _default_handlers_registered:
        return
    runner = get_job_runner()

    from app.services.agent_runtime.impact_collector import run_impact_job
    from app.services.agent_runtime.autonomy import run_autonomy_scan_job

    runner.register("impact_collect", run_impact_job)
    runner.register("autonomy_scan", run_autonomy_scan_job)

    _default_handlers_registered = True


def reset_job_runner() -> None:
    """测试钩子：清空单例。"""
    global _runner, _default_handlers_registered
    _runner = None
    _default_handlers_registered = False
