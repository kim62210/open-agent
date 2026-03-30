from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.fixture()
async def runs_client(_patch_db_factory):
    import httpx
    from fastapi import FastAPI
    from httpx import ASGITransport
    from open_agent.api.endpoints import runs as runs_router

    from core.auth.dependencies import get_current_user

    test_app = FastAPI()
    test_app.include_router(runs_router.router, prefix="/api/runs")

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


def _make_run_detail(run_id: str = "run-1") -> dict:
    return {
        "id": run_id,
        "owner_user_id": "test-user-id",
        "status": "completed",
        "request_messages": [],
        "response_payload": {"choices": [{"message": {"content": "done"}}]},
        "created_at": "2026-03-30T00:00:00+00:00",
        "updated_at": "2026-03-30T00:00:00+00:00",
        "finished_at": "2026-03-30T00:00:01+00:00",
        "events": [
            {
                "seq": 0,
                "event_type": "request.received",
                "payload": {"message_count": 1},
                "created_at": "2026-03-30T00:00:00+00:00",
            }
        ],
    }


class TestListRuns:
    async def test_list_runs(self, runs_client: AsyncClient):
        with patch("open_agent.api.endpoints.runs.run_manager") as mock_rm:
            mock_rm.list_runs = AsyncMock(return_value=[_make_run_detail()])
            resp = await runs_client.get("/api/runs/")

        assert resp.status_code == 200
        assert resp.json()[0]["id"] == "run-1"


class TestGetRun:
    async def test_get_run(self, runs_client: AsyncClient):
        with patch("open_agent.api.endpoints.runs.run_manager") as mock_rm:
            mock_rm.get_run = AsyncMock(return_value=_make_run_detail())
            resp = await runs_client.get("/api/runs/run-1")

        assert resp.status_code == 200
        assert resp.json()["events"][0]["event_type"] == "request.received"

    async def test_get_run_not_found(self, runs_client: AsyncClient):
        with patch("open_agent.api.endpoints.runs.run_manager") as mock_rm:
            mock_rm.get_run = AsyncMock(return_value=None)
            resp = await runs_client.get("/api/runs/missing")

        assert resp.status_code == 404


class TestRunControls:
    async def test_get_run_status(self, runs_client: AsyncClient):
        with patch("open_agent.api.endpoints.runs.run_manager") as mock_rm:
            mock_rm.get_run_status = AsyncMock(
                return_value={"id": "run-1", "status": "running", "finished_at": None}
            )
            resp = await runs_client.get("/api/runs/run-1/status")

        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    async def test_abort_run(self, runs_client: AsyncClient):
        with patch("open_agent.api.endpoints.runs.run_manager") as mock_rm:
            mock_rm.abort_run = AsyncMock(
                return_value={
                    "id": "run-1",
                    "status": "cancelled",
                    "finished_at": "2026-03-30T00:00:01+00:00",
                }
            )
            resp = await runs_client.post("/api/runs/run-1/abort")

        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"
