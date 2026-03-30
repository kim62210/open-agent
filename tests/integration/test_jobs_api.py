"""Jobs API integration tests — CRUD, toggle, run/stop."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from open_agent.models.job import JobInfo


@pytest.fixture()
async def jobs_client(_patch_db_factory, monkeypatch):
    """httpx.AsyncClient wired to jobs router with mocked managers."""
    import httpx
    from fastapi import FastAPI
    from httpx import ASGITransport

    monkeypatch.setitem(sys.modules, "croniter", MagicMock())

    from open_agent.api.endpoints import jobs as jobs_router

    from core.auth.dependencies import get_current_user

    test_app = FastAPI()
    test_app.include_router(jobs_router.router, prefix="/api/jobs")

    async def _fake_current_user() -> dict:
        return {
            "id": "test-user-id",
            "email": "test@example.com",
            "username": "testuser",
            "role": "admin",
        }

    test_app.dependency_overrides[get_current_user] = _fake_current_user

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _make_job_info(id="job-1", name="Test Job"):
    return JobInfo(
        id=id,
        name=name,
        description="",
        prompt="Do something",
        skill_names=[],
        mcp_server_names=[],
        schedule_type="once",
        schedule_config={},
        enabled=True,
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )


class TestListJobs:
    """GET /api/jobs/"""

    async def test_list_jobs_empty(self, jobs_client: AsyncClient):
        """Returns empty list when no jobs exist."""
        with patch("open_agent.api.endpoints.jobs.job_manager") as mock_jm:
            mock_jm.get_all_jobs.return_value = []
            resp = await jobs_client.get("/api/jobs/")
        assert resp.status_code == 200
        assert resp.json() == []


class TestGetJob:
    """GET /api/jobs/{job_id}"""

    async def test_get_job_found(self, jobs_client: AsyncClient):
        """Returns job by ID."""
        job = _make_job_info()
        with patch("open_agent.api.endpoints.jobs.job_manager") as mock_jm:
            mock_jm.get_job.return_value = job
            resp = await jobs_client.get("/api/jobs/job-1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "job-1"

    async def test_get_job_not_found(self, jobs_client: AsyncClient):
        """Returns 404 for non-existent job."""
        with patch("open_agent.api.endpoints.jobs.job_manager") as mock_jm:
            mock_jm.get_job.return_value = None
            resp = await jobs_client.get("/api/jobs/nonexistent")
        assert resp.status_code == 404


class TestCreateJob:
    """POST /api/jobs/"""

    async def test_create_job(self, jobs_client: AsyncClient):
        """Creates a job successfully."""
        job = _make_job_info()
        with patch("open_agent.api.endpoints.jobs.job_manager") as mock_jm:
            with patch("open_agent.api.endpoints.jobs.job_scheduler") as mock_sched:
                with patch("open_agent.api.endpoints.jobs.validate_job_prompt", return_value=None):
                    mock_jm.create_job = AsyncMock(return_value=job)
                    mock_sched.refresh_job = MagicMock()
                    resp = await jobs_client.post(
                        "/api/jobs/",
                        json={"name": "Test Job", "prompt": "Do something"},
                    )
        assert resp.status_code == 200
        mock_jm.create_job.assert_awaited_once()
        assert mock_jm.create_job.await_args.kwargs["owner_user_id"] == "test-user-id"

    async def test_create_job_invalid_prompt(self, jobs_client: AsyncClient):
        """Returns 400 for invalid prompt."""
        with patch(
            "open_agent.api.endpoints.jobs.validate_job_prompt", return_value="Prompt too short"
        ):
            resp = await jobs_client.post(
                "/api/jobs/",
                json={"name": "Bad Job", "prompt": "x"},
            )
        assert resp.status_code == 400


class TestDeleteJob:
    """DELETE /api/jobs/{job_id}"""

    async def test_delete_job(self, jobs_client: AsyncClient):
        """Deletes job successfully."""
        with patch("open_agent.api.endpoints.jobs.job_manager") as mock_jm:
            with patch("open_agent.api.endpoints.jobs.job_scheduler") as mock_sched:
                mock_sched.is_running.return_value = False
                mock_jm.delete_job = AsyncMock(return_value=True)
                resp = await jobs_client.delete("/api/jobs/job-1")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    async def test_delete_nonexistent_job(self, jobs_client: AsyncClient):
        """Returns 404 for non-existent job."""
        with patch("open_agent.api.endpoints.jobs.job_manager") as mock_jm:
            with patch("open_agent.api.endpoints.jobs.job_scheduler") as mock_sched:
                mock_sched.is_running.return_value = False
                mock_jm.delete_job = AsyncMock(return_value=False)
                resp = await jobs_client.delete("/api/jobs/nonexistent")
        assert resp.status_code == 404


class TestToggleJob:
    """POST /api/jobs/{job_id}/toggle"""

    async def test_toggle_job(self, jobs_client: AsyncClient):
        """Toggles job enabled state."""
        job = _make_job_info()
        with patch("open_agent.api.endpoints.jobs.job_manager") as mock_jm:
            with patch("open_agent.api.endpoints.jobs.job_scheduler") as mock_sched:
                mock_jm.toggle_job = AsyncMock(return_value=job)
                mock_sched.refresh_job = MagicMock()
                resp = await jobs_client.post("/api/jobs/job-1/toggle")
        assert resp.status_code == 200

    async def test_toggle_nonexistent_job(self, jobs_client: AsyncClient):
        """Returns 404 for non-existent job."""
        with patch("open_agent.api.endpoints.jobs.job_manager") as mock_jm:
            with patch("open_agent.api.endpoints.jobs.job_scheduler"):
                mock_jm.toggle_job = AsyncMock(return_value=None)
                resp = await jobs_client.post("/api/jobs/nonexistent/toggle")
        assert resp.status_code == 404


class TestRunJob:
    """POST /api/jobs/{job_id}/run"""

    async def test_run_job(self, jobs_client: AsyncClient):
        """Manual job run returns started status."""
        with patch("open_agent.api.endpoints.jobs.job_scheduler") as mock_sched:
            mock_sched.run_now = AsyncMock()
            resp = await jobs_client.post("/api/jobs/job-1/run")
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"


class TestGetJobHistory:
    """GET /api/jobs/{job_id}/history"""

    async def test_get_history(self, jobs_client: AsyncClient):
        """Returns job run history."""
        with patch("open_agent.api.endpoints.jobs.job_manager") as mock_jm:
            mock_jm.get_job.return_value = _make_job_info()
            mock_jm.get_run_history.return_value = []
            resp = await jobs_client.get("/api/jobs/job-1/history")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_get_history_nonexistent_job(self, jobs_client: AsyncClient):
        """Returns 404 for non-existent job history."""
        with patch("open_agent.api.endpoints.jobs.job_manager") as mock_jm:
            mock_jm.get_job.return_value = None
            resp = await jobs_client.get("/api/jobs/nonexistent/history")
        assert resp.status_code == 404


class TestUpdateJob:
    """PATCH /api/jobs/{job_id}"""

    async def test_update_job(self, jobs_client: AsyncClient):
        """Updates job name and prompt."""
        updated = _make_job_info(name="Updated Job")
        with patch("open_agent.api.endpoints.jobs.job_manager") as mock_jm:
            with patch("open_agent.api.endpoints.jobs.job_scheduler") as mock_sched:
                with patch("open_agent.api.endpoints.jobs.validate_job_prompt", return_value=None):
                    mock_jm.update_job = AsyncMock(return_value=updated)
                    mock_sched.refresh_job = MagicMock()
                    resp = await jobs_client.patch(
                        "/api/jobs/job-1",
                        json={"name": "Updated Job", "prompt": "Updated prompt"},
                    )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Job"

    async def test_update_job_not_found(self, jobs_client: AsyncClient):
        """Returns 404 for non-existent job."""
        with patch("open_agent.api.endpoints.jobs.job_manager") as mock_jm:
            with patch("open_agent.api.endpoints.jobs.job_scheduler"):
                with patch("open_agent.api.endpoints.jobs.validate_job_prompt", return_value=None):
                    mock_jm.update_job = AsyncMock(return_value=None)
                    resp = await jobs_client.patch(
                        "/api/jobs/nonexistent",
                        json={"name": "New Name"},
                    )
        assert resp.status_code == 404

    async def test_update_job_invalid_prompt(self, jobs_client: AsyncClient):
        """Returns 400 when updated prompt is invalid."""
        with patch(
            "open_agent.api.endpoints.jobs.validate_job_prompt", return_value="Prompt too short"
        ):
            resp = await jobs_client.patch(
                "/api/jobs/job-1",
                json={"prompt": "x"},
            )
        assert resp.status_code == 400
        assert "Prompt too short" in resp.json()["detail"]

    async def test_update_job_without_prompt(self, jobs_client: AsyncClient):
        """Updates job without changing prompt skips validation."""
        updated = _make_job_info(name="Name Only")
        with patch("open_agent.api.endpoints.jobs.job_manager") as mock_jm:
            with patch("open_agent.api.endpoints.jobs.job_scheduler") as mock_sched:
                mock_jm.update_job = AsyncMock(return_value=updated)
                mock_sched.refresh_job = MagicMock()
                resp = await jobs_client.patch(
                    "/api/jobs/job-1",
                    json={"name": "Name Only"},
                )
        assert resp.status_code == 200


class TestStopJob:
    """POST /api/jobs/{job_id}/stop"""

    async def test_stop_job(self, jobs_client: AsyncClient):
        """Stops a running job."""
        with patch("open_agent.api.endpoints.jobs.job_scheduler") as mock_sched:
            mock_sched.stop_job = AsyncMock()
            resp = await jobs_client.post("/api/jobs/job-1/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopping"


class TestDeleteJobExtended:
    """Extended delete job tests."""

    async def test_delete_running_job_stops_first(self, jobs_client: AsyncClient):
        """Deleting a running job stops it before deletion."""
        with patch("open_agent.api.endpoints.jobs.job_manager") as mock_jm:
            with patch("open_agent.api.endpoints.jobs.job_scheduler") as mock_sched:
                mock_sched.is_running.return_value = True
                mock_sched.stop_job = AsyncMock()
                mock_jm.delete_job = AsyncMock(return_value=True)
                resp = await jobs_client.delete("/api/jobs/job-1")
        assert resp.status_code == 200
        mock_sched.stop_job.assert_called_once_with("job-1")


class TestCreateJobExtended:
    """Extended create job tests."""

    async def test_create_job_with_schedule(self, jobs_client: AsyncClient):
        """Creates a scheduled job."""
        job = _make_job_info()
        with patch("open_agent.api.endpoints.jobs.job_manager") as mock_jm:
            with patch("open_agent.api.endpoints.jobs.job_scheduler") as mock_sched:
                with patch("open_agent.api.endpoints.jobs.validate_job_prompt", return_value=None):
                    mock_jm.create_job = AsyncMock(return_value=job)
                    mock_sched.refresh_job = MagicMock()
                    resp = await jobs_client.post(
                        "/api/jobs/",
                        json={
                            "name": "Scheduled Job",
                            "prompt": "Run daily task",
                            "schedule_type": "daily",
                            "schedule_config": {"hour": 9, "minute": 0},
                        },
                    )
        assert resp.status_code == 200

    async def test_create_job_exception(self, jobs_client: AsyncClient):
        """Returns 400 when job creation raises exception."""
        with patch("open_agent.api.endpoints.jobs.job_manager") as mock_jm:
            with patch("open_agent.api.endpoints.jobs.validate_job_prompt", return_value=None):
                mock_jm.create_job = AsyncMock(side_effect=ValueError("Invalid schedule"))
                resp = await jobs_client.post(
                    "/api/jobs/",
                    json={"name": "Bad Job", "prompt": "Do something"},
                )
        assert resp.status_code == 400
