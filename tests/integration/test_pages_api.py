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

    async def test_kv_delete_nonexistent_key(self, pages_client: AsyncClient):
        """Returns 404 when deleting non-existent KV key."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.get_page.return_value = _make_page_info()
            mock_pm.kv_delete.return_value = False
            resp = await pages_client.delete("/api/pages/page-1/kv/missing")
        assert resp.status_code == 404

    async def test_kv_list_page_not_found(self, pages_client: AsyncClient):
        """Returns 404 when page not found for KV list."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.kv_list.return_value = None
            resp = await pages_client.get("/api/pages/nonexistent/kv")
        assert resp.status_code == 404

    async def test_kv_get_page_not_found(self, pages_client: AsyncClient):
        """Returns 404 when page not found for KV get."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.get_page.return_value = None
            resp = await pages_client.get("/api/pages/nonexistent/kv/key1")
        assert resp.status_code == 404

    async def test_kv_set_page_not_found(self, pages_client: AsyncClient):
        """Returns 404 when page not found for KV set."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.get_page.return_value = None
            resp = await pages_client.put(
                "/api/pages/nonexistent/kv/key1", json={"value": "val"}
            )
        assert resp.status_code == 404

    async def test_kv_delete_page_not_found(self, pages_client: AsyncClient):
        """Returns 404 when page not found for KV delete."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.get_page.return_value = None
            resp = await pages_client.delete("/api/pages/nonexistent/kv/key1")
        assert resp.status_code == 404


class TestPageFileOperations:
    """Page file operations (inline editor) endpoints."""

    async def test_list_page_files(self, pages_client: AsyncClient):
        """Lists files for a page."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.list_page_files.return_value = ["index.html", "style.css"]
            resp = await pages_client.get("/api/pages/page-1/files")
        assert resp.status_code == 200
        assert resp.json()["files"] == ["index.html", "style.css"]

    async def test_list_page_files_not_found(self, pages_client: AsyncClient):
        """Returns 404 when page not found for file listing."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.list_page_files.return_value = None
            resp = await pages_client.get("/api/pages/nonexistent/files")
        assert resp.status_code == 404

    async def test_read_page_file(self, pages_client: AsyncClient):
        """Reads a page file content."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.read_page_file.return_value = "<html></html>"
            resp = await pages_client.get("/api/pages/page-1/files/index.html")
        assert resp.status_code == 200
        assert resp.json()["content"] == "<html></html>"
        assert resp.json()["name"] == "index.html"

    async def test_read_page_file_not_found(self, pages_client: AsyncClient):
        """Returns 404 when page file not found."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.read_page_file.return_value = None
            resp = await pages_client.get("/api/pages/page-1/files/missing.html")
        assert resp.status_code == 404

    async def test_write_page_file(self, pages_client: AsyncClient):
        """Writes a page file content."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.write_page_file = AsyncMock(return_value="index.html")
            resp = await pages_client.put(
                "/api/pages/page-1/files/index.html",
                json={"content": "<html>updated</html>"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_write_page_file_no_content(self, pages_client: AsyncClient):
        """Returns 400 when content is missing."""
        resp = await pages_client.put(
            "/api/pages/page-1/files/index.html",
            json={},
        )
        assert resp.status_code == 400

    async def test_write_page_file_failure(self, pages_client: AsyncClient):
        """Returns 400 when write fails."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.write_page_file = AsyncMock(return_value=None)
            resp = await pages_client.put(
                "/api/pages/page-1/files/index.html",
                json={"content": "test"},
            )
        assert resp.status_code == 400


class TestUnpublishPageExtended:
    """Extended unpublish page tests."""

    async def test_unpublish_nonexistent_page(self, pages_client: AsyncClient):
        """Returns 404 for non-existent page unpublish."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.publish_page = AsyncMock(return_value=None)
            resp = await pages_client.post("/api/pages/nonexistent/unpublish")
        assert resp.status_code == 404


class TestListPublishedPages:
    """GET /api/pages/published/list"""

    async def test_list_published_pages(self, pages_client: AsyncClient):
        """Returns published pages."""
        page = _make_page_info(published=True)
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.get_published_pages.return_value = [page]
            resp = await pages_client.get("/api/pages/published/list")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_list_published_pages_empty(self, pages_client: AsyncClient):
        """Returns empty list when no published pages."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.get_published_pages.return_value = []
            resp = await pages_client.get("/api/pages/published/list")
        assert resp.status_code == 200
        assert resp.json() == []


class TestBreadcrumb:
    """GET /api/pages/breadcrumb/{page_id}"""

    async def test_get_breadcrumb(self, pages_client: AsyncClient):
        """Returns breadcrumb path for a page."""
        page = _make_page_info()
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.get_page.return_value = page
            mock_pm.get_breadcrumb.return_value = [page]
            resp = await pages_client.get("/api/pages/breadcrumb/page-1")
        assert resp.status_code == 200

    async def test_get_breadcrumb_not_found(self, pages_client: AsyncClient):
        """Returns 404 for non-existent page breadcrumb."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.get_page.return_value = None
            resp = await pages_client.get("/api/pages/breadcrumb/nonexistent")
        assert resp.status_code == 404


class TestCheckFrameable:
    """POST /api/pages/check-frameable/{page_id}"""

    async def test_check_frameable(self, pages_client: AsyncClient):
        """Returns frameable status."""
        page = _make_page_info()
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.get_page.return_value = page
            mock_pm.check_and_update_frameable = AsyncMock(return_value=True)
            resp = await pages_client.post("/api/pages/check-frameable/page-1")
        assert resp.status_code == 200
        assert resp.json()["frameable"] is True

    async def test_check_frameable_not_found(self, pages_client: AsyncClient):
        """Returns 404 for non-existent page."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.get_page.return_value = None
            resp = await pages_client.post("/api/pages/check-frameable/nonexistent")
        assert resp.status_code == 404


class TestListPagesWithParent:
    """Extended list pages tests."""

    async def test_list_pages_null_parent_id(self, pages_client: AsyncClient):
        """Treats parent_id='null' as None."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.get_children.return_value = []
            resp = await pages_client.get("/api/pages/", params={"parent_id": "null"})
        assert resp.status_code == 200
        mock_pm.get_children.assert_called_once_with(None)

    async def test_list_pages_no_parent(self, pages_client: AsyncClient):
        """Returns all pages when no parent_id specified."""
        page = _make_page_info()
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.get_all.return_value = [page]
            resp = await pages_client.get("/api/pages/")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestPageVersion:
    """GET /api/pages/{page_id}/__version__"""

    async def test_get_page_version(self, pages_client: AsyncClient):
        """Returns page version for live-reload."""
        with patch("open_agent.api.endpoints.pages.page_manager") as mock_pm:
            mock_pm.get_version.return_value = 5
            resp = await pages_client.get("/api/pages/page-1/__version__")
        assert resp.status_code == 200
        assert resp.json()["v"] == 5
