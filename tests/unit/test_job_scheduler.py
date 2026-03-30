"""JobScheduler unit tests — cron parsing, next run calculation, scheduler lifecycle."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from open_agent.core.exceptions import JobNotFoundError, JobStateError
from open_agent.core.job_scheduler import (
    CHECK_INTERVAL,
    MAX_CONCURRENT_JOBS,
    JobScheduler,
    _get_schedule_tz,
    calc_next_run,
)
from open_agent.models.job import JobInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)


def _make_job(
    job_id: str = "test1",
    schedule_type: str = "once",
    schedule_config: dict | None = None,
    enabled: bool = True,
    last_run_at: str | None = None,
    next_run_at: str | None = None,
) -> JobInfo:
    return JobInfo(
        id=job_id,
        name=f"job-{job_id}",
        prompt="Do something",
        enabled=enabled,
        schedule_type=schedule_type,
        schedule_config=schedule_config or {},
        created_at=_NOW.isoformat(),
        updated_at=_NOW.isoformat(),
        last_run_at=last_run_at,
        next_run_at=next_run_at,
    )


# ---------------------------------------------------------------------------
# _get_schedule_tz
# ---------------------------------------------------------------------------


class TestGetScheduleTz:
    def test_default_local_timezone(self):
        tz = _get_schedule_tz({})
        assert tz is not None

    def test_valid_timezone(self):
        tz = _get_schedule_tz({"timezone": "US/Eastern"})
        assert tz is not None

    def test_invalid_timezone_fallback(self):
        tz = _get_schedule_tz({"timezone": "Invalid/Zone"})
        # Falls back to local timezone
        assert tz is not None


# ---------------------------------------------------------------------------
# calc_next_run
# ---------------------------------------------------------------------------


class TestCalcNextRun:
    def test_once_no_run_at(self):
        job = _make_job(schedule_type="once", schedule_config={})
        assert calc_next_run(job, after=_NOW) is None

    def test_once_past_run_at(self):
        past = (_NOW - timedelta(hours=1)).isoformat()
        job = _make_job(schedule_type="once", schedule_config={"run_at": past})
        assert calc_next_run(job, after=_NOW) is None

    def test_once_future_run_at(self):
        future = (_NOW + timedelta(hours=1)).isoformat()
        job = _make_job(schedule_type="once", schedule_config={"run_at": future})
        result = calc_next_run(job, after=_NOW)
        assert result is not None
        assert result > _NOW

    def test_once_invalid_run_at(self):
        job = _make_job(schedule_type="once", schedule_config={"run_at": "not-a-date"})
        assert calc_next_run(job, after=_NOW) is None

    def test_interval_no_last_run(self):
        job = _make_job(
            schedule_type="interval",
            schedule_config={"interval_minutes": 30},
        )
        result = calc_next_run(job, after=_NOW)
        assert result is not None
        # Should be shortly after base (10 seconds)
        assert result - _NOW < timedelta(minutes=1)

    def test_interval_with_last_run(self):
        last = (_NOW - timedelta(minutes=10)).isoformat()
        job = _make_job(
            schedule_type="interval",
            schedule_config={"interval_minutes": 30},
            last_run_at=last,
        )
        result = calc_next_run(job, after=_NOW)
        assert result is not None

    def test_interval_overdue(self):
        """If interval has passed since last run, next run is soon."""
        last = (_NOW - timedelta(hours=2)).isoformat()
        job = _make_job(
            schedule_type="interval",
            schedule_config={"interval_minutes": 30},
            last_run_at=last,
        )
        result = calc_next_run(job, after=_NOW)
        assert result is not None
        # When overdue, returns base + 10s
        assert result - _NOW < timedelta(minutes=1)

    def test_daily(self):
        job = _make_job(
            schedule_type="daily",
            schedule_config={"hour": 14, "minute": 30},
        )
        result = calc_next_run(job, after=_NOW)
        assert result is not None
        # Should be a future datetime
        assert result > _NOW

    def test_daily_already_passed_today(self):
        # Now is 12:00 UTC, target is 09:00 — should schedule for tomorrow
        job = _make_job(
            schedule_type="daily",
            schedule_config={"hour": 9, "minute": 0},
        )
        result = calc_next_run(job, after=_NOW)
        assert result is not None
        assert result > _NOW

    def test_weekly(self):
        job = _make_job(
            schedule_type="weekly",
            schedule_config={"weekday": 1, "hour": 9, "minute": 0},
        )
        result = calc_next_run(job, after=_NOW)
        assert result is not None
        assert result > _NOW

    def test_cron(self):
        job = _make_job(
            schedule_type="cron",
            schedule_config={"cron_expr": "0 9 * * 1-5"},
        )
        result = calc_next_run(job, after=_NOW)
        assert result is not None
        assert result > _NOW

    def test_cron_invalid_expression(self):
        job = _make_job(
            schedule_type="cron",
            schedule_config={"cron_expr": "not valid cron"},
        )
        assert calc_next_run(job, after=_NOW) is None

    def test_unknown_schedule_type(self):
        job = _make_job(schedule_type="once", schedule_config={})
        # Manually override (bypassing validation) to test fallback
        job.schedule_type = "unknown"
        assert calc_next_run(job, after=_NOW) is None

    def test_cron_with_timezone(self):
        job = _make_job(
            schedule_type="cron",
            schedule_config={"cron_expr": "30 14 * * *", "timezone": "US/Eastern"},
        )
        result = calc_next_run(job, after=_NOW)
        assert result is not None
        assert result.tzinfo == timezone.utc

    def test_daily_with_timezone(self):
        job = _make_job(
            schedule_type="daily",
            schedule_config={"hour": 9, "minute": 0, "timezone": "Asia/Seoul"},
        )
        result = calc_next_run(job, after=_NOW)
        assert result is not None
        assert result.tzinfo == timezone.utc

    def test_weekly_with_timezone(self):
        job = _make_job(
            schedule_type="weekly",
            schedule_config={"weekday": 3, "hour": 15, "minute": 0, "timezone": "Europe/London"},
        )
        result = calc_next_run(job, after=_NOW)
        assert result is not None
        assert result.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# JobScheduler lifecycle
# ---------------------------------------------------------------------------


class TestSchedulerLifecycle:
    async def test_start_creates_task(self):
        scheduler = JobScheduler()
        with patch.object(scheduler, "_loop", new_callable=AsyncMock):
            with patch.object(scheduler, "_refresh_all_next_run", new_callable=AsyncMock):
                await scheduler.start()
        assert scheduler._task is not None
        # Cleanup
        await scheduler.stop()

    async def test_start_idempotent(self):
        scheduler = JobScheduler()
        with patch.object(scheduler, "_loop", new_callable=AsyncMock):
            with patch.object(scheduler, "_refresh_all_next_run", new_callable=AsyncMock):
                await scheduler.start()
                task1 = scheduler._task
                await scheduler.start()  # second call should be no-op
                assert scheduler._task is task1
        await scheduler.stop()

    async def test_stop_cancels_task(self):
        scheduler = JobScheduler()
        with patch.object(scheduler, "_loop", new_callable=AsyncMock):
            with patch.object(scheduler, "_refresh_all_next_run", new_callable=AsyncMock):
                await scheduler.start()
        await scheduler.stop()
        assert scheduler._task is None
        assert len(scheduler._running_tasks) == 0

    async def test_stop_cancels_running_jobs(self):
        scheduler = JobScheduler()
        mock_running = MagicMock()
        mock_running.cancel = MagicMock()
        scheduler._running_tasks["job1"] = mock_running

        # Create a real cancellable task for _task
        async def _noop():
            await asyncio.sleep(100)

        scheduler._task = asyncio.create_task(_noop())
        await scheduler.stop()
        mock_running.cancel.assert_called_once()
        assert len(scheduler._running_tasks) == 0


# ---------------------------------------------------------------------------
# Tick logic
# ---------------------------------------------------------------------------


class TestSchedulerTick:
    async def test_tick_triggers_due_job(self):
        scheduler = JobScheduler()
        # Use a time definitely in the past relative to _NOW
        past_time = (_NOW - timedelta(minutes=5)).isoformat()
        job = _make_job(
            job_id="due1",
            enabled=True,
            next_run_at=past_time,
        )

        with patch("open_agent.core.job_scheduler.job_manager") as mock_jm:
            mock_jm.get_all_jobs.return_value = [job]
            with patch.object(scheduler, "_spawn_job") as mock_spawn:
                # Mock datetime.now to return _NOW so past_time is in the past
                with patch("open_agent.core.job_scheduler.datetime") as mock_dt:
                    mock_dt.now.return_value = _NOW
                    mock_dt.fromisoformat = datetime.fromisoformat
                    await scheduler._tick()
                mock_spawn.assert_called_once_with("due1")

    async def test_tick_skips_disabled_job(self):
        scheduler = JobScheduler()
        past_time = (_NOW - timedelta(minutes=5)).isoformat()
        job = _make_job(job_id="dis1", enabled=False, next_run_at=past_time)

        with patch("open_agent.core.job_scheduler.job_manager") as mock_jm:
            mock_jm.get_all_jobs.return_value = [job]
            with patch.object(scheduler, "_spawn_job") as mock_spawn:
                with patch("open_agent.core.job_scheduler.datetime") as mock_dt:
                    mock_dt.now.return_value = _NOW
                    mock_dt.fromisoformat = datetime.fromisoformat
                    await scheduler._tick()
                mock_spawn.assert_not_called()

    async def test_tick_skips_running_job(self):
        scheduler = JobScheduler()
        past_time = (_NOW - timedelta(minutes=5)).isoformat()
        job = _make_job(job_id="running1", enabled=True, next_run_at=past_time)
        scheduler._running_tasks["running1"] = AsyncMock()

        with patch("open_agent.core.job_scheduler.job_manager") as mock_jm:
            mock_jm.get_all_jobs.return_value = [job]
            with patch.object(scheduler, "_spawn_job") as mock_spawn:
                with patch("open_agent.core.job_scheduler.datetime") as mock_dt:
                    mock_dt.now.return_value = _NOW
                    mock_dt.fromisoformat = datetime.fromisoformat
                    await scheduler._tick()
                mock_spawn.assert_not_called()

    async def test_tick_skips_no_next_run(self):
        scheduler = JobScheduler()
        job = _make_job(job_id="nonext", enabled=True, next_run_at=None)

        with patch("open_agent.core.job_scheduler.job_manager") as mock_jm:
            mock_jm.get_all_jobs.return_value = [job]
            with patch.object(scheduler, "_spawn_job") as mock_spawn:
                await scheduler._tick()
                mock_spawn.assert_not_called()

    async def test_tick_skips_future_job(self):
        scheduler = JobScheduler()
        future = (_NOW + timedelta(hours=1)).isoformat()
        job = _make_job(job_id="future1", enabled=True, next_run_at=future)

        with patch("open_agent.core.job_scheduler.job_manager") as mock_jm:
            mock_jm.get_all_jobs.return_value = [job]
            with patch.object(scheduler, "_spawn_job") as mock_spawn:
                with patch("open_agent.core.job_scheduler.datetime") as mock_dt:
                    mock_dt.now.return_value = _NOW
                    mock_dt.fromisoformat = datetime.fromisoformat
                    await scheduler._tick()
                mock_spawn.assert_not_called()

    async def test_tick_invalid_next_run_at(self):
        scheduler = JobScheduler()
        job = _make_job(job_id="invalid1", enabled=True, next_run_at="not-a-date")

        with patch("open_agent.core.job_scheduler.job_manager") as mock_jm:
            mock_jm.get_all_jobs.return_value = [job]
            with patch.object(scheduler, "_spawn_job") as mock_spawn:
                await scheduler._tick()
                mock_spawn.assert_not_called()


# ---------------------------------------------------------------------------
# run_now / stop_job / is_running
# ---------------------------------------------------------------------------


class TestManualControls:
    async def test_run_now_success(self):
        scheduler = JobScheduler()
        job = _make_job(job_id="manual1")

        with patch("open_agent.core.job_scheduler.job_manager") as mock_jm:
            mock_jm.get_job.return_value = job
            with patch.object(scheduler, "_spawn_job") as mock_spawn:
                await scheduler.run_now("manual1")
                mock_spawn.assert_called_once_with("manual1")

    async def test_run_now_not_found(self):
        scheduler = JobScheduler()
        with patch("open_agent.core.job_scheduler.job_manager") as mock_jm:
            mock_jm.get_job.return_value = None
            with pytest.raises(JobNotFoundError):
                await scheduler.run_now("nope")

    async def test_run_now_already_running(self):
        scheduler = JobScheduler()
        job = _make_job(job_id="running1")
        scheduler._running_tasks["running1"] = AsyncMock()

        with patch("open_agent.core.job_scheduler.job_manager") as mock_jm:
            mock_jm.get_job.return_value = job
            with pytest.raises(JobStateError):
                await scheduler.run_now("running1")

    async def test_stop_job_running(self):
        scheduler = JobScheduler()
        mock_task = MagicMock()
        scheduler._running_tasks["stop1"] = mock_task
        await scheduler.stop_job("stop1")
        mock_task.cancel.assert_called_once()

    async def test_stop_job_not_running(self):
        scheduler = JobScheduler()
        with pytest.raises(JobStateError):
            await scheduler.stop_job("nope")

    def test_is_running(self):
        scheduler = JobScheduler()
        assert scheduler.is_running("x") is False
        scheduler._running_tasks["x"] = MagicMock()
        assert scheduler.is_running("x") is True


# ---------------------------------------------------------------------------
# refresh_job
# ---------------------------------------------------------------------------


class TestRefreshJob:
    def test_refresh_disabled_job(self):
        scheduler = JobScheduler()
        job = _make_job(enabled=False)

        with patch("open_agent.core.job_scheduler.job_manager") as mock_jm:
            mock_jm.get_job.return_value = job
            mock_jm.set_next_run_at = AsyncMock()
            # Patch asyncio.ensure_future to capture the call
            with patch("asyncio.ensure_future") as mock_ef:
                scheduler.refresh_job("test1")
                mock_ef.assert_called_once()

    def test_refresh_nonexistent_job(self):
        scheduler = JobScheduler()
        with patch("open_agent.core.job_scheduler.job_manager") as mock_jm:
            mock_jm.get_job.return_value = None
            with patch("asyncio.ensure_future") as mock_ef:
                scheduler.refresh_job("nope")
                mock_ef.assert_called_once()

    def test_refresh_enabled_job(self):
        scheduler = JobScheduler()
        future = (_NOW + timedelta(hours=1)).isoformat()
        job = _make_job(
            enabled=True,
            schedule_type="daily",
            schedule_config={"hour": 9, "minute": 0},
        )

        with patch("open_agent.core.job_scheduler.job_manager") as mock_jm:
            mock_jm.get_job.return_value = job
            with patch("asyncio.ensure_future") as mock_ef:
                scheduler.refresh_job("test1")
                mock_ef.assert_called_once()


# ---------------------------------------------------------------------------
# _run_job
# ---------------------------------------------------------------------------


class TestRunJob:
    async def test_run_job_success(self):
        scheduler = JobScheduler()

        with (
            patch("open_agent.core.job_scheduler.job_manager") as mock_jm,
            patch("open_agent.core.job_scheduler.execute_job", new_callable=AsyncMock) as mock_exec,
        ):
            mock_jm.start_run = AsyncMock(return_value="run1")
            mock_jm.finish_run = AsyncMock()
            mock_jm.get_job.return_value = _make_job()
            mock_jm.set_next_run_at = AsyncMock()
            mock_exec.return_value = "Job completed successfully"

            # Patch refresh_job to avoid asyncio.ensure_future without event loop issues
            with patch.object(scheduler, "refresh_job"):
                await scheduler._run_job("test1")

            mock_jm.finish_run.assert_called_once()
            call_args = mock_jm.finish_run.call_args
            assert call_args[0][2] == "success"

    async def test_run_job_start_fails(self):
        scheduler = JobScheduler()

        with patch("open_agent.core.job_scheduler.job_manager") as mock_jm:
            mock_jm.start_run = AsyncMock(return_value=None)
            mock_jm.get_job.return_value = _make_job()
            mock_jm.set_next_run_at = AsyncMock()
            with patch.object(scheduler, "refresh_job"):
                await scheduler._run_job("test1")
            mock_jm.finish_run.assert_not_called()

    async def test_run_job_execution_failure(self):
        scheduler = JobScheduler()

        with (
            patch("open_agent.core.job_scheduler.job_manager") as mock_jm,
            patch(
                "open_agent.core.job_scheduler.execute_job",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
        ):
            mock_jm.start_run = AsyncMock(return_value="run1")
            mock_jm.finish_run = AsyncMock()
            mock_jm.get_job.return_value = _make_job()
            mock_jm.set_next_run_at = AsyncMock()

            with patch.object(scheduler, "refresh_job"):
                await scheduler._run_job("test1")

            mock_jm.finish_run.assert_called_once()
            call_args = mock_jm.finish_run.call_args
            assert call_args[0][2] == "failed"

    async def test_run_job_timeout(self):
        scheduler = JobScheduler()

        with (
            patch("open_agent.core.job_scheduler.job_manager") as mock_jm,
            patch(
                "open_agent.core.job_scheduler.execute_job",
                new_callable=AsyncMock,
                side_effect=asyncio.TimeoutError(),
            ),
        ):
            mock_jm.start_run = AsyncMock(return_value="run1")
            mock_jm.finish_run = AsyncMock()
            mock_jm.get_job.return_value = _make_job()
            mock_jm.set_next_run_at = AsyncMock()

            with patch.object(scheduler, "refresh_job"):
                await scheduler._run_job("test1")

            mock_jm.finish_run.assert_called_once()
            call_args = mock_jm.finish_run.call_args
            assert call_args[0][2] == "timeout"


# ---------------------------------------------------------------------------
# Semaphore (MAX_CONCURRENT_JOBS)
# ---------------------------------------------------------------------------


class TestSemaphore:
    def test_semaphore_limit(self):
        scheduler = JobScheduler()
        assert scheduler._semaphore._value == MAX_CONCURRENT_JOBS
