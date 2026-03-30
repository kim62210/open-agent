"""Workspace API integration tests — CRUD endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from open_agent.models.workspace import WorkspaceInfo


@pytest.fixture()
async def workspace_client(_patch_db_factory, monkeypatch):
    """httpx.AsyncClient wired to workspace router with mocked workspace_manager."""
    import httpx
    from fastapi import FastAPI
    from httpx import ASGITransport
    from open_agent.api.endpoints import workspace as workspace_router

    from core.auth.dependencies import get_current_user

    test_app = FastAPI()
    test_app.include_router(workspace_router.router, prefix="/api/workspace")

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


def _make_ws_info(id="ws-1", name="Test WS", path="/tmp/test", description="", is_active=False):
    return WorkspaceInfo(
        id=id,
        name=name,
        path=path,
        description=description,
        created_at="2024-01-01T00:00:00Z",
        is_active=is_active,
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
        mock_wm.create_workspace.assert_awaited_once_with(
            "Test WS",
            "/tmp/test",
            "",
            owner_user_id="test-user-id",
        )


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
            resp = await workspace_client.patch("/api/workspace/ws-1", json={"name": "Updated"})
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


class TestFileTree:
    """GET /api/workspace/{workspace_id}/tree"""

    async def test_get_file_tree(self, workspace_client: AsyncClient):
        """Returns file tree for workspace."""
        from open_agent.models.workspace import FileTreeNode

        tree = [
            FileTreeNode(name="src", path="src", type="dir", children=[]),
            FileTreeNode(name="README.md", path="README.md", type="file", size=100),
        ]
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.get_file_tree.return_value = tree
            resp = await workspace_client.get("/api/workspace/ws-1/tree")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["name"] == "src"
        assert data[0]["type"] == "dir"

    async def test_get_file_tree_with_params(self, workspace_client: AsyncClient):
        """File tree respects path and max_depth parameters."""
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.get_file_tree.return_value = []
            resp = await workspace_client.get(
                "/api/workspace/ws-1/tree",
                params={"path": "src", "max_depth": 2},
            )
        assert resp.status_code == 200
        mock_wm.get_file_tree.assert_called_once_with("ws-1", "src", 2)


class TestReadFile:
    """GET /api/workspace/{workspace_id}/file"""

    async def test_read_file(self, workspace_client: AsyncClient):
        """Reads a file from workspace."""
        from open_agent.models.workspace import FileContent

        content = FileContent(path="main.py", content="print('hello')", total_lines=1)
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.read_file.return_value = content
            resp = await workspace_client.get(
                "/api/workspace/ws-1/file", params={"path": "main.py"}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] == "main.py"
        assert "print" in data["content"]

    async def test_read_file_with_offset_limit(self, workspace_client: AsyncClient):
        """Reads a file with offset and limit."""
        from open_agent.models.workspace import FileContent

        content = FileContent(path="main.py", content="line 5", total_lines=10, offset=4, limit=1)
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.read_file.return_value = content
            resp = await workspace_client.get(
                "/api/workspace/ws-1/file",
                params={"path": "main.py", "offset": 4, "limit": 1},
            )
        assert resp.status_code == 200
        mock_wm.read_file.assert_called_once_with("ws-1", "main.py", 4, 1)


class TestWriteFile:
    """POST /api/workspace/{workspace_id}/file"""

    async def test_write_file(self, workspace_client: AsyncClient):
        """Writes a file to workspace."""
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.write_file.return_value = "File written"
            resp = await workspace_client.post(
                "/api/workspace/ws-1/file",
                json={"path": "test.py", "content": "print('test')"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestEditFile:
    """POST /api/workspace/{workspace_id}/edit"""

    async def test_edit_file(self, workspace_client: AsyncClient):
        """Edits a file in workspace."""
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.edit_file.return_value = "Edit applied"
            resp = await workspace_client.post(
                "/api/workspace/ws-1/edit",
                json={"path": "test.py", "old_string": "old", "new_string": "new"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_edit_file_value_error(self, workspace_client: AsyncClient):
        """Returns 400 when edit fails with ValueError."""
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.edit_file.side_effect = ValueError("old_string not found")
            resp = await workspace_client.post(
                "/api/workspace/ws-1/edit",
                json={"path": "test.py", "old_string": "missing", "new_string": "new"},
            )
        assert resp.status_code == 400
        assert "old_string not found" in resp.json()["detail"]


class TestRenameFile:
    """POST /api/workspace/{workspace_id}/rename"""

    async def test_rename_file(self, workspace_client: AsyncClient):
        """Renames a file in workspace."""
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.rename_file.return_value = "Renamed"
            resp = await workspace_client.post(
                "/api/workspace/ws-1/rename",
                json={"old_path": "old.py", "new_path": "new.py"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestMkdir:
    """POST /api/workspace/{workspace_id}/mkdir"""

    async def test_mkdir(self, workspace_client: AsyncClient):
        """Creates a directory in workspace."""
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.mkdir.return_value = "Directory created"
            resp = await workspace_client.post(
                "/api/workspace/ws-1/mkdir",
                json={"path": "new_dir"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestDeleteFile:
    """POST /api/workspace/{workspace_id}/delete"""

    async def test_delete_file(self, workspace_client: AsyncClient):
        """Deletes a file from workspace."""
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.delete_path.return_value = "Deleted"
            resp = await workspace_client.post(
                "/api/workspace/ws-1/delete",
                json={"path": "old.py"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestBrowseDirectory:
    """POST /api/workspace/browse-directory"""

    async def test_browse_directory_selected(self, workspace_client: AsyncClient):
        """Returns path when user selects a directory."""
        with patch(
            "open_agent.api.endpoints.workspace._pick_directory", return_value="/home/user/project"
        ):
            resp = await workspace_client.post(
                "/api/workspace/browse-directory",
                json={"default_path": "/home/user"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] == "/home/user/project"
        assert data["cancelled"] is False

    async def test_browse_directory_cancelled(self, workspace_client: AsyncClient):
        """Returns cancelled=True when user cancels picker."""
        with patch("open_agent.api.endpoints.workspace._pick_directory", return_value=None):
            resp = await workspace_client.post("/api/workspace/browse-directory")
        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] is None
        assert data["cancelled"] is True


class TestUploadFiles:
    """POST /api/workspace/{workspace_id}/upload"""

    async def test_upload_files(self, workspace_client: AsyncClient):
        """Uploads files to workspace."""
        with patch("open_agent.api.endpoints.workspace.workspace_manager") as mock_wm:
            mock_wm.upload_file.return_value = "test.txt"
            resp = await workspace_client.post(
                "/api/workspace/ws-1/upload",
                files={"files": ("test.txt", b"file content", "text/plain")},
                data={"path": "."},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert len(data["uploaded"]) == 1
