"""JobManager unit tests — CRUD, status transitions, run history, tool handling."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from open_agent.core.job_manager import (
    MAX_CONSECUTIVE_FAILURES,
    MAX_HISTORY,
    MAX_PROMPT_LENGTH,
    JobManager,
    _extract_mcp_servers_from_tools,
    validate_job_prompt,
)
from open_agent.models.job import CreateJobRequest, JobInfo, JobRunRecord, UpdateJobRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW_ISO = datetime.now(timezone.utc).isoformat()


def _make_job_info(
    job_id: str = "abc123",
    name: str = "test-job",
    prompt: str = "Do something",
    enabled: bool = True,
    schedule_type: str = "once",
    schedule_config: dict | None = None,
    run_count: int = 0,
    consecutive_failures: int = 0,
    run_history: list | None = None,
) -> JobInfo:
    return JobInfo(
        id=job_id,
        name=name,
        prompt=prompt,
        enabled=enabled,
        schedule_type=schedule_type,
        schedule_config=schedule_config or {},
        created_at=_NOW_ISO,
        updated_at=_NOW_ISO,
        run_count=run_count,
        consecutive_failures=consecutive_failures,
        run_history=run_history or [],
    )


def _make_manager_with_jobs(*jobs: JobInfo) -> JobManager:
    mgr = JobManager()
    for job in jobs:
        mgr._jobs[job.id] = job
    return mgr


@pytest.fixture()
def _mock_db():
    """Patch DB session factory and JobRepository for all lazy imports in job_manager."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.get = AsyncMock(return_value=None)
    mock_factory = MagicMock(return_value=mock_session)
    mock_repo = AsyncMock()

    with (
        patch("core.db.engine.async_session_factory", mock_factory),
        patch("core.db.repositories.job_repo.JobRepository", return_value=mock_repo),
    ):
        yield mock_session, mock_repo


# ---------------------------------------------------------------------------
# validate_job_prompt
# ---------------------------------------------------------------------------


class TestValidateJobPrompt:
    def test_valid_prompt(self):
        assert validate_job_prompt("Summarize today's news") is None

    def test_empty_prompt(self):
        result = validate_job_prompt("")
        assert result is not None

    def test_whitespace_only_prompt(self):
        result = validate_job_prompt("   ")
        assert result is not None

    def test_too_long_prompt(self):
        long_prompt = "x" * (MAX_PROMPT_LENGTH + 1)
        result = validate_job_prompt(long_prompt)
        assert result is not None
        assert str(MAX_PROMPT_LENGTH) in result

    def test_dangerous_pattern_blocked(self):
        result = validate_job_prompt("rm -rf /important")
        assert result is not None


# ---------------------------------------------------------------------------
# _extract_mcp_servers_from_tools
# ---------------------------------------------------------------------------


class TestExtractMcpServers:
    def test_extract_servers(self):
        tools = ["brave-search__brave_web_search", "github__get_repo", "local_tool"]
        servers = _extract_mcp_servers_from_tools(tools)
        assert "brave-search" in servers
        assert "github" in servers
        assert "local_tool" not in servers

    def test_empty_list(self):
        assert _extract_mcp_servers_from_tools([]) == []

    def test_no_mcp_tools(self):
        assert _extract_mcp_servers_from_tools(["tool_a", "tool_b"]) == []

    def test_sorted_output(self):
        tools = ["zzz__tool1", "aaa__tool2"]
        result = _extract_mcp_servers_from_tools(tools)
        assert result == ["aaa", "zzz"]


# ---------------------------------------------------------------------------
# JobManager CRUD
# ---------------------------------------------------------------------------


