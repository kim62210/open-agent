"""PageTools unit tests — tool call routing, input validation, error formatting."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from open_agent.core.page_tools import (
    PAGE_TOOL_NAMES,
    _ALLOWED_EXTENSIONS,
    get_page_management_tools,
    get_page_system_prompt,
    get_page_tools,
    handle_page_tool_call,
    _handle_page_grep,
)
from open_agent.models.page import PageInfo


@pytest.fixture()
def mock_pm():
    """Patch the page_manager singleton used by page_tools."""
    with patch("open_agent.core.page_tools.page_manager") as pm:
        yield pm


@pytest.fixture()
def active_page():
    """A PageInfo representing an active bundle page."""
    return PageInfo(
        id="pg01",
        name="Active Page",
        description="test",
        content_type="bundle",
        entry_file="index.html",
    )


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


class TestToolDefinitions:
    """Verify tool list structure."""

    def test_management_tools_returned(self):
        tools = get_page_management_tools()
        names = {t["function"]["name"] for t in tools}
        assert "page_create_page" in names
        assert "page_create_folder" in names
        assert "page_move" in names

    def test_get_page_tools_no_active(self, mock_pm):
        mock_pm.get_active_page.return_value = None
        tools = get_page_tools()
        names = {t["function"]["name"] for t in tools}
        assert "page_create_page" in names
        assert "page_list_files" not in names

    def test_get_page_tools_with_active(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        tools = get_page_tools()
        names = {t["function"]["name"] for t in tools}
        assert "page_list_files" in names
        assert "page_read_file" in names
        assert "page_write_file" in names
        assert "page_edit_file" in names
        assert "page_grep" in names

    def test_page_tool_names_constant(self):
        assert "page_create_page" in PAGE_TOOL_NAMES
        assert "page_list_files" in PAGE_TOOL_NAMES
        assert "page_grep" in PAGE_TOOL_NAMES


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    """get_page_system_prompt builds context for LLM."""

    def test_no_active_page(self, mock_pm):
        mock_pm.get_active_page.return_value = None
        assert get_page_system_prompt() is None

    def test_with_active_page(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.list_page_files.return_value = ["index.html", "style.css"]

        prompt = get_page_system_prompt()
        assert "Active Page" in prompt
        assert "pg01" in prompt
        assert "index.html" in prompt
        assert "style.css" in prompt

    def test_with_no_files(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.list_page_files.return_value = []

        prompt = get_page_system_prompt()
        assert "pg01" in prompt


# ---------------------------------------------------------------------------
# handle_page_tool_call — Management tools
# ---------------------------------------------------------------------------


class TestCreatePage:
    """page_create_page tool call."""

    async def test_create_page_success(self, mock_pm, active_page):
        mock_pm.add_bundle = AsyncMock(return_value=active_page)
        mock_pm.activate_page.return_value = active_page

        result = await handle_page_tool_call("page_create_page", {
            "name": "New Page",
            "content": "<h1>Hello</h1>",
        })

        assert "New Page" in result
        mock_pm.add_bundle.assert_awaited_once()
        mock_pm.activate_page.assert_called_once_with(active_page.id)

    async def test_create_page_with_parent(self, mock_pm, active_page):
        mock_pm.add_bundle = AsyncMock(return_value=active_page)
        mock_pm.activate_page.return_value = active_page

        result = await handle_page_tool_call("page_create_page", {
            "name": "Child",
            "content": "<h1>Child</h1>",
            "parent_id": "folder1",
        })

        assert "Child" in result

    async def test_create_page_error(self, mock_pm):
        mock_pm.add_bundle = AsyncMock(side_effect=ValueError("bad input"))

        result = await handle_page_tool_call("page_create_page", {
            "name": "Fail",
            "content": "<h1>x</h1>",
        })

        assert "Error" in result


class TestCreateFolder:
    """page_create_folder tool call."""

    async def test_create_folder_success(self, mock_pm):
        folder = PageInfo(
            id="f01", name="My Folder", content_type="folder",
        )
        mock_pm.create_folder = AsyncMock(return_value=folder)

        result = await handle_page_tool_call("page_create_folder", {
            "name": "My Folder",
        })

        assert "My Folder" in result
        assert "f01" in result

    async def test_create_folder_error(self, mock_pm):
        mock_pm.create_folder = AsyncMock(side_effect=RuntimeError("db fail"))

        result = await handle_page_tool_call("page_create_folder", {
            "name": "Fail",
        })

        assert "Error" in result


class TestMovePageTool:
    """page_move tool call."""

    async def test_move_to_folder(self, mock_pm, active_page):
        target_folder = PageInfo(
            id="fold", name="Target", content_type="folder",
        )
        mock_pm.get_page.side_effect = lambda pid: {
            "pg01": active_page,
            "fold": target_folder,
        }.get(pid)
        mock_pm.update_page = AsyncMock(return_value=active_page)

        result = await handle_page_tool_call("page_move", {
            "page_id": "pg01",
            "target_folder_id": "fold",
        })

        assert "Target" in result

    async def test_move_nonexistent_page(self, mock_pm):
        mock_pm.get_page.return_value = None

        result = await handle_page_tool_call("page_move", {
            "page_id": "nope",
        })

        assert "Error" in result

    async def test_move_to_non_folder_target(self, mock_pm, active_page):
        non_folder = PageInfo(
            id="pg02", name="Not A Folder", content_type="html",
        )
        mock_pm.get_page.side_effect = lambda pid: {
            "pg01": active_page,
            "pg02": non_folder,
        }.get(pid)

        result = await handle_page_tool_call("page_move", {
            "page_id": "pg01",
            "target_folder_id": "pg02",
        })

        assert "Error" in result

    async def test_move_folder_into_itself(self, mock_pm):
        folder = PageInfo(
            id="f1", name="Folder", content_type="folder", parent_id=None,
        )
        child = PageInfo(
            id="f2", name="Child Folder", content_type="folder", parent_id="f1",
        )
        mock_pm.get_page.side_effect = lambda pid: {
            "f1": folder,
            "f2": child,
        }.get(pid)

        result = await handle_page_tool_call("page_move", {
            "page_id": "f1",
            "target_folder_id": "f2",
        })

        assert "Error" in result


# ---------------------------------------------------------------------------
# handle_page_tool_call — File tools (require active page)
# ---------------------------------------------------------------------------


class TestFileToolsNoActive:
    """File tools error when no page is active."""

    async def test_list_files_no_active(self, mock_pm):
        mock_pm.get_active_page.return_value = None

        result = await handle_page_tool_call("page_list_files", {})
        assert "Error" in result

    async def test_read_file_no_active(self, mock_pm):
        mock_pm.get_active_page.return_value = None

        result = await handle_page_tool_call("page_read_file", {"file_path": "x"})
        assert "Error" in result


class TestListFiles:
    """page_list_files tool call."""

    async def test_list_files(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.list_page_files.return_value = ["index.html", "style.css"]

        result = await handle_page_tool_call("page_list_files", {})
        assert "index.html" in result
        assert "style.css" in result

    async def test_list_files_empty(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.list_page_files.return_value = []

        result = await handle_page_tool_call("page_list_files", {})
        assert result != ""

    async def test_list_files_none(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.list_page_files.return_value = None

        result = await handle_page_tool_call("page_list_files", {})
        assert "Error" in result


class TestReadFile:
    """page_read_file tool call."""

    async def test_read_existing(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.read_page_file.return_value = "<h1>Hello</h1>"

        result = await handle_page_tool_call("page_read_file", {"file_path": "index.html"})
        assert "<h1>Hello</h1>" in result

    async def test_read_missing(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.read_page_file.return_value = None

        result = await handle_page_tool_call("page_read_file", {"file_path": "missing.html"})
        assert "Error" in result


class TestWriteFile:
    """page_write_file tool call."""

    async def test_write_valid_extension(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.get_page.return_value = active_page
        mock_pm.write_page_file = AsyncMock(return_value="/some/path/style.css")

        result = await handle_page_tool_call("page_write_file", {
            "file_path": "style.css",
            "content": "body { color: red; }",
        })

        assert "style.css" in result

    async def test_write_blocked_extension(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page

        result = await handle_page_tool_call("page_write_file", {
            "file_path": "script.exe",
            "content": "bad",
        })

        assert "Error" in result

    async def test_write_path_traversal(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page

        result = await handle_page_tool_call("page_write_file", {
            "file_path": "../../../etc/passwd.html",
            "content": "bad",
        })

        assert "Error" in result

    async def test_write_converts_html_to_bundle(self, mock_pm):
        html_page = PageInfo(
            id="pg01", name="HTML Page", content_type="html", filename="pg01.html",
        )
        mock_pm.get_active_page.return_value = html_page
        mock_pm.get_page.return_value = html_page
        mock_pm.list_page_files.return_value = ["pg01.html"]
        mock_pm.convert_to_bundle = AsyncMock()
        mock_pm.write_page_file = AsyncMock(return_value="/path/to/new.css")

        result = await handle_page_tool_call("page_write_file", {
            "file_path": "new.css",
            "content": "body {}",
        })

        mock_pm.convert_to_bundle.assert_awaited_once()


# ---------------------------------------------------------------------------
# page_grep tool
# ---------------------------------------------------------------------------


class TestPageGrep:
    """page_grep tool call."""

    async def test_grep_matches(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.list_page_files.return_value = ["index.html"]
        mock_pm.read_page_file.return_value = "<h1>Hello World</h1>\n<p>test</p>"

        result = await handle_page_tool_call("page_grep", {"pattern": "Hello"})
        assert "Hello" in result
        assert "Found" in result

    async def test_grep_no_matches(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.list_page_files.return_value = ["index.html"]
        mock_pm.read_page_file.return_value = "<p>nothing here</p>"

        result = await handle_page_tool_call("page_grep", {"pattern": "ZZZZZ"})
        assert "No matches" in result

    async def test_grep_invalid_regex(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page

        result = await handle_page_tool_call("page_grep", {"pattern": "[invalid"})
        assert "Error" in result

    async def test_grep_with_glob_filter(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.list_page_files.return_value = ["index.html", "style.css"]
        mock_pm.read_page_file.side_effect = lambda pid, fp: {
            "index.html": "<h1>body</h1>",
            "style.css": "body { color: red; }",
        }.get(fp)

        result = await handle_page_tool_call("page_grep", {
            "pattern": "body",
            "glob_filter": "*.css",
        })
        assert "style.css" in result

    async def test_grep_no_files(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.list_page_files.return_value = []

        result = await handle_page_tool_call("page_grep", {"pattern": "test"})
        assert result != ""

    async def test_grep_case_insensitive(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.list_page_files.return_value = ["index.html"]
        mock_pm.read_page_file.return_value = "<h1>Hello World</h1>"

        result = await handle_page_tool_call("page_grep", {
            "pattern": "hello",
            "case_insensitive": True,
        })
        assert "Found" in result


# ---------------------------------------------------------------------------
# Unknown tool
# ---------------------------------------------------------------------------


class TestEditFile:
    """page_edit_file tool call."""

    async def test_edit_file_exact_match(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.read_page_file.return_value = "<h1>Hello</h1>\n<p>World</p>"
        mock_pm.write_page_file = AsyncMock(return_value="/path/to/file")

        with patch("open_agent.core.fuzzy.fuzzy_find") as mock_find:
            mock_find.return_value = ("exact", 0, 14)
            result = await handle_page_tool_call("page_edit_file", {
                "file_path": "index.html",
                "old_string": "<h1>Hello</h1>",
                "new_string": "<h1>Goodbye</h1>",
            })

        assert "1" in result
        mock_pm.write_page_file.assert_awaited_once()

    async def test_edit_file_empty_old_string(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page

        result = await handle_page_tool_call("page_edit_file", {
            "file_path": "index.html",
            "old_string": "",
            "new_string": "new",
        })

        assert "Error" in result

    async def test_edit_file_not_found(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.read_page_file.return_value = None

        result = await handle_page_tool_call("page_edit_file", {
            "file_path": "missing.html",
            "old_string": "x",
            "new_string": "y",
        })

        assert "Error" in result

    async def test_edit_file_no_match(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.read_page_file.return_value = "<h1>Hello</h1>"

        with (
            patch("open_agent.core.fuzzy.fuzzy_find") as mock_find,
            patch("open_agent.core.fuzzy.find_closest_match") as mock_closest,
        ):
            mock_find.return_value = (None, -1, 0)
            mock_closest.return_value = (1, 0.6, "<h1>Hello</h1>")

            result = await handle_page_tool_call("page_edit_file", {
                "file_path": "index.html",
                "old_string": "<h1>Helo</h1>",
                "new_string": "<h1>Fixed</h1>",
            })

        assert "Error" in result

    async def test_edit_file_multiple_matches_no_replace_all(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.read_page_file.return_value = "aaa\naaa\naaa"

        with patch("open_agent.core.fuzzy.fuzzy_find") as mock_find:
            mock_find.return_value = ("exact", 0, 3)

            result = await handle_page_tool_call("page_edit_file", {
                "file_path": "index.html",
                "old_string": "aaa",
                "new_string": "bbb",
            })

        assert "Error" in result
        assert "3" in result

    async def test_edit_file_replace_all(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.read_page_file.return_value = "foo\nbar\nfoo"
        mock_pm.write_page_file = AsyncMock(return_value="/path")

        with patch("open_agent.core.fuzzy.fuzzy_find") as mock_find:
            mock_find.return_value = ("exact", 0, 3)

            result = await handle_page_tool_call("page_edit_file", {
                "file_path": "index.html",
                "old_string": "foo",
                "new_string": "baz",
                "replace_all": True,
            })

        assert "2" in result

    async def test_edit_file_fuzzy_match(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.read_page_file.return_value = "<h1>Hello</h1>"
        mock_pm.write_page_file = AsyncMock(return_value="/path")

        with (
            patch("open_agent.core.fuzzy.fuzzy_find") as mock_find,
            patch("open_agent.core.fuzzy.fuzzy_replace") as mock_replace,
        ):
            mock_find.return_value = ("whitespace", 0, 14)
            mock_replace.return_value = "<h1>New</h1>"

            result = await handle_page_tool_call("page_edit_file", {
                "file_path": "index.html",
                "old_string": "<h1>Hello</h1>",
                "new_string": "<h1>New</h1>",
            })

        assert "whitespace" in result

    async def test_edit_file_write_failure(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.read_page_file.return_value = "<h1>Hello</h1>"
        mock_pm.write_page_file = AsyncMock(return_value=None)

        with patch("open_agent.core.fuzzy.fuzzy_find") as mock_find:
            mock_find.return_value = ("exact", 0, 14)

            result = await handle_page_tool_call("page_edit_file", {
                "file_path": "index.html",
                "old_string": "<h1>Hello</h1>",
                "new_string": "<h1>New</h1>",
            })

        assert "Error" in result


class TestMoveToRoot:
    """page_move to root (no target_folder_id)."""

    async def test_move_to_root(self, mock_pm, active_page):
        mock_pm.get_page.return_value = active_page
        mock_pm.update_page = AsyncMock(return_value=active_page)

        result = await handle_page_tool_call("page_move", {
            "page_id": "pg01",
        })

        assert result != ""

    async def test_move_update_failure(self, mock_pm, active_page):
        mock_pm.get_page.return_value = active_page
        mock_pm.update_page = AsyncMock(return_value=None)

        result = await handle_page_tool_call("page_move", {
            "page_id": "pg01",
        })

        assert "Error" in result


class TestGrepLimit:
    """page_grep with match limit."""

    async def test_grep_limit(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.list_page_files.return_value = ["big.html"]
        # File with many matching lines
        lines = ["hello line\n"] * 100
        mock_pm.read_page_file.return_value = "".join(lines)

        result = await handle_page_tool_call("page_grep", {
            "pattern": "hello",
            "limit": 5,
        })

        assert "5" in result

    async def test_grep_glob_no_matching_files(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.list_page_files.return_value = ["index.html", "style.css"]

        result = await handle_page_tool_call("page_grep", {
            "pattern": "test",
            "glob_filter": "*.py",
        })

        assert "No files" in result


class TestWriteFileFailure:
    """page_write_file write failure."""

    async def test_write_returns_none(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page
        mock_pm.get_page.return_value = active_page
        mock_pm.write_page_file = AsyncMock(return_value=None)

        result = await handle_page_tool_call("page_write_file", {
            "file_path": "test.css",
            "content": "body {}",
        })

        assert "Error" in result


class TestUnknownTool:
    """Unknown tool name returns error."""

    async def test_unknown_tool(self, mock_pm, active_page):
        mock_pm.get_active_page.return_value = active_page

        result = await handle_page_tool_call("page_unknown_tool", {})
        assert "Error" in result
        assert "Unknown" in result
