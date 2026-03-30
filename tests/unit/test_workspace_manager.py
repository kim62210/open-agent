"""WorkspaceManager unit tests — async DB-backed + filesystem operations."""

from pathlib import Path

import pytest
from open_agent.core.exceptions import (
    AlreadyExistsError,
    InvalidPathError,
    NotFoundError,
    PermissionDeniedError,
)
from open_agent.core.workspace_manager import WorkspaceManager


@pytest.fixture()
def tmp_workspace(tmp_path: Path) -> Path:
    """Create a temporary directory with test files for workspace operations."""
    (tmp_path / "hello.txt").write_text("Hello, World!", encoding="utf-8")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "nested.py").write_text("# python file", encoding="utf-8")
    return tmp_path


@pytest.fixture()
async def workspace_manager(_patch_db_factory) -> WorkspaceManager:
    """Isolated WorkspaceManager backed by in-memory DB."""
    return WorkspaceManager()


class TestWorkspaceCreate:
    """Workspace creation tests."""

    async def test_create_workspace(self, workspace_manager: WorkspaceManager, tmp_workspace: Path):
        """Workspace can be created with a valid directory path."""
        ws = await workspace_manager.create_workspace(
            name="Test WS", path=str(tmp_workspace), description="A test workspace"
        )
        assert ws.id
        assert ws.name == "Test WS"
        assert ws.path == str(tmp_workspace)
        assert ws.description == "A test workspace"
        assert ws.is_active is False
        assert ws.created_at

    async def test_create_workspace_nonexistent_path(self, workspace_manager: WorkspaceManager):
        """Creating workspace with non-existent path raises NotFoundError."""
        with pytest.raises(NotFoundError, match="Directory not found"):
            await workspace_manager.create_workspace(
                name="Bad WS", path="/nonexistent/path/that/does/not/exist"
            )

    async def test_create_workspace_default_description(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """Workspace created without description defaults to empty string."""
        ws = await workspace_manager.create_workspace(name="WS", path=str(tmp_workspace))
        assert ws.description == ""

    async def test_create_workspace_persists_to_db(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """Created workspace persists in DB and survives reload."""
        ws = await workspace_manager.create_workspace(name="Persist WS", path=str(tmp_workspace))

        workspace_manager._workspaces.clear()
        await workspace_manager.load_from_db()
        reloaded = workspace_manager.get_workspace(ws.id)
        assert reloaded is not None
        assert reloaded.name == "Persist WS"


class TestWorkspaceGet:
    """Workspace retrieval tests."""

    async def test_get_all_empty(self, workspace_manager: WorkspaceManager):
        """Empty manager returns empty list."""
        assert workspace_manager.get_all() == []

    async def test_get_all_with_workspaces(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """get_all returns all created workspaces."""
        await workspace_manager.create_workspace("WS1", str(tmp_workspace))
        await workspace_manager.create_workspace("WS2", str(tmp_workspace))
        assert len(workspace_manager.get_all()) == 2

    async def test_get_workspace_by_id(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """Existing workspace can be retrieved by ID."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        result = workspace_manager.get_workspace(ws.id)
        assert result is not None
        assert result.name == "WS"

    async def test_get_nonexistent_workspace(self, workspace_manager: WorkspaceManager):
        """Non-existent workspace ID returns None."""
        assert workspace_manager.get_workspace("nonexistent") is None


class TestWorkspaceUpdate:
    """Workspace update tests."""

    async def test_update_name(self, workspace_manager: WorkspaceManager, tmp_workspace: Path):
        """Workspace name can be updated."""
        ws = await workspace_manager.create_workspace("Old Name", str(tmp_workspace))
        result = await workspace_manager.update_workspace(ws.id, name="New Name")
        assert result is not None
        assert result.name == "New Name"

    async def test_update_description(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """Workspace description can be updated."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        result = await workspace_manager.update_workspace(ws.id, description="Updated desc")
        assert result is not None
        assert result.description == "Updated desc"

    async def test_update_both_fields(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """Name and description can be updated together."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        result = await workspace_manager.update_workspace(ws.id, name="New", description="New desc")
        assert result.name == "New"
        assert result.description == "New desc"

    async def test_update_nonexistent_workspace(self, workspace_manager: WorkspaceManager):
        """Updating non-existent workspace returns None."""
        result = await workspace_manager.update_workspace("nonexistent", name="No")
        assert result is None

    async def test_update_none_values_no_change(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """Passing None values leaves fields unchanged."""
        ws = await workspace_manager.create_workspace(
            "WS", str(tmp_workspace), description="Original"
        )
        result = await workspace_manager.update_workspace(ws.id, name=None, description=None)
        assert result is not None
        assert result.name == "WS"
        assert result.description == "Original"


class TestWorkspaceDelete:
    """Workspace deletion tests."""

    async def test_delete_workspace(self, workspace_manager: WorkspaceManager, tmp_workspace: Path):
        """Workspace can be deleted."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        result = await workspace_manager.delete_workspace(ws.id)
        assert result is True
        assert workspace_manager.get_workspace(ws.id) is None

    async def test_delete_nonexistent_workspace(self, workspace_manager: WorkspaceManager):
        """Deleting non-existent workspace returns False."""
        result = await workspace_manager.delete_workspace("nonexistent")
        assert result is False

    async def test_delete_persists_to_db(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """Deleted workspace does not survive DB reload."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        await workspace_manager.delete_workspace(ws.id)

        workspace_manager._workspaces.clear()
        await workspace_manager.load_from_db()
        assert workspace_manager.get_workspace(ws.id) is None


class TestWorkspaceActivation:
    """Workspace activation/deactivation tests."""

    async def test_set_active(self, workspace_manager: WorkspaceManager, tmp_workspace: Path):
        """A workspace can be activated."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        result = await workspace_manager.set_active(ws.id)
        assert result is not None
        assert result.is_active is True

    async def test_set_active_deactivates_others(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """Activating one workspace deactivates all others."""
        ws1 = await workspace_manager.create_workspace("WS1", str(tmp_workspace))
        ws2 = await workspace_manager.create_workspace("WS2", str(tmp_workspace))

        await workspace_manager.set_active(ws1.id)
        await workspace_manager.set_active(ws2.id)

        assert workspace_manager.get_workspace(ws1.id).is_active is False
        assert workspace_manager.get_workspace(ws2.id).is_active is True

    async def test_set_active_nonexistent(self, workspace_manager: WorkspaceManager):
        """Activating non-existent workspace returns None."""
        result = await workspace_manager.set_active("nonexistent")
        assert result is None

    async def test_get_active(self, workspace_manager: WorkspaceManager, tmp_workspace: Path):
        """get_active returns the active workspace."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        assert workspace_manager.get_active() is None

        await workspace_manager.set_active(ws.id)
        active = workspace_manager.get_active()
        assert active is not None
        assert active.id == ws.id

    async def test_deactivate_all(self, workspace_manager: WorkspaceManager, tmp_workspace: Path):
        """deactivate sets all workspaces to inactive."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        await workspace_manager.set_active(ws.id)
        assert workspace_manager.get_active() is not None

        await workspace_manager.deactivate()
        assert workspace_manager.get_active() is None

    async def test_set_active_is_user_scoped(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        ws1 = await workspace_manager.create_workspace(
            "WS1", str(tmp_workspace), owner_user_id="user-1"
        )
        ws2 = await workspace_manager.create_workspace(
            "WS2", str(tmp_workspace), owner_user_id="user-2"
        )

        await workspace_manager.set_active(ws1.id, owner_user_id="user-1")
        await workspace_manager.set_active(ws2.id, owner_user_id="user-2")

        assert workspace_manager.get_active(owner_user_id="user-1").id == ws1.id
        assert workspace_manager.get_active(owner_user_id="user-2").id == ws2.id

    async def test_file_read_denies_other_owner(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        ws = await workspace_manager.create_workspace(
            "WS", str(tmp_workspace), owner_user_id="user-1"
        )

        with pytest.raises(PermissionDeniedError):
            workspace_manager.read_file(ws.id, "hello.txt", owner_user_id="user-2")


class TestWorkspaceFileOperations:
    """File operations within workspace context."""

    async def test_read_file(self, workspace_manager: WorkspaceManager, tmp_workspace: Path):
        """Read a file from a workspace."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        content = workspace_manager.read_file(ws.id, "hello.txt")
        assert content.content == "Hello, World!"
        assert content.total_lines >= 1

    async def test_read_file_nonexistent(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """Reading non-existent file raises NotFoundError."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        with pytest.raises(NotFoundError, match="File not found"):
            workspace_manager.read_file(ws.id, "nonexistent.txt")

    async def test_read_file_with_offset_and_limit(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """Read file with offset and limit."""
        (tmp_workspace / "multi.txt").write_text("line1\nline2\nline3\nline4\n")
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        content = workspace_manager.read_file(ws.id, "multi.txt", offset=1, limit=2)
        lines = content.content.split("\n")
        assert lines[0] == "line2"
        assert len(lines) == 2

    async def test_write_file(self, workspace_manager: WorkspaceManager, tmp_workspace: Path):
        """Write a new file to a workspace."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        result = workspace_manager.write_file(ws.id, "new_file.txt", "new content")
        assert "File written" in result
        assert (tmp_workspace / "new_file.txt").read_text() == "new content"

    async def test_write_file_creates_parent_dirs(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """Writing creates parent directories if needed."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        workspace_manager.write_file(ws.id, "deep/nested/file.txt", "deep content")
        assert (tmp_workspace / "deep" / "nested" / "file.txt").exists()

    async def test_write_empty_to_existing_file_raises(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """Writing empty content to existing file raises PermissionDeniedError."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        with pytest.raises(PermissionDeniedError):
            workspace_manager.write_file(ws.id, "hello.txt", "   ")

    async def test_get_file_tree(self, workspace_manager: WorkspaceManager, tmp_workspace: Path):
        """File tree lists files and directories."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        tree = workspace_manager.get_file_tree(ws.id)
        names = {node.name for node in tree}
        assert "hello.txt" in names
        assert "subdir" in names

    async def test_get_file_tree_nonexistent_dir(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """File tree on non-existent dir raises NotFoundError."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        with pytest.raises(NotFoundError, match="Not a directory"):
            workspace_manager.get_file_tree(ws.id, "nonexistent_dir")

    async def test_rename_file(self, workspace_manager: WorkspaceManager, tmp_workspace: Path):
        """File can be renamed."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        result = workspace_manager.rename_file(ws.id, "hello.txt", "renamed.txt")
        assert "Renamed" in result
        assert not (tmp_workspace / "hello.txt").exists()
        assert (tmp_workspace / "renamed.txt").exists()

    async def test_rename_to_existing_file_raises(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """Renaming to an existing file raises AlreadyExistsError."""
        (tmp_workspace / "target.txt").write_text("existing")
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        with pytest.raises(AlreadyExistsError):
            workspace_manager.rename_file(ws.id, "hello.txt", "target.txt")

    async def test_rename_nonexistent_source(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """Renaming a non-existent source file raises NotFoundError."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        with pytest.raises(NotFoundError, match="Source not found"):
            workspace_manager.rename_file(ws.id, "ghost.txt", "new.txt")

    async def test_mkdir(self, workspace_manager: WorkspaceManager, tmp_workspace: Path):
        """Directory can be created."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        result = workspace_manager.mkdir(ws.id, "new_dir")
        assert "Created directory" in result
        assert (tmp_workspace / "new_dir").is_dir()

    async def test_mkdir_existing_raises(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """Creating an existing directory raises AlreadyExistsError."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        with pytest.raises(AlreadyExistsError):
            workspace_manager.mkdir(ws.id, "subdir")

    async def test_delete_file(self, workspace_manager: WorkspaceManager, tmp_workspace: Path):
        """File can be deleted."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        result = workspace_manager.delete_path(ws.id, "hello.txt")
        assert "Deleted" in result
        assert not (tmp_workspace / "hello.txt").exists()

    async def test_delete_directory(self, workspace_manager: WorkspaceManager, tmp_workspace: Path):
        """Directory can be deleted recursively."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        result = workspace_manager.delete_path(ws.id, "subdir")
        assert "Deleted" in result
        assert not (tmp_workspace / "subdir").exists()

    async def test_delete_nonexistent_raises(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """Deleting a non-existent path raises NotFoundError."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        with pytest.raises(NotFoundError, match="Not found"):
            workspace_manager.delete_path(ws.id, "ghost.txt")

    async def test_delete_workspace_root_raises(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """Deleting workspace root raises PermissionDeniedError."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        with pytest.raises(PermissionDeniedError, match="Cannot delete workspace root"):
            workspace_manager.delete_path(ws.id, ".")

    async def test_upload_file(self, workspace_manager: WorkspaceManager, tmp_workspace: Path):
        """Binary content can be uploaded."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        workspace_manager.upload_file(ws.id, ".", "upload.bin", b"\x00\x01\x02")
        assert (tmp_workspace / "upload.bin").exists()
        assert (tmp_workspace / "upload.bin").read_bytes() == b"\x00\x01\x02"

    async def test_upload_file_to_subdirectory(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """Upload creates subdirectory if needed."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        workspace_manager.upload_file(ws.id, "uploads", "data.txt", b"data")
        assert (tmp_workspace / "uploads" / "data.txt").exists()

    async def test_get_raw_file_path(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """get_raw_file_path returns an absolute Path."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        p = workspace_manager.get_raw_file_path(ws.id, "hello.txt")
        assert isinstance(p, Path)
        assert p.is_absolute()
        assert p.name == "hello.txt"

    async def test_get_raw_file_path_nonexistent(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """get_raw_file_path raises NotFoundError for non-existent file."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        with pytest.raises(NotFoundError):
            workspace_manager.get_raw_file_path(ws.id, "ghost.txt")


class TestWorkspacePathSafety:
    """Path traversal protection tests."""

    async def test_path_traversal_blocked(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """Path traversal attempts are blocked."""
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        with pytest.raises(InvalidPathError, match="Path traversal"):
            workspace_manager.read_file(ws.id, "../../etc/passwd")

    async def test_resolve_safe_path_nonexistent_workspace(
        self, workspace_manager: WorkspaceManager
    ):
        """Resolving path for non-existent workspace raises NotFoundError."""
        with pytest.raises(NotFoundError, match="Workspace not found"):
            workspace_manager._resolve_safe_path("nonexistent", "file.txt")


class TestWorkspaceFileTreeFiltering:
    """File tree filtering of ignored directories and files."""

    async def test_ignored_dirs_excluded(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """Ignored directories like .git and node_modules are excluded from tree."""
        (tmp_workspace / ".git").mkdir()
        (tmp_workspace / "node_modules").mkdir()
        (tmp_workspace / "src").mkdir()
        (tmp_workspace / "src" / "app.py").write_text("# app")

        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        tree = workspace_manager.get_file_tree(ws.id)
        names = {node.name for node in tree}
        assert ".git" not in names
        assert "node_modules" not in names
        assert "src" in names

    async def test_ignored_files_excluded(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """Ignored files like .DS_Store are excluded from tree."""
        (tmp_workspace / ".DS_Store").write_text("")
        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        tree = workspace_manager.get_file_tree(ws.id)
        names = {node.name for node in tree}
        assert ".DS_Store" not in names

    async def test_max_depth_respected(
        self, workspace_manager: WorkspaceManager, tmp_workspace: Path
    ):
        """File tree respects max_depth parameter."""
        deep = tmp_workspace / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "deep.txt").write_text("deep")

        ws = await workspace_manager.create_workspace("WS", str(tmp_workspace))
        tree = workspace_manager.get_file_tree(ws.id, max_depth=1)

        # depth=1: top-level dirs have children scanned, but their children's children are None
        for node in tree:
            if node.type == "dir" and node.children:
                for child in node.children:
                    if child.type == "dir":
                        assert child.children is None
