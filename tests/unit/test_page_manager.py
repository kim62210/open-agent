"""PageManager unit tests — page CRUD, hierarchy, publish, file ops, KV storage."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from open_agent.core.exceptions import NotFoundError, NotInitializedError, StorageLimitError
from open_agent.core.page_manager import PageManager, _check_frameable
from open_agent.models.page import PageInfo


@pytest.fixture()
def pm(tmp_path: Path) -> PageManager:
    """Fresh PageManager with pages_dir pointing to tmp_path."""
    mgr = PageManager()
    mgr._pages_dir = tmp_path
    return mgr


@pytest.fixture()
def pm_with_html(pm: PageManager) -> PageManager:
    """PageManager with a pre-existing HTML page."""
    page = PageInfo(
        id="pg01",
        name="Test Page",
        description="desc",
        content_type="html",
        filename="pg01.html",
        size_bytes=12,
    )
    pm._pages["pg01"] = page
    dest = pm._pages_dir / "pg01.html"
    dest.write_text("<h1>Hello</h1>", encoding="utf-8")
    return pm


@pytest.fixture()
def pm_with_bundle(pm: PageManager, tmp_path: Path) -> PageManager:
    """PageManager with a pre-existing bundle page."""
    bundle_dir = tmp_path / "bnd1"
    bundle_dir.mkdir()
    (bundle_dir / "index.html").write_text("<h1>Bundle</h1>", encoding="utf-8")
    (bundle_dir / "style.css").write_text("body{}", encoding="utf-8")

    page = PageInfo(
        id="bnd1",
        name="Bundle Page",
        description="bundle desc",
        content_type="bundle",
        entry_file="index.html",
        size_bytes=100,
    )
    pm._pages["bnd1"] = page
    return pm


# ---------------------------------------------------------------------------
# _check_frameable
# ---------------------------------------------------------------------------


class TestCheckFrameable:
    """Test the helper that inspects frame headers."""

    def test_deny_xfo(self):
        """X-Frame-Options: DENY blocks framing."""
        mock_resp = MagicMock()
        mock_resp.headers = {"X-Frame-Options": "DENY", "Content-Security-Policy": ""}
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert _check_frameable("https://example.com") is False

    def test_sameorigin_xfo(self):
        """X-Frame-Options: SAMEORIGIN blocks framing."""
        mock_resp = MagicMock()
        mock_resp.headers = {"X-Frame-Options": "SAMEORIGIN", "Content-Security-Policy": ""}
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert _check_frameable("https://example.com") is False

    def test_no_restriction_allows_framing(self):
        """No X-Frame-Options and no CSP allows framing."""
        mock_resp = MagicMock()
        mock_resp.headers = {"X-Frame-Options": None, "Content-Security-Policy": None}
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert _check_frameable("https://example.com") is True

    def test_csp_frame_ancestors_wildcard(self):
        """CSP frame-ancestors * allows framing."""
        mock_resp = MagicMock()
        mock_resp.headers = {
            "X-Frame-Options": None,
            "Content-Security-Policy": "frame-ancestors *",
        }
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert _check_frameable("https://example.com") is True

    def test_csp_frame_ancestors_restricted(self):
        """CSP frame-ancestors 'self' blocks framing."""
        mock_resp = MagicMock()
        mock_resp.headers = {
            "X-Frame-Options": None,
            "Content-Security-Policy": "frame-ancestors 'self'",
        }
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert _check_frameable("https://example.com") is False

    def test_network_error_returns_true(self):
        """Network failure defaults to frameable=True."""
        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            assert _check_frameable("https://example.com") is True


# ---------------------------------------------------------------------------
# Version tracking
# ---------------------------------------------------------------------------


class TestVersionTracking:
    """Bump/get version for live-reload polling."""

    def test_get_version_unknown_page(self, pm: PageManager):
        assert pm.get_version("unknown") == 0

    def test_bump_and_get(self, pm: PageManager):
        pm.bump_version("p1")
        v1 = pm.get_version("p1")
        assert v1 > 0

    def test_bump_increments(self, pm: PageManager):
        pm.bump_version("p1")
        v1 = pm.get_version("p1")
        pm.bump_version("p1")
        v2 = pm.get_version("p1")
        assert v2 >= v1


# ---------------------------------------------------------------------------
# init_pages_dir
# ---------------------------------------------------------------------------


class TestInitPagesDir:
    """Pages directory initialization."""

    def test_init_with_absolute_path(self, pm: PageManager, tmp_path: Path):
        target = tmp_path / "pages"
        pm.init_pages_dir(str(target))
        assert pm._pages_dir == target
        assert target.is_dir()

    def test_init_creates_missing_dir(self, pm: PageManager, tmp_path: Path):
        target = tmp_path / "deep" / "nested" / "pages"
        pm.init_pages_dir(str(target))
        assert target.is_dir()


# ---------------------------------------------------------------------------
# Page CRUD
# ---------------------------------------------------------------------------


class TestGetAll:
    """get_all returns all cached pages."""

    def test_empty(self, pm: PageManager):
        assert pm.get_all() == []

    def test_returns_all_pages(self, pm_with_html: PageManager):
        pages = pm_with_html.get_all()
        assert len(pages) == 1
        assert pages[0].id == "pg01"


class TestGetPage:
    """get_page retrieves by ID or returns None."""

    def test_existing(self, pm_with_html: PageManager):
        page = pm_with_html.get_page("pg01")
        assert page is not None
        assert page.name == "Test Page"

    def test_nonexistent(self, pm: PageManager):
        assert pm.get_page("nope") is None


class TestAddPage:
    """add_page creates an HTML page on disk and cache."""

    async def test_add_page(self, pm: PageManager):
        with patch.object(pm, "_persist_page", new_callable=AsyncMock):
            page = await pm.add_page("My Page", "desc", b"<p>content</p>", "page.html")

        assert page.id in pm._pages
        assert page.name == "My Page"
        assert page.content_type == "html"
        assert page.size_bytes == len(b"<p>content</p>")
        assert (pm._pages_dir / page.filename).exists()

    async def test_add_page_not_initialized(self, tmp_path: Path):
        mgr = PageManager()
        with pytest.raises(NotInitializedError):
            await mgr.add_page("fail", "", b"data", "f.html")


class TestAddPageFromPath:
    """add_page_from_path reads from filesystem."""

    async def test_from_valid_path(self, pm: PageManager, tmp_path: Path):
        src = tmp_path / "source.html"
        src.write_text("<h1>From Path</h1>", encoding="utf-8")

        with patch.object(pm, "_persist_page", new_callable=AsyncMock):
            page = await pm.add_page_from_path("FromPath", "desc", str(src))

        assert page.content_type == "html"
        assert page.id in pm._pages

    async def test_from_missing_path(self, pm: PageManager):
        with pytest.raises(NotFoundError):
            with patch.object(pm, "_persist_page", new_callable=AsyncMock):
                await pm.add_page_from_path("Fail", "", "/nonexistent/file.html")


class TestAddBookmark:
    """add_bookmark creates a URL page."""

    async def test_add_bookmark(self, pm: PageManager):
        with (
            patch("open_agent.core.page_manager._check_frameable", return_value=True),
            patch.object(pm, "_persist_page", new_callable=AsyncMock),
        ):
            page = await pm.add_bookmark("Google", "https://google.com", "search")

        assert page.content_type == "url"
        assert page.url == "https://google.com"
        assert page.frameable is True


class TestAddBundle:
    """add_bundle creates a multi-file page."""

    async def test_add_bundle_with_entry(self, pm: PageManager):
        files = [
            ("index.html", b"<h1>Bundle</h1>"),
            ("style.css", b"body {}"),
        ]
        with patch.object(pm, "_persist_page", new_callable=AsyncMock):
            page = await pm.add_bundle("My Bundle", "desc", files)

        assert page.content_type == "bundle"
        assert page.entry_file == "index.html"
        assert page.size_bytes > 0
        bundle_dir = pm._pages_dir / page.id
        assert bundle_dir.is_dir()
        assert (bundle_dir / "index.html").exists()
        assert (bundle_dir / "style.css").exists()

    async def test_add_bundle_no_html_raises(self, pm: PageManager):
        files = [("data.csv", b"a,b,c")]
        with pytest.raises(ValueError, match="HTML"):
            with patch.object(pm, "_persist_page", new_callable=AsyncMock):
                await pm.add_bundle("Bad", "no html", files)

    async def test_add_bundle_path_traversal_defense(self, pm: PageManager):
        files = [
            ("index.html", b"<h1>OK</h1>"),
            ("../../etc/passwd", b"bad data"),
        ]
        with patch.object(pm, "_persist_page", new_callable=AsyncMock):
            page = await pm.add_bundle("Safe Bundle", "", files)

        # The traversal file should be silently skipped
        bundle_dir = pm._pages_dir / page.id
        assert (bundle_dir / "index.html").exists()
        assert not (pm._pages_dir / ".." / "etc" / "passwd").exists()

    async def test_add_bundle_not_initialized(self):
        mgr = PageManager()
        with pytest.raises(NotInitializedError):
            await mgr.add_bundle("Fail", "", [("index.html", b"<h1>x</h1>")])


class TestUpdatePage:
    """update_page modifies name/description/parent."""

    async def test_update_name(self, pm_with_html: PageManager):
        with patch.object(pm_with_html, "_persist_page", new_callable=AsyncMock):
            result = await pm_with_html.update_page("pg01", name="Updated")

        assert result is not None
        assert result.name == "Updated"

    async def test_update_description(self, pm_with_html: PageManager):
        with patch.object(pm_with_html, "_persist_page", new_callable=AsyncMock):
            result = await pm_with_html.update_page("pg01", description="new desc")

        assert result.description == "new desc"

    async def test_update_parent_id(self, pm_with_html: PageManager):
        with patch.object(pm_with_html, "_persist_page", new_callable=AsyncMock):
            result = await pm_with_html.update_page("pg01", parent_id="folder1")

        assert result.parent_id == "folder1"

    async def test_update_nonexistent(self, pm: PageManager):
        result = await pm.update_page("nope", name="x")
        assert result is None


class TestDeletePage:
    """delete_page removes from cache, disk, and DB."""

    async def test_delete_html_page(self, pm_with_html: PageManager):
        with patch.object(pm_with_html, "_delete_from_db", new_callable=AsyncMock):
            result = await pm_with_html.delete_page("pg01")

        assert result is True
        assert "pg01" not in pm_with_html._pages
        assert not (pm_with_html._pages_dir / "pg01.html").exists()

    async def test_delete_bundle_page(self, pm_with_bundle: PageManager):
        with patch.object(pm_with_bundle, "_delete_from_db", new_callable=AsyncMock):
            result = await pm_with_bundle.delete_page("bnd1")

        assert result is True
        assert "bnd1" not in pm_with_bundle._pages
        assert not (pm_with_bundle._pages_dir / "bnd1").exists()

    async def test_delete_nonexistent(self, pm: PageManager):
        with patch.object(pm, "_delete_from_db", new_callable=AsyncMock):
            result = await pm.delete_page("nope")

        assert result is False

    async def test_delete_active_page_clears_active(self, pm_with_html: PageManager):
        pm_with_html.activate_page("pg01")
        assert pm_with_html._active_page_id == "pg01"

        with patch.object(pm_with_html, "_delete_from_db", new_callable=AsyncMock):
            await pm_with_html.delete_page("pg01")

        assert pm_with_html._active_page_id is None


# ---------------------------------------------------------------------------
# Folder operations
# ---------------------------------------------------------------------------


class TestFolders:
    """Folder CRUD and hierarchy."""

    async def test_create_folder(self, pm: PageManager):
        with patch.object(pm, "_persist_page", new_callable=AsyncMock):
            folder = await pm.create_folder("Docs", "documentation")

        assert folder.content_type == "folder"
        assert folder.name == "Docs"
        assert folder.id in pm._pages

    def test_get_children_root(self, pm: PageManager):
        pm._pages["f1"] = PageInfo(
            id="f1", name="Folder", content_type="folder", parent_id=None,
        )
        pm._pages["p1"] = PageInfo(
            id="p1", name="Page1", content_type="html", parent_id=None,
        )
        pm._pages["p2"] = PageInfo(
            id="p2", name="Page2", content_type="html", parent_id="f1",
        )

        root_children = pm.get_children(None)
        assert len(root_children) == 2
        folder_children = pm.get_children("f1")
        assert len(folder_children) == 1
        assert folder_children[0].id == "p2"

    def test_get_breadcrumb(self, pm: PageManager):
        pm._pages["root"] = PageInfo(
            id="root", name="Root Folder", content_type="folder", parent_id=None,
        )
        pm._pages["sub"] = PageInfo(
            id="sub", name="Sub Folder", content_type="folder", parent_id="root",
        )
        pm._pages["page"] = PageInfo(
            id="page", name="Deep Page", content_type="html", parent_id="sub",
        )

        crumbs = pm.get_breadcrumb("page")
        assert len(crumbs) == 3
        assert crumbs[0].id == "root"
        assert crumbs[1].id == "sub"
        assert crumbs[2].id == "page"

    def test_breadcrumb_for_none(self, pm: PageManager):
        assert pm.get_breadcrumb(None) == []

    async def test_delete_folder_cascades(self, pm: PageManager):
        pm._pages["f1"] = PageInfo(
            id="f1", name="Folder", content_type="folder", parent_id=None,
        )
        pm._pages["p1"] = PageInfo(
            id="p1", name="Child", content_type="html", parent_id="f1",
            filename="p1.html",
        )
        (pm._pages_dir / "p1.html").write_text("<p>child</p>", encoding="utf-8")

        with patch.object(pm, "_delete_from_db", new_callable=AsyncMock):
            result = await pm.delete_page("f1")

        assert result is True
        assert "f1" not in pm._pages
        assert "p1" not in pm._pages


# ---------------------------------------------------------------------------
# Active page
# ---------------------------------------------------------------------------


class TestActivePage:
    """activate_page / deactivate_page / get_active_page."""

    def test_activate_html_page(self, pm_with_html: PageManager):
        result = pm_with_html.activate_page("pg01")
        assert result is not None
        assert pm_with_html.get_active_page() == result

    def test_activate_folder_returns_none(self, pm: PageManager):
        pm._pages["f1"] = PageInfo(
            id="f1", name="Folder", content_type="folder",
        )
        assert pm.activate_page("f1") is None

    def test_activate_nonexistent(self, pm: PageManager):
        assert pm.activate_page("nope") is None

    def test_deactivate(self, pm_with_html: PageManager):
        pm_with_html.activate_page("pg01")
        pm_with_html.deactivate_page()
        assert pm_with_html.get_active_page() is None

    def test_get_active_clears_stale(self, pm: PageManager):
        pm._active_page_id = "deleted-page"
        assert pm.get_active_page() is None
        assert pm._active_page_id is None


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


class TestPublish:
    """publish_page and verify_host_password."""

    async def test_publish_with_password(self, pm_with_html: PageManager):
        with patch.object(pm_with_html, "_persist_page", new_callable=AsyncMock):
            result = await pm_with_html.publish_page("pg01", True, password="secret123")

        assert result.published is True
        assert result.host_password_hash is not None

    async def test_unpublish_clears_password(self, pm_with_html: PageManager):
        with patch.object(pm_with_html, "_persist_page", new_callable=AsyncMock):
            await pm_with_html.publish_page("pg01", True, password="secret")
            result = await pm_with_html.publish_page("pg01", False)

        assert result.published is False
        assert result.host_password_hash is None

    async def test_publish_folder_returns_none(self, pm: PageManager):
        pm._pages["f1"] = PageInfo(
            id="f1", name="Folder", content_type="folder",
        )
        result = await pm.publish_page("f1", True)
        assert result is None

    def test_verify_password_correct(self, pm_with_html: PageManager):
        page = pm_with_html._pages["pg01"]
        page.host_password_hash = pm_with_html._hash_password("mypass")
        assert pm_with_html.verify_host_password("pg01", "mypass") is True

    def test_verify_password_wrong(self, pm_with_html: PageManager):
        page = pm_with_html._pages["pg01"]
        page.host_password_hash = pm_with_html._hash_password("mypass")
        assert pm_with_html.verify_host_password("pg01", "wrong") is False

    def test_verify_no_password_set(self, pm_with_html: PageManager):
        assert pm_with_html.verify_host_password("pg01", "anything") is True

    def test_verify_nonexistent_page(self, pm: PageManager):
        assert pm.verify_host_password("nope", "pw") is False

    def test_get_published_pages(self, pm: PageManager):
        pm._pages["p1"] = PageInfo(
            id="p1", name="P1", content_type="html", published=True,
        )
        pm._pages["p2"] = PageInfo(
            id="p2", name="P2", content_type="html", published=False,
        )
        pm._pages["f1"] = PageInfo(
            id="f1", name="F1", content_type="folder", published=True,
        )
        published = pm.get_published_pages()
        assert len(published) == 1
        assert published[0].id == "p1"


# ---------------------------------------------------------------------------
# Page file ops (resolve, list, read, write)
# ---------------------------------------------------------------------------


class TestPageFileOps:
    """File operations within pages."""

    def test_list_page_files_bundle(self, pm_with_bundle: PageManager):
        files = pm_with_bundle.list_page_files("bnd1")
        assert "index.html" in files
        assert "style.css" in files

    def test_list_page_files_html(self, pm_with_html: PageManager):
        files = pm_with_html.list_page_files("pg01")
        assert files == ["pg01.html"]

    def test_list_page_files_nonexistent(self, pm: PageManager):
        assert pm.list_page_files("nope") is None

    def test_read_page_file_bundle(self, pm_with_bundle: PageManager):
        content = pm_with_bundle.read_page_file("bnd1", "index.html")
        assert "<h1>Bundle</h1>" in content

    def test_read_page_file_html(self, pm_with_html: PageManager):
        content = pm_with_html.read_page_file("pg01", "pg01.html")
        assert "<h1>Hello</h1>" in content

    def test_read_page_file_missing(self, pm_with_bundle: PageManager):
        assert pm_with_bundle.read_page_file("bnd1", "missing.txt") is None

    async def test_write_page_file_bundle(self, pm_with_bundle: PageManager):
        with patch.object(pm_with_bundle, "_persist_page", new_callable=AsyncMock):
            result = await pm_with_bundle.write_page_file(
                "bnd1", "new.js", "console.log('hi')"
            )
        assert result is not None
        new_file = pm_with_bundle._pages_dir / "bnd1" / "new.js"
        assert new_file.read_text(encoding="utf-8") == "console.log('hi')"

    async def test_write_page_file_html(self, pm_with_html: PageManager):
        with patch.object(pm_with_html, "_persist_page", new_callable=AsyncMock):
            result = await pm_with_html.write_page_file(
                "pg01", "pg01.html", "<h1>Updated</h1>"
            )
        assert result is not None

    async def test_write_page_file_path_traversal(self, pm_with_bundle: PageManager):
        with patch.object(pm_with_bundle, "_persist_page", new_callable=AsyncMock):
            result = await pm_with_bundle.write_page_file(
                "bnd1", "../../evil.txt", "bad"
            )
        assert result is None


# ---------------------------------------------------------------------------
# Get page_dir / html_path / bundle_file_path helpers
# ---------------------------------------------------------------------------


class TestPathHelpers:
    """get_page_dir, get_html_path, get_bundle_file_path."""

    def test_get_page_dir_bundle(self, pm_with_bundle: PageManager):
        d = pm_with_bundle.get_page_dir("bnd1")
        assert d is not None
        assert d.name == "bnd1"

    def test_get_page_dir_html(self, pm_with_html: PageManager):
        assert pm_with_html.get_page_dir("pg01") is None

    def test_get_page_dir_nonexistent(self, pm: PageManager):
        assert pm.get_page_dir("nope") is None

    def test_get_html_path_bundle(self, pm_with_bundle: PageManager):
        p = pm_with_bundle.get_html_path("bnd1")
        assert p is not None
        assert p.name == "index.html"

    def test_get_html_path_html(self, pm_with_html: PageManager):
        p = pm_with_html.get_html_path("pg01")
        assert p is not None
        assert p.name == "pg01.html"

    def test_get_bundle_file_path(self, pm_with_bundle: PageManager):
        p = pm_with_bundle.get_bundle_file_path("bnd1", "index.html")
        assert p is not None
        assert p.name == "index.html"

    def test_get_bundle_file_path_traversal(self, pm_with_bundle: PageManager):
        assert pm_with_bundle.get_bundle_file_path("bnd1", "../../etc/passwd") is None

    def test_get_bundle_file_path_wrong_type(self, pm_with_html: PageManager):
        assert pm_with_html.get_bundle_file_path("pg01", "anything") is None


# ---------------------------------------------------------------------------
# Convert to bundle
# ---------------------------------------------------------------------------


class TestConvertToBundle:
    """convert_to_bundle converts single HTML to bundle."""

    async def test_convert_html_to_bundle(self, pm_with_html: PageManager):
        with patch.object(pm_with_html, "_persist_page", new_callable=AsyncMock):
            result = await pm_with_html.convert_to_bundle("pg01")

        assert result is not None
        assert result.content_type == "bundle"
        assert result.entry_file == "index.html"
        assert result.filename is None
        assert (pm_with_html._pages_dir / "pg01" / "index.html").exists()

    async def test_convert_nonexistent(self, pm: PageManager):
        result = await pm.convert_to_bundle("nope")
        assert result is None

    async def test_convert_already_bundle(self, pm_with_bundle: PageManager):
        result = await pm_with_bundle.convert_to_bundle("bnd1")
        assert result is None


# ---------------------------------------------------------------------------
# Static helpers
# ---------------------------------------------------------------------------


class TestStaticHelpers:
    """_compute_size, _detect_entry_file."""

    def test_compute_size_file(self, tmp_path: Path):
        f = tmp_path / "data.txt"
        f.write_text("hello world")
        assert PageManager._compute_size(f) == f.stat().st_size

    def test_compute_size_dir(self, tmp_path: Path):
        (tmp_path / "a.txt").write_text("aaa")
        (tmp_path / "b.txt").write_text("bbb")
        total = PageManager._compute_size(tmp_path)
        assert total > 0

    def test_compute_size_missing(self, tmp_path: Path):
        assert PageManager._compute_size(tmp_path / "nope") == 0

    def test_detect_entry_file_index_html(self, tmp_path: Path):
        (tmp_path / "index.html").write_text("<h1>hi</h1>")
        (tmp_path / "other.html").write_text("<p>other</p>")
        assert PageManager._detect_entry_file(tmp_path) == "index.html"

    def test_detect_entry_file_index_htm(self, tmp_path: Path):
        (tmp_path / "index.htm").write_text("<h1>hi</h1>")
        assert PageManager._detect_entry_file(tmp_path) == "index.htm"

    def test_detect_entry_file_first_html(self, tmp_path: Path):
        (tmp_path / "about.html").write_text("<p>about</p>")
        assert PageManager._detect_entry_file(tmp_path) == "about.html"

    def test_detect_entry_file_nested(self, tmp_path: Path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "page.html").write_text("<p>nested</p>")
        assert PageManager._detect_entry_file(tmp_path) == "sub/page.html"

    def test_detect_entry_file_none(self, tmp_path: Path):
        (tmp_path / "readme.txt").write_text("no html")
        assert PageManager._detect_entry_file(tmp_path) is None


# ---------------------------------------------------------------------------
# KV Storage
# ---------------------------------------------------------------------------


class TestKVStorage:
    """Page KV storage operations."""

    def test_kv_set_and_get(self, pm_with_html: PageManager):
        with patch.object(PageManager, "_get_kv_path") as mock_kv:
            kv_file = pm_with_html._pages_dir / "pg01_kv.json"
            mock_kv.return_value = kv_file

            assert pm_with_html.kv_set("pg01", "color", "blue") is True
            assert pm_with_html.kv_get("pg01", "color") == "blue"

    def test_kv_list(self, pm_with_html: PageManager):
        with patch.object(PageManager, "_get_kv_path") as mock_kv:
            kv_file = pm_with_html._pages_dir / "pg01_kv.json"
            mock_kv.return_value = kv_file

            pm_with_html.kv_set("pg01", "k1", "v1")
            pm_with_html.kv_set("pg01", "k2", "v2")
            keys = pm_with_html.kv_list("pg01")
            assert "k1" in keys
            assert "k2" in keys

    def test_kv_delete(self, pm_with_html: PageManager):
        with patch.object(PageManager, "_get_kv_path") as mock_kv:
            kv_file = pm_with_html._pages_dir / "pg01_kv.json"
            mock_kv.return_value = kv_file

            pm_with_html.kv_set("pg01", "key", "val")
            assert pm_with_html.kv_delete("pg01", "key") is True
            assert pm_with_html.kv_get("pg01", "key") is None

    def test_kv_delete_nonexistent_key(self, pm_with_html: PageManager):
        with patch.object(PageManager, "_get_kv_path") as mock_kv:
            kv_file = pm_with_html._pages_dir / "pg01_kv.json"
            mock_kv.return_value = kv_file

            assert pm_with_html.kv_delete("pg01", "missing") is False

    def test_kv_operations_unknown_page(self, pm: PageManager):
        assert pm.kv_list("unknown") is None
        assert pm.kv_get("unknown", "k") is None
        assert pm.kv_set("unknown", "k", "v") is False
        assert pm.kv_delete("unknown", "k") is False

    def test_kv_size_limit(self, pm_with_html: PageManager):
        with patch.object(PageManager, "_get_kv_path") as mock_kv:
            kv_file = pm_with_html._pages_dir / "pg01_kv.json"
            mock_kv.return_value = kv_file

            # Create a value that will exceed 1MB
            big_value = "x" * (1024 * 1024 + 1)
            with pytest.raises(StorageLimitError):
                pm_with_html.kv_set("pg01", "huge", big_value)