class TestJobManagerCRUD:
    def test_get_all_jobs_empty(self):
        mgr = JobManager()
        assert mgr.get_all_jobs() == []

    def test_get_all_jobs(self):
        job = _make_job_info()
        mgr = _make_manager_with_jobs(job)
        assert len(mgr.get_all_jobs()) == 1

    def test_get_job_existing(self):
        job = _make_job_info(job_id="x1")
        mgr = _make_manager_with_jobs(job)
        assert mgr.get_job("x1") is not None
        assert mgr.get_job("x1").name == "test-job"

    def test_get_job_nonexistent(self):
        mgr = JobManager()
        assert mgr.get_job("nonexistent") is None

    async def test_create_job(self):
        mgr = JobManager()
        req = CreateJobRequest(
            name="new-job",
            prompt="Do stuff",
            schedule_type="once",
            schedule_config={},
        )
        with patch.object(mgr, "_persist_job", new_callable=AsyncMock):
            job = await mgr.create_job(req)
        assert job.name == "new-job"
        assert job.prompt == "Do stuff"
        assert job.id in [j.id for j in mgr.get_all_jobs()]

    async def test_create_job_invalid_prompt(self):
        mgr = JobManager()
        req = CreateJobRequest(
            name="bad",
            prompt="",
            schedule_type="once",
            schedule_config={},
        )
        with pytest.raises(ValueError):
            with patch.object(mgr, "_persist_job", new_callable=AsyncMock):
                await mgr.create_job(req)

    async def test_create_job_replaces_same_name(self, _mock_db):
        existing = _make_job_info(job_id="old1", name="dup-job")
        mgr = _make_manager_with_jobs(existing)
        req = CreateJobRequest(
            name="dup-job",
            prompt="New version",
            schedule_type="once",
            schedule_config={},
        )
        with patch.object(mgr, "_persist_job", new_callable=AsyncMock):
            job = await mgr.create_job(req)
        # Old job removed
        assert mgr.get_job("old1") is None
        # New job exists
        assert job.prompt == "New version"

    async def test_update_job(self):
        job = _make_job_info(job_id="upd1", name="original")
        mgr = _make_manager_with_jobs(job)
        req = UpdateJobRequest(name="updated")
        with patch.object(mgr, "_persist_job", new_callable=AsyncMock):
            result = await mgr.update_job("upd1", req)
        assert result is not None
        assert result.name == "updated"

    async def test_update_job_nonexistent(self):
        mgr = JobManager()
        req = UpdateJobRequest(name="nope")
        result = await mgr.update_job("nonexistent", req)
        assert result is None

    async def test_delete_job(self, _mock_db):
        job = _make_job_info(job_id="del1")
        mgr = _make_manager_with_jobs(job)
        result = await mgr.delete_job("del1")
        assert result is True
        assert mgr.get_job("del1") is None

    async def test_delete_job_nonexistent(self):
        mgr = JobManager()
        result = await mgr.delete_job("nope")
        assert result is False


# ---------------------------------------------------------------------------
# Toggle
# ---------------------------------------------------------------------------


class TestJobToggle:
    async def test_toggle_enables(self):
        job = _make_job_info(enabled=False)
        mgr = _make_manager_with_jobs(job)
        with patch.object(mgr, "_persist_job", new_callable=AsyncMock):
            result = await mgr.toggle_job(job.id)
        assert result is not None
        assert result.enabled is True

    async def test_toggle_disables(self):
        job = _make_job_info(enabled=True)
        mgr = _make_manager_with_jobs(job)
        with patch.object(mgr, "_persist_job", new_callable=AsyncMock):
            result = await mgr.toggle_job(job.id)
        assert result is not None
        assert result.enabled is False

    async def test_toggle_nonexistent(self):
        mgr = JobManager()
        with patch.object(mgr, "_persist_job", new_callable=AsyncMock):
            result = await mgr.toggle_job("nope")
        assert result is None


# ---------------------------------------------------------------------------
# Run State & History
# ---------------------------------------------------------------------------


