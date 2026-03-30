"""JobExecutor unit tests — execution, timeout, error propagation."""

import asyncio
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from open_agent.core.exceptions import JobNotFoundError
from open_agent.models.job import JobInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc).isoformat()


def _make_job(
    job_id: str = "exec1",
    name: str = "test-job",
    prompt: str = "Summarize news",
    skill_names: list | None = None,
    mcp_server_names: list | None = None,
) -> JobInfo:
    return JobInfo(
        id=job_id,
        name=name,
        prompt=prompt,
        skill_names=skill_names or [],
        mcp_server_names=mcp_server_names or [],
        schedule_type="once",
        schedule_config={},
        created_at=_NOW,
        updated_at=_NOW,
    )


def _mock_response(content: str = "Result text") -> dict:
    return {
        "choices": [
            {"message": {"content": content}}
        ]
    }


@pytest.fixture(autouse=True)
def _mock_agent_module():
    """Prevent importing core.agent (has syntax error in test env).

    We inject a fake module with a mock orchestrator so that
    ``from open_agent.core.agent import orchestrator`` works inside execute_job.
    """
    mock_orchestrator = MagicMock()
    mock_orchestrator.run = AsyncMock(return_value=_mock_response())

    fake_agent_module = MagicMock()
    fake_agent_module.orchestrator = mock_orchestrator

    original = sys.modules.get("open_agent.core.agent")
    sys.modules["open_agent.core.agent"] = fake_agent_module
    yield mock_orchestrator
    if original is not None:
        sys.modules["open_agent.core.agent"] = original
    else:
        sys.modules.pop("open_agent.core.agent", None)


@pytest.fixture()
def mock_job_manager():
    with patch("open_agent.core.job_executor.job_manager") as mock_jm:
        yield mock_jm


@pytest.fixture()
def mock_skill_manager():
    """Mock skill_manager accessed via lazy import inside execute_job."""
    mock_sm = MagicMock()
    mock_sm.load_skill_content.return_value = None
    original = sys.modules.get("open_agent.core.skill_manager")
    if original:
        with patch.object(original, "skill_manager", mock_sm):
            yield mock_sm
    else:
        fake_module = MagicMock()
        fake_module.skill_manager = mock_sm
        sys.modules["open_agent.core.skill_manager"] = fake_module
        yield mock_sm
        sys.modules.pop("open_agent.core.skill_manager", None)


@pytest.fixture()
def mock_mcp_manager():
    """Mock mcp_manager accessed via lazy import inside execute_job."""
    mock_mcp = MagicMock()
    mock_mcp.get_tools_for_server = AsyncMock(return_value=[])
    original = sys.modules.get("open_agent.core.mcp_manager")
    if original:
        with patch.object(original, "mcp_manager", mock_mcp):
            yield mock_mcp
    else:
        fake_module = MagicMock()
        fake_module.mcp_manager = mock_mcp
        sys.modules["open_agent.core.mcp_manager"] = fake_module
        yield mock_mcp
        sys.modules.pop("open_agent.core.mcp_manager", None)


# ---------------------------------------------------------------------------
# Basic execution
# ---------------------------------------------------------------------------


