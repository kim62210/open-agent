"""Pages API integration tests — CRUD, search, export."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from open_agent.models.page import PageInfo


@pytest.fixture()
async def pages_client(_patch_db_factory, monkeypatch):
    """httpx.AsyncClient wired to pages router with mocked page_manager."""
    import httpx
    from httpx import ASGITransport

    from fastapi import FastAPI
    from core.auth.dependencies import get_current_user
    from open_agent.api.endpoints import pages as pages_router

    test_app = FastAPI()
    test_app.include_router(pages_router.router, prefix="/api/pages")

    async def _fake_current_user() -> dict:
        return {"id": "test-user-id", "email": "test@example.com", "username": "testuser", "role": "admin"}

    test_app.dependency_overrides[get_current_user] = _fake_current_user

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _make_page_info(id="page-1", name="Test Page", content_type="html", published=False):
    return PageInfo(
        id=id, name=name, description="", content_type=content_type,
        filename="index.html", size_bytes=100, published=published,
    )


class TestListPages:
    """GET /api/pages/"""

    async def test_list_pages_empty(self, pages_client: AsyncClient):
        """Returns empty list when no pages exist."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.get_all.return_value = []
            resp = await pages_client.get("/api/pages/")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_pages_with_parent_id(self, pages_client: AsyncClient):
        """Filters by parent_id when provided."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.get_children.return_value = []
            resp = await pages_client.get("/api/pages/", params={"parent_id": "folder-1"})
        assert resp.status_code == 200
        mock_pm.get_children.assert_called_once_with("folder-1")


class TestGetPage:
    """GET /api/pages/{page_id}"""

    async def test_get_page_found(self, pages_client: AsyncClient):
        """Returns page by ID."""
        page = _make_page_info()
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.get_page.return_value = page
            resp = await pages_client.get("/api/pages/page-1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "page-1"

    async def test_get_page_not_found(self, pages_client: AsyncClient):
        """Returns 404 for non-existent page."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.get_page.return_value = None
            resp = await pages_client.get("/api/pages/nonexistent")
        assert resp.status_code == 404


class TestUpdatePage:
    """PATCH /api/pages/{page_id}"""

    async def test_update_page(self, pages_client: AsyncClient):
        """Updates page name."""
        page = _make_page_info(name="Updated")
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.update_page = AsyncMock(return_value=page)
            resp = await pages_client.patch(
                "/api/pages/page-1", json={"name": "Updated"}
            )
        assert resp.status_code == 200

    async def test_update_nonexistent_page(self, pages_client: AsyncClient):
        """Returns 404 for non-existent page."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.update_page = AsyncMock(return_value=None)
            resp = await pages_client.patch(
                "/api/pages/nonexistent", json={"name": "Nope"}
            )
        assert resp.status_code == 404


class TestDeletePage:
    """DELETE /api/pages/{page_id}"""

    async def test_delete_page(self, pages_client: AsyncClient):
        """Deletes page successfully."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.delete_page = AsyncMock(return_value=True)
            resp = await pages_client.delete("/api/pages/page-1")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    async def test_delete_nonexistent_page(self, pages_client: AsyncClient):
        """Returns 404 for non-existent page."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.delete_page = AsyncMock(return_value=False)
            resp = await pages_client.delete("/api/pages/nonexistent")
        assert resp.status_code == 404


class TestCreateFolder:
    """POST /api/pages/folders"""

    async def test_create_folder(self, pages_client: AsyncClient):
        """Creates a folder page."""
        folder = _make_page_info(content_type="folder")
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.create_folder = AsyncMock(return_value=folder)
            resp = await pages_client.post(
                "/api/pages/folders", json={"name": "My Folder"}
            )
        assert resp.status_code == 200


class TestCreateBookmark:
    """POST /api/pages/bookmark"""

    async def test_create_bookmark(self, pages_client: AsyncClient):
        """Creates a bookmark page."""
        bm = _make_page_info(content_type="url")
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.add_bookmark = AsyncMock(return_value=bm)
            resp = await pages_client.post(
                "/api/pages/bookmark",
                json={"name": "Google", "url": "https://google.com"},
            )
        assert resp.status_code == 200


class TestActivatePage:
    """POST /api/pages/{page_id}/activate"""

    async def test_activate_page(self, pages_client: AsyncClient):
        """Activates a page."""
        page = _make_page_info()
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.activate_page.return_value = page
            resp = await pages_client.post("/api/pages/page-1/activate")
        assert resp.status_code == 200

    async def test_activate_nonexistent_page(self, pages_client: AsyncClient):
        """Returns 404 for non-existent page."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.activate_page.return_value = None
            resp = await pages_client.post("/api/pages/nonexistent/activate")
        assert resp.status_code == 404