class TestRunStateHistory:
    async def test_start_run(self, _mock_db):
        job = _make_job_info(job_id="run1")
        mgr = _make_manager_with_jobs(job)
        with patch.object(mgr, "_persist_job", new_callable=AsyncMock):
            run_id = await mgr.start_run("run1")
        assert run_id is not None
        updated_job = mgr.get_job("run1")
        assert updated_job.last_run_status == "running"
        assert len(updated_job.run_history) == 1

    async def test_start_run_nonexistent(self):
        mgr = JobManager()
        run_id = await mgr.start_run("nope")
        assert run_id is None

    async def test_finish_run_success(self, _mock_db):
        job = _make_job_info(job_id="fin1", consecutive_failures=2)
        job.run_history = [
            JobRunRecord(run_id="r1", started_at=_NOW_ISO, status="running"),
        ]
        mgr = _make_manager_with_jobs(job)
        with patch.object(mgr, "_persist_job", new_callable=AsyncMock):
            result = await mgr.finish_run("fin1", "r1", "success", summary="Done")
        assert result is not None
        assert result.last_run_status == "success"
        assert result.consecutive_failures == 0
        assert result.run_count == 1

    async def test_finish_run_failure_increments(self, _mock_db):
        job = _make_job_info(job_id="fail1", consecutive_failures=0)
        job.run_history = [
            JobRunRecord(run_id="r1", started_at=_NOW_ISO, status="running"),
        ]
        mgr = _make_manager_with_jobs(job)
        with patch.object(mgr, "_persist_job", new_callable=AsyncMock):
            result = await mgr.finish_run("fail1", "r1", "failed", summary="Error")
        assert result.consecutive_failures == 1
        assert result.enabled is True

    async def test_finish_run_auto_disables_after_consecutive_failures(self, _mock_db):
        job = _make_job_info(
            job_id="autodis",
            consecutive_failures=MAX_CONSECUTIVE_FAILURES - 1,
        )
        job.run_history = [
            JobRunRecord(run_id="r1", started_at=_NOW_ISO, status="running"),
        ]
        mgr = _make_manager_with_jobs(job)
        with patch.object(mgr, "_persist_job", new_callable=AsyncMock):
            result = await mgr.finish_run("autodis", "r1", "failed")
        assert result.enabled is False
        assert result.consecutive_failures == MAX_CONSECUTIVE_FAILURES

    async def test_finish_run_truncates_history(self, _mock_db):
        job = _make_job_info(job_id="hist1")
        job.run_history = [
            JobRunRecord(run_id=f"r{i}", started_at=_NOW_ISO, status="running")
            for i in range(MAX_HISTORY + 1)
        ]
        mgr = _make_manager_with_jobs(job)
        with patch.object(mgr, "_persist_job", new_callable=AsyncMock):
            result = await mgr.finish_run("hist1", "r0", "success")
        assert len(result.run_history) <= MAX_HISTORY

    async def test_finish_run_nonexistent(self):
        mgr = JobManager()
        result = await mgr.finish_run("nope", "r1", "success")
        assert result is None

    async def test_finish_run_truncates_summary(self, _mock_db):
        job = _make_job_info(job_id="trunc1")
        job.run_history = [
            JobRunRecord(run_id="r1", started_at=_NOW_ISO, status="running"),
        ]
        mgr = _make_manager_with_jobs(job)
        long_summary = "x" * 5000
        with patch.object(mgr, "_persist_job", new_callable=AsyncMock):
            result = await mgr.finish_run("trunc1", "r1", "success", summary=long_summary)
        assert len(result.last_run_summary) <= 2000

    def test_get_run_history(self):
        job = _make_job_info(job_id="hist2")
        job.run_history = [
            JobRunRecord(run_id=f"r{i}", started_at=_NOW_ISO, status="success")
            for i in range(5)
        ]
        mgr = _make_manager_with_jobs(job)
        history = mgr.get_run_history("hist2", limit=3)
        assert len(history) == 3

    def test_get_run_history_nonexistent(self):
        mgr = JobManager()
        assert mgr.get_run_history("nope") == []


# ---------------------------------------------------------------------------
# set_next_run_at
# ---------------------------------------------------------------------------