class TestExecuteJob:
    async def test_execute_success(
        self, _mock_agent_module, mock_job_manager, mock_skill_manager, mock_mcp_manager
    ):
        from open_agent.core.job_executor import execute_job

        job = _make_job()
        mock_job_manager.get_job.return_value = job
        _mock_agent_module.run.return_value = _mock_response("Job done")

        result = await execute_job("exec1")
        assert "Job done" in result

    async def test_execute_not_found(
        self, _mock_agent_module, mock_job_manager, mock_skill_manager, mock_mcp_manager
    ):
        from open_agent.core.job_executor import execute_job

        mock_job_manager.get_job.return_value = None
        with pytest.raises(JobNotFoundError):
            await execute_job("nonexistent")

    async def test_execute_with_skills(
        self, _mock_agent_module, mock_job_manager, mock_skill_manager, mock_mcp_manager
    ):
        from open_agent.core.job_executor import execute_job

        job = _make_job(skill_names=["summarizer"])
        mock_job_manager.get_job.return_value = job

        mock_detail = MagicMock()
        mock_detail.content = "## Summarizer skill instructions"
        mock_skill_manager.load_skill_content.return_value = mock_detail

        _mock_agent_module.run.return_value = _mock_response("Summarized")

        result = await execute_job("exec1")
        assert "Summarized" in result
        call_args = _mock_agent_module.run.call_args[0][0]
        system_msgs = [m for m in call_args if m["role"] == "system"]
        assert len(system_msgs) == 1
        assert "Summarizer" in system_msgs[0]["content"]

    async def test_execute_with_mcp_servers(
        self, _mock_agent_module, mock_job_manager, mock_skill_manager, mock_mcp_manager
    ):
        from open_agent.core.job_executor import execute_job

        job = _make_job(mcp_server_names=["brave-search"])
        mock_job_manager.get_job.return_value = job

        mock_tool = MagicMock()
        mock_tool.name = "web_search"
        mock_tool.description = "Search the web"
        mock_mcp_manager.get_tools_for_server = AsyncMock(return_value=[mock_tool])

        _mock_agent_module.run.return_value = _mock_response("Searched")

        result = await execute_job("exec1")
        assert "Searched" in result
        call_args = _mock_agent_module.run.call_args[0][0]
        system_msgs = [m for m in call_args if m["role"] == "system"]
        assert len(system_msgs) == 1
        assert "brave-search" in system_msgs[0]["content"]

    async def test_execute_no_skills_no_mcp(
        self, _mock_agent_module, mock_job_manager, mock_skill_manager, mock_mcp_manager
    ):
        """When no skills or MCP servers, only user message is sent."""
        from open_agent.core.job_executor import execute_job

        job = _make_job()
        mock_job_manager.get_job.return_value = job
        _mock_agent_module.run.return_value = _mock_response("plain")

        result = await execute_job("exec1")
        call_args = _mock_agent_module.run.call_args[0][0]
        system_msgs = [m for m in call_args if m["role"] == "system"]
        assert len(system_msgs) == 0
        user_msgs = [m for m in call_args if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert user_msgs[0]["content"] == "Summarize news"


# ---------------------------------------------------------------------------
# Output truncation
# ---------------------------------------------------------------------------


class TestOutputTruncation:
    async def test_long_output_truncated(
        self, _mock_agent_module, mock_job_manager, mock_skill_manager, mock_mcp_manager
    ):
        from open_agent.core.job_executor import execute_job

        job = _make_job()
        mock_job_manager.get_job.return_value = job
        _mock_agent_module.run.return_value = _mock_response("x" * 5000)

        result = await execute_job("exec1")
        assert len(result) <= 2000

    async def test_empty_output_returns_placeholder(
        self, _mock_agent_module, mock_job_manager, mock_skill_manager, mock_mcp_manager
    ):
        from open_agent.core.job_executor import execute_job

        job = _make_job()
        mock_job_manager.get_job.return_value = job
        _mock_agent_module.run.return_value = _mock_response("")

        result = await execute_job("exec1")
        assert result == "(no output)"


# ---------------------------------------------------------------------------
# Timeout constant
# ---------------------------------------------------------------------------


class TestTimeout:
    def test_timeout_constant(self):
        from open_agent.core.job_executor import JOB_TIMEOUT

        assert JOB_TIMEOUT == 300


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    async def test_orchestrator_exception_propagates(
        self, _mock_agent_module, mock_job_manager, mock_skill_manager, mock_mcp_manager
    ):
        from open_agent.core.job_executor import execute_job

        job = _make_job()
        mock_job_manager.get_job.return_value = job
        _mock_agent_module.run = AsyncMock(side_effect=RuntimeError("LLM failed"))

        with pytest.raises(RuntimeError, match="LLM failed"):
            await execute_job("exec1")

    async def test_timeout_error_propagates(
        self, _mock_agent_module, mock_job_manager, mock_skill_manager, mock_mcp_manager
    ):
        from open_agent.core.job_executor import execute_job

        job = _make_job()
        mock_job_manager.get_job.return_value = job
        _mock_agent_module.run = AsyncMock(side_effect=asyncio.TimeoutError())

        with pytest.raises(asyncio.TimeoutError):
            await execute_job("exec1")

    async def test_skill_content_none_is_skipped(
        self, _mock_agent_module, mock_job_manager, mock_skill_manager, mock_mcp_manager
    ):
        """If load_skill_content returns None, no system message is injected."""
        from open_agent.core.job_executor import execute_job

        job = _make_job(skill_names=["missing-skill"])
        mock_job_manager.get_job.return_value = job
        mock_skill_manager.load_skill_content.return_value = None
        _mock_agent_module.run.return_value = _mock_response("ok")

        result = await execute_job("exec1")
        assert result == "ok"
        call_args = _mock_agent_module.run.call_args[0][0]
        system_msgs = [m for m in call_args if m["role"] == "system"]
        assert len(system_msgs) == 0

    async def test_mcp_empty_tools_skipped(
        self, _mock_agent_module, mock_job_manager, mock_skill_manager, mock_mcp_manager
    ):
        """If MCP server has no tools, its section is not injected."""
        from open_agent.core.job_executor import execute_job

        job = _make_job(mcp_server_names=["empty-server"])
        mock_job_manager.get_job.return_value = job
        mock_mcp_manager.get_tools_for_server = AsyncMock(return_value=[])
        _mock_agent_module.run.return_value = _mock_response("ok")

        result = await execute_job("exec1")
        call_args = _mock_agent_module.run.call_args[0][0]
        system_msgs = [m for m in call_args if m["role"] == "system"]
        assert len(system_msgs) == 0