class TestDeactivatePage:
    """POST /api/pages/deactivate"""

    async def test_deactivate_page(self, pages_client: AsyncClient):
        """Deactivates current page."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.deactivate_page = MagicMock()
            resp = await pages_client.post("/api/pages/deactivate")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deactivated"


class TestGetActivePage:
    """GET /api/pages/active/current"""

    async def test_get_active_page_none(self, pages_client: AsyncClient):
        """Returns null when no page is active."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.get_active_page.return_value = None
            resp = await pages_client.get("/api/pages/active/current")
        assert resp.status_code == 200


class TestPublishPage:
    """POST /api/pages/{page_id}/publish"""

    async def test_publish_page(self, pages_client: AsyncClient):
        """Publishes a page."""
        page = _make_page_info(published=True)
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.publish_page = AsyncMock(return_value=page)
            resp = await pages_client.post("/api/pages/page-1/publish")
        assert resp.status_code == 200

    async def test_publish_nonexistent_page(self, pages_client: AsyncClient):
        """Returns 404 for non-existent page."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.publish_page = AsyncMock(return_value=None)
            resp = await pages_client.post("/api/pages/nonexistent/publish")
        assert resp.status_code == 404


class TestUnpublishPage:
    """POST /api/pages/{page_id}/unpublish"""

    async def test_unpublish_page(self, pages_client: AsyncClient):
        """Unpublishes a page."""
        page = _make_page_info()
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.publish_page = AsyncMock(return_value=page)
            resp = await pages_client.post("/api/pages/page-1/unpublish")
        assert resp.status_code == 200


class TestPageKVStorage:
    """KV storage endpoints."""

    async def test_kv_list_keys(self, pages_client: AsyncClient):
        """Lists KV keys for a page."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.kv_list.return_value = ["key1", "key2"]
            resp = await pages_client.get("/api/pages/page-1/kv")
        assert resp.status_code == 200

    async def test_kv_get_key(self, pages_client: AsyncClient):
        """Gets a KV value by key."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.get_page.return_value = _make_page_info()
            mock_pm.kv_get.return_value = "val1"
            resp = await pages_client.get("/api/pages/page-1/kv/key1")
        assert resp.status_code == 200
        assert resp.json()["value"] == "val1"

    async def test_kv_get_not_found(self, pages_client: AsyncClient):
        """Returns 404 for non-existent KV key."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.get_page.return_value = _make_page_info()
            mock_pm.kv_get.return_value = None
            resp = await pages_client.get("/api/pages/page-1/kv/missing")
        assert resp.status_code == 404

    async def test_kv_set_key(self, pages_client: AsyncClient):
        """Sets a KV value."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.get_page.return_value = _make_page_info()
            mock_pm.kv_set = MagicMock()
            resp = await pages_client.put(
                "/api/pages/page-1/kv/key1", json={"value": "new-val"}
            )
        assert resp.status_code == 200

    async def test_kv_delete_key(self, pages_client: AsyncClient):
        """Deletes a KV key."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.get_page.return_value = _make_page_info()
            mock_pm.kv_delete.return_value = True
            resp = await pages_client.delete("/api/pages/page-1/kv/key1")
        assert resp.status_code == 200