class TestSetNextRunAt:
    async def test_set_next_run_at(self):
        job = _make_job_info(job_id="next1")
        mgr = _make_manager_with_jobs(job)
        with patch.object(mgr, "_persist_job", new_callable=AsyncMock):
            await mgr.set_next_run_at("next1", "2025-01-01T00:00:00Z")
        assert mgr.get_job("next1").next_run_at == "2025-01-01T00:00:00Z"

    async def test_set_next_run_at_nonexistent(self):
        mgr = JobManager()
        # Should not raise
        await mgr.set_next_run_at("nope", "2025-01-01T00:00:00Z")


# ---------------------------------------------------------------------------
# _format_schedule_text
# ---------------------------------------------------------------------------


class TestFormatScheduleText:
    def test_interval(self):
        job = _make_job_info(schedule_type="interval", schedule_config={"interval_minutes": 30})
        text = JobManager._format_schedule_text(job)
        assert "30" in text

    def test_daily(self):
        job = _make_job_info(schedule_type="daily", schedule_config={"hour": 9, "minute": 0})
        text = JobManager._format_schedule_text(job)
        assert "09:00" in text

    def test_weekly(self):
        job = _make_job_info(
            schedule_type="weekly",
            schedule_config={"weekday": 1, "hour": 10, "minute": 30},
        )
        text = JobManager._format_schedule_text(job)
        assert "10:30" in text

    def test_cron(self):
        job = _make_job_info(
            schedule_type="cron",
            schedule_config={"cron_expr": "0 9 * * 1-5"},
        )
        text = JobManager._format_schedule_text(job)
        assert "0 9 * * 1-5" in text

    def test_once_with_run_at(self):
        job = _make_job_info(
            schedule_type="once",
            schedule_config={"run_at": "2025-01-01T00:00:00"},
        )
        text = JobManager._format_schedule_text(job)
        assert "2025-01-01" in text

    def test_once_immediate(self):
        job = _make_job_info(schedule_type="once", schedule_config={})
        text = JobManager._format_schedule_text(job)
        assert "1회" in text


# ---------------------------------------------------------------------------
# handle_tool_call
# ---------------------------------------------------------------------------


class TestHandleToolCall:
    async def test_list_scheduled_tasks_empty(self):
        mgr = JobManager()
        result = await mgr.handle_tool_call("list_scheduled_tasks", {})
        assert "없습니다" in result

    async def test_list_scheduled_tasks_with_jobs(self):
        job = _make_job_info(job_id="list1", name="My Job")
        mgr = _make_manager_with_jobs(job)
        result = await mgr.handle_tool_call("list_scheduled_tasks", {})
        assert "My Job" in result
        assert "list1" in result

    async def test_delete_by_id(self):
        job = _make_job_info(job_id="del1", name="Delete Me")
        mgr = _make_manager_with_jobs(job)
        with patch.object(mgr, "delete_job", new_callable=AsyncMock, return_value=True):
            result = await mgr.handle_tool_call("delete_scheduled_task", {"job_id": "del1"})
        assert "Delete Me" in result

    async def test_delete_by_name(self):
        job = _make_job_info(job_id="del2", name="Named Job")
        mgr = _make_manager_with_jobs(job)
        with patch.object(mgr, "delete_job", new_callable=AsyncMock, return_value=True):
            result = await mgr.handle_tool_call(
                "delete_scheduled_task", {"name": "Named Job"}
            )
        assert "Named Job" in result

    async def test_delete_missing_id_and_name(self):
        mgr = JobManager()
        result = await mgr.handle_tool_call("delete_scheduled_task", {})
        assert "Error" in result

    async def test_delete_nonexistent_name(self):
        mgr = JobManager()
        result = await mgr.handle_tool_call(
            "delete_scheduled_task", {"name": "Nonexistent"}
        )
        assert "Error" in result

    async def test_unknown_tool(self):
        mgr = JobManager()
        result = await mgr.handle_tool_call("unknown_tool", {})
        assert "Unknown" in result or "Error" in result


# ---------------------------------------------------------------------------
# Concurrency (lock)
# ---------------------------------------------------------------------------


class TestConcurrency:
    async def test_lock_protects_create(self):
        mgr = JobManager()
        assert isinstance(mgr._lock, asyncio.Lock)
        assert not mgr._lock.locked()
