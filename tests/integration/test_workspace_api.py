"""Workspace API integration tests — CRUD endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from open_agent.models.workspace import WorkspaceInfo


@pytest.fixture()
async def workspace_client(_patch_db_factory, monkeypatch):
    """httpx.AsyncClient wired to workspace router with mocked workspace_manager."""
    import httpx
    from httpx import ASGITransport

    from fastapi import FastAPI
    from core.auth.dependencies import get_current_user
    from open_agent.api.endpoints import workspace as workspace_router

    test_app = FastAPI()
    test_app.include_router(workspace_router.router, prefix="/api/workspace")

    async def _fake_current_user() -> dict:
        return {"id": "test-user-id", "email": "test@example.com", "username": "testuser", "role": "admin"}

    test_app.dependency_overrides[get_current_user] = _fake_current_user

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _make_ws_info(id="ws-1", name="Test WS", path="/tmp/test", description="", is_active=False):
    return WorkspaceInfo(
        id=id, name=name, path=path, description=description,
        created_at="2024-01-01T00:00:00Z", is_active=is_active,
    )


class TestListWorkspaces:
    """GET /api/workspace/"""

    async def test_list_empty(self, workspace_client: AsyncClient):
        """Returns empty list when no workspaces exist."""
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.get_all.return_value = []
            resp = await workspace_client.get("/api/workspace/")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_returns_workspaces(self, workspace_client: AsyncClient):
        """Returns list of workspaces."""
        ws = _make_ws_info()
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.get_all.return_value = [ws]
            resp = await workspace_client.get("/api/workspace/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Test WS"


class TestCreateWorkspace:
    """POST /api/workspace/"""

    async def test_create_workspace(self, workspace_client: AsyncClient):
        """Creates a workspace successfully."""
        ws = _make_ws_info()
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.create_workspace = AsyncMock(return_value=ws)
            resp = await workspace_client.post(
                "/api/workspace/",
                json={"name": "Test WS", "path": "/tmp/test"},
            )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test WS"


class TestGetWorkspace:
    """GET /api/workspace/{workspace_id}"""

    async def test_get_workspace(self, workspace_client: AsyncClient):
        """Returns workspace by ID."""
        ws = _make_ws_info()
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.get_workspace.return_value = ws
            resp = await workspace_client.get("/api/workspace/ws-1")
        assert resp.status_code == 200

    async def test_get_nonexistent_workspace(self, workspace_client: AsyncClient):
        """Returns 404 for non-existent workspace."""
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.get_workspace.return_value = None
            resp = await workspace_client.get("/api/workspace/nonexistent")
        assert resp.status_code == 404


class TestUpdateWorkspace:
    """PATCH /api/workspace/{workspace_id}"""

    async def test_update_workspace(self, workspace_client: AsyncClient):
        """Updates workspace name."""
        ws = _make_ws_info(name="Updated")
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.update_workspace = AsyncMock(return_value=ws)
            resp = await workspace_client.patch(
                "/api/workspace/ws-1", json={"name": "Updated"}
            )
        assert resp.status_code == 200

    async def test_update_nonexistent_workspace(self, workspace_client: AsyncClient):
        """Returns 404 for non-existent workspace."""
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.update_workspace = AsyncMock(return_value=None)
            resp = await workspace_client.patch(
                "/api/workspace/nonexistent", json={"name": "Updated"}
            )
        assert resp.status_code == 404


class TestDeleteWorkspace:
    """DELETE /api/workspace/{workspace_id}"""

    async def test_delete_workspace(self, workspace_client: AsyncClient):
        """Deletes workspace successfully."""
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.delete_workspace = AsyncMock(return_value=True)
            resp = await workspace_client.delete("/api/workspace/ws-1")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    async def test_delete_nonexistent_workspace(self, workspace_client: AsyncClient):
        """Returns 404 for non-existent workspace."""
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.delete_workspace = AsyncMock(return_value=False)
            resp = await workspace_client.delete("/api/workspace/nonexistent")
        assert resp.status_code == 404


class TestActivateWorkspace:
    """POST /api/workspace/{workspace_id}/activate"""

    async def test_activate_workspace(self, workspace_client: AsyncClient):
        """Activates workspace successfully."""
        ws = _make_ws_info(is_active=True)
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.set_active = AsyncMock(return_value=ws)
            resp = await workspace_client.post("/api/workspace/ws-1/activate")
        assert resp.status_code == 200

    async def test_activate_nonexistent_workspace(self, workspace_client: AsyncClient):
        """Returns 404 for non-existent workspace."""
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.set_active = AsyncMock(return_value=None)
            resp = await workspace_client.post("/api/workspace/nonexistent/activate")
        assert resp.status_code == 404


class TestDeactivateWorkspace:
    """POST /api/workspace/deactivate"""

    async def test_deactivate_workspace(self, workspace_client: AsyncClient):
        """Deactivates current workspace."""
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.deactivate = AsyncMock()
            resp = await workspace_client.post("/api/workspace/deactivate")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deactivated"
