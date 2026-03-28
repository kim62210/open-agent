"""경량 asyncio 기반 Job 스케줄러.

30초 간격으로 등록된 Job들의 실행 시점을 확인하고,
해당 시점이 되면 job_executor를 통해 실행합니다.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from croniter import croniter

from open_agent.core.exceptions import JobNotFoundError, JobStateError
from open_agent.core.job_executor import execute_job
from open_agent.core.job_manager import job_manager
from open_agent.models.job import JobInfo

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 30  # 스케줄 체크 주기 (초)
MAX_CONCURRENT_JOBS = 3  # 전역 동시 실행 제한


def _get_schedule_tz(cfg: Dict[str, Any]):
    """schedule_config의 timezone 또는 시스템 로컬 타임존을 반환합니다."""
    tz_name = cfg.get("timezone")
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(tz_name)
        except (ImportError, KeyError):
            logger.warning(f"Invalid timezone: {tz_name}, falling back to local")
    return datetime.now().astimezone().tzinfo


def calc_next_run(job: JobInfo, after: Optional[datetime] = None) -> Optional[datetime]:
    """Job의 schedule 설정에 따라 다음 실행 시각을 계산합니다.

    daily, weekly, cron 스케줄은 로컬 타임존 기준으로 계산합니다.
    schedule_config에 "timezone" 키가 있으면 해당 타임존을 사용합니다.
    """
    base = after or datetime.now(timezone.utc)
    cfg = job.schedule_config

    if job.schedule_type == "once":
        run_at_str = cfg.get("run_at")
        if not run_at_str:
            return None
        try:
            run_at = datetime.fromisoformat(run_at_str)
            if run_at.tzinfo is None:
                tz = _get_schedule_tz(cfg)
                run_at = run_at.replace(tzinfo=tz)
            run_at_utc = run_at.astimezone(timezone.utc)
            if run_at_utc > base:
                return run_at_utc
        except (ValueError, TypeError):
            logger.warning(f"Invalid run_at for job {job.id}: {run_at_str}")
        return None

    if job.schedule_type == "interval":
        minutes = int(cfg.get("interval_minutes", 30))
        if job.last_run_at:
            last = datetime.fromisoformat(job.last_run_at)
            next_t = last + timedelta(minutes=minutes)
            if next_t <= base:
                next_t = base + timedelta(seconds=10)
            return next_t
        return base + timedelta(seconds=10)

    if job.schedule_type == "daily":
        h = int(cfg.get("hour", 0))
        m = int(cfg.get("minute", 0))
        tz = _get_schedule_tz(cfg)
        local_base = base.astimezone(tz)
        today_target = local_base.replace(hour=h, minute=m, second=0, microsecond=0)
        if today_target <= local_base:
            today_target += timedelta(days=1)
        return today_target.astimezone(timezone.utc)

    if job.schedule_type == "weekly":
        target_weekday = int(cfg.get("weekday", 0))  # 0=Sun..6=Sat
        h = int(cfg.get("hour", 0))
        m = int(cfg.get("minute", 0))
        tz = _get_schedule_tz(cfg)
        local_base = base.astimezone(tz)
        current_iso = local_base.isoweekday()  # 1=Mon..7=Sun
        target_iso = 7 if target_weekday == 0 else target_weekday
        days_ahead = (target_iso - current_iso) % 7
        next_day = local_base + timedelta(days=days_ahead)
        next_t = next_day.replace(hour=h, minute=m, second=0, microsecond=0)
        if next_t <= local_base:
            next_t += timedelta(weeks=1)
        return next_t.astimezone(timezone.utc)

    if job.schedule_type == "cron":
        expr = cfg.get("cron_expr", "0 0 * * *")
        try:
            tz = _get_schedule_tz(cfg)
            local_base = base.astimezone(tz)
            cron = croniter(expr, local_base)
            next_t = cron.get_next(datetime)
            if next_t.tzinfo is None:
                next_t = next_t.replace(tzinfo=tz)
            return next_t.astimezone(timezone.utc)
        except (ValueError, KeyError) as e:
            logger.warning(f"Invalid cron expression for job {job.id}: {expr} — {e}")
            return None

    return None


class JobScheduler:
    """asyncio 기반 경량 스케줄러."""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running_tasks: Dict[str, asyncio.Task] = {}  # job_id → Task
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("Job scheduler started (check every %ds)", CHECK_INTERVAL)
        self._refresh_all_next_run()

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # 실행 중인 Job들도 모두 취소
        for job_id, task in list(self._running_tasks.items()):
            task.cancel()
        self._running_tasks.clear()
        logger.info("Job scheduler stopped")

    def refresh_job(self, job_id: str) -> None:
        """특정 Job의 next_run_at를 재계산합니다."""
        job = job_manager.get_job(job_id)
        if not job or not job.enabled:
            job_manager.set_next_run_at(job_id, None)
            return
        next_t = calc_next_run(job)
        job_manager.set_next_run_at(
            job_id, next_t.isoformat() if next_t else None
        )

    def _refresh_all_next_run(self) -> None:
        for job in job_manager.get_all_jobs():
            if not job.enabled:
                job_manager.set_next_run_at(job.id, None)
                continue
            next_t = calc_next_run(job)
            job_manager.set_next_run_at(
                job.id, next_t.isoformat() if next_t else None
            )

    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduler tick error")
            await asyncio.sleep(CHECK_INTERVAL)

    async def _tick(self) -> None:
        now = datetime.now(timezone.utc)
        for job in job_manager.get_all_jobs():
            if not job.enabled:
                continue
            if job.id in self._running_tasks:
                continue
            if not job.next_run_at:
                continue
            try:
                next_run = datetime.fromisoformat(job.next_run_at)
            except ValueError:
                continue
            if next_run <= now:
                self._spawn_job(job.id)

    def _spawn_job(self, job_id: str) -> None:
        """Job 실행 Task를 생성합니다."""
        task = asyncio.create_task(self._run_job(job_id))
        self._running_tasks[job_id] = task

    async def _run_job(self, job_id: str) -> None:
        """세마포어로 동시 실행 제한 후 Job을 실행합니다."""
        run_id: Optional[str] = None
        try:
            logger.debug(f"Job waiting for slot ({job_id})")
            async with self._semaphore:
                logger.debug(f"Job acquired slot ({job_id})")
                run_id = job_manager.start_run(job_id)
                if not run_id:
                    return
                try:
                    summary = await execute_job(job_id)
                    job_manager.finish_run(job_id, run_id, "success", summary=summary)
                except asyncio.CancelledError:
                    logger.info(f"Job cancelled ({job_id})")
                    job_manager.finish_run(job_id, run_id, "cancelled", summary="Cancelled by user")
                    raise
                except asyncio.TimeoutError:
                    logger.warning(f"Job timed out ({job_id})")
                    job_manager.finish_run(job_id, run_id, "timeout", summary="Execution timed out (300s)")
                except Exception as e:
                    logger.error(f"Job execution failed ({job_id}): {e}")
                    job_manager.finish_run(job_id, run_id, "failed", summary=str(e)[:500])
        except asyncio.CancelledError:
            # 대기 중 취소 (run_id=None) 또는 실행 중 취소 (re-raise)
            if run_id is None:
                logger.info(f"Job cancelled while waiting for slot ({job_id})")
        finally:
            self._running_tasks.pop(job_id, None)
            self.refresh_job(job_id)

    async def run_now(self, job_id: str) -> None:
        """수동 즉시 실행."""
        job = job_manager.get_job(job_id)
        if not job:
            raise JobNotFoundError(f"Job not found: {job_id}")
        if job_id in self._running_tasks:
            raise JobStateError(f"Job is already running: {job_id}")
        self._spawn_job(job_id)

    async def stop_job(self, job_id: str) -> None:
        """실행 중인 Job을 취소합니다."""
        task = self._running_tasks.get(job_id)
        if not task:
            raise JobStateError(f"Job is not running: {job_id}")
        task.cancel()

    def is_running(self, job_id: str) -> bool:
        return job_id in self._running_tasks


job_scheduler = JobScheduler()
