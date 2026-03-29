import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from open_agent.core.exceptions import (
    AlreadyExistsError,
    InvalidPathError,
    NotFoundError,
    PermissionDeniedError,
)
from open_agent.models.workspace import (
    EditFileRequest,
    FileContent,
    FileTreeNode,
    WorkspaceInfo,
)

logger = logging.getLogger(__name__)

IGNORED_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".next", "dist", "build", ".cache", "target", ".idea", ".vscode",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", "egg-info",
}
IGNORED_DIRS_LOWER = {d.lower() for d in IGNORED_DIRS}
IGNORED_FILES = {".DS_Store", "Thumbs.db"}


class WorkspaceManager:
    def __init__(self):
        self._workspaces: Dict[str, WorkspaceInfo] = {}

    async def load_from_db(self) -> None:
        """Load all workspaces from database into in-memory cache."""
        from core.db.engine import async_session_factory
        from core.db.repositories.workspace_repo import WorkspaceRepository

        async with async_session_factory() as session:
            repo = WorkspaceRepository(session)
            rows = await repo.get_all()
            self._workspaces.clear()
            for row in rows:
                self._workspaces[row.id] = WorkspaceInfo(
                    id=row.id,
                    name=row.name,
                    path=row.path,
                    description=row.description,
                    created_at=row.created_at,
                    is_active=row.is_active,
                )
            logger.info(f"Loaded {len(self._workspaces)} workspaces from database")

    async def _persist_workspace(self, ws: WorkspaceInfo) -> None:
        """Write a single workspace to database."""
        from core.db.engine import async_session_factory
        from core.db.models.workspace import WorkspaceORM

        async with async_session_factory() as session:
            orm = WorkspaceORM(
                id=ws.id,
                name=ws.name,
                path=ws.path,
                description=ws.description,
                created_at=ws.created_at,
                is_active=ws.is_active,
            )
            await session.merge(orm)
            await session.commit()

    # --- CRUD ---

    async def create_workspace(self, name: str, path: str, description: str = "") -> WorkspaceInfo:
        abs_path = Path(path).expanduser().resolve()
        if not abs_path.is_dir():
            raise NotFoundError(f"Directory not found: {path}")

        wid = uuid.uuid4().hex[:8]
        workspace = WorkspaceInfo(
            id=wid,
            name=name,
            path=str(abs_path),
            description=description,
            created_at=datetime.now(timezone.utc).isoformat(),
            is_active=False,
        )
        self._workspaces[wid] = workspace
        await self._persist_workspace(workspace)
        logger.info(f"Created workspace: {name} ({abs_path})")
        return workspace

    def get_all(self) -> List[WorkspaceInfo]:
        return list(self._workspaces.values())

    def get_workspace(self, workspace_id: str) -> Optional[WorkspaceInfo]:
        return self._workspaces.get(workspace_id)

    async def update_workspace(
        self, workspace_id: str, name: Optional[str] = None, description: Optional[str] = None
    ) -> Optional[WorkspaceInfo]:
        ws = self._workspaces.get(workspace_id)
        if not ws:
            return None
        if name is not None:
            ws.name = name
        if description is not None:
            ws.description = description
        self._workspaces[workspace_id] = ws
        await self._persist_workspace(ws)
        return ws

    async def delete_workspace(self, workspace_id: str) -> bool:
        if workspace_id not in self._workspaces:
            return False

        from core.db.engine import async_session_factory
        from core.db.repositories.workspace_repo import WorkspaceRepository

        async with async_session_factory() as session:
            repo = WorkspaceRepository(session)
            await repo.delete_by_id(workspace_id)
            await session.commit()

        self._workspaces.pop(workspace_id)
        logger.info(f"Deleted workspace: {workspace_id}")
        return True

    async def set_active(self, workspace_id: str) -> Optional[WorkspaceInfo]:
        ws = self._workspaces.get(workspace_id)
        if not ws:
            return None

        from core.db.engine import async_session_factory
        from core.db.repositories.workspace_repo import WorkspaceRepository

        for w in self._workspaces.values():
            w.is_active = False
        ws.is_active = True

        async with async_session_factory() as session:
            repo = WorkspaceRepository(session)
            await repo.set_active(workspace_id)
            await session.commit()

        logger.info(f"Activated workspace: {ws.name}")
        return ws

    async def deactivate(self) -> None:
        from core.db.engine import async_session_factory
        from sqlalchemy import update
        from core.db.models.workspace import WorkspaceORM

        for w in self._workspaces.values():
            w.is_active = False

        async with async_session_factory() as session:
            await session.execute(update(WorkspaceORM).values(is_active=False))
            await session.commit()

        logger.info("All workspaces deactivated")

    def get_active(self) -> Optional[WorkspaceInfo]:
        for w in self._workspaces.values():
            if w.is_active:
                return w
        return None

    # --- File Operations (unchanged — filesystem only) ---

    def _resolve_safe_path(self, workspace_id: str, relative_path: str) -> Path:
        ws = self._workspaces.get(workspace_id)
        if not ws:
            raise NotFoundError(f"Workspace not found: {workspace_id}")
        root = Path(ws.path).resolve()
        abs_candidate = Path(relative_path).resolve()
        if abs_candidate != Path(relative_path) and abs_candidate.is_relative_to(root):
            relative_path = str(abs_candidate.relative_to(root))
        target = (root / relative_path).resolve()
        if not target.is_relative_to(root):
            raise InvalidPathError("Path traversal detected")
        return target

    def get_file_tree(
        self, workspace_id: str, path: str = ".", max_depth: int = 3
    ) -> List[FileTreeNode]:
        target = self._resolve_safe_path(workspace_id, path)
        if not target.is_dir():
            raise NotFoundError(f"Not a directory: {path}")
        ws = self._workspaces.get(workspace_id)
        root = Path(ws.path).resolve()  # type: ignore[union-attr]
        return self._scan_dir(target, root, max_depth, 0)

    def _scan_dir(
        self, dir_path: Path, root: Path, max_depth: int, current_depth: int
    ) -> List[FileTreeNode]:
        nodes: List[FileTreeNode] = []
        try:
            entries = sorted(dir_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return nodes

        for entry in entries:
            if entry.name in IGNORED_FILES:
                continue
            if entry.is_dir() and entry.name.lower() in IGNORED_DIRS_LOWER:
                continue

            rel = entry.relative_to(root).as_posix()
            if entry.is_dir():
                children = None
                if current_depth < max_depth:
                    children = self._scan_dir(entry, root, max_depth, current_depth + 1)
                nodes.append(FileTreeNode(
                    name=entry.name,
                    path=rel,
                    type="dir",
                    children=children,
                ))
            else:
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = 0
                nodes.append(FileTreeNode(
                    name=entry.name,
                    path=rel,
                    type="file",
                    size=size,
                ))
        return nodes

    def read_file(
        self, workspace_id: str, path: str, offset: int = 0, limit: Optional[int] = None
    ) -> FileContent:
        target = self._resolve_safe_path(workspace_id, path)
        if not target.is_file():
            raise NotFoundError(f"File not found: {path}")

        text = target.read_text(encoding="utf-8", errors="replace")
        lines = text.split('\n')
        total = len(lines)

        if offset > 0:
            lines = lines[offset:]
        if limit is not None and limit > 0:
            lines = lines[:limit]

        content = "\n".join(lines)
        return FileContent(
            path=path,
            content=content,
            total_lines=total,
            offset=offset,
            limit=limit,
        )

    def get_raw_file_path(self, workspace_id: str, path: str) -> Path:
        target = self._resolve_safe_path(workspace_id, path)
        if not target.is_file():
            raise NotFoundError(f"File not found: {path}")
        return target

    def rename_file(self, workspace_id: str, old_path: str, new_path: str) -> str:
        source = self._resolve_safe_path(workspace_id, old_path)
        target = self._resolve_safe_path(workspace_id, new_path)
        if not source.exists():
            raise NotFoundError(f"Source not found: {old_path}")
        if target.exists():
            raise AlreadyExistsError(f"Target already exists: {new_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
        return f"Renamed: {old_path} → {new_path}"

    def mkdir(self, workspace_id: str, path: str) -> str:
        target = self._resolve_safe_path(workspace_id, path)
        if target.exists():
            raise AlreadyExistsError(f"Already exists: {path}")
        target.mkdir(parents=True, exist_ok=True)
        return f"Created directory: {path}"

    def delete_path(self, workspace_id: str, path: str) -> str:
        import shutil
        target = self._resolve_safe_path(workspace_id, path)
        if not target.exists():
            raise NotFoundError(f"Not found: {path}")
        ws = self._workspaces.get(workspace_id)
        root = Path(ws.path).resolve()  # type: ignore[union-attr]
        if target == root:
            raise PermissionDeniedError("Cannot delete workspace root")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return f"Deleted: {path}"

    def upload_file(
        self, workspace_id: str, directory: str, filename: str, content_bytes: bytes
    ) -> str:
        rel_path = f"{directory}/{filename}" if directory and directory != "." else filename
        target = self._resolve_safe_path(workspace_id, rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content_bytes)
        return rel_path

    def write_file(self, workspace_id: str, path: str, content: str) -> str:
        target = self._resolve_safe_path(workspace_id, path)
        if not content.strip() and target.is_file():
            raise PermissionDeniedError(
                "빈 내용으로 기존 파일을 덮어쓸 수 없습니다. "
                "워크스페이스에서는 파일 삭제가 지원되지 않습니다."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"File written: {path} ({len(content)} chars)\nAbsolute path: {target}"

    def edit_file(self, workspace_id: str, req: EditFileRequest) -> str:
        from open_agent.core.fuzzy import find_closest_match, fuzzy_find, fuzzy_replace

        target = self._resolve_safe_path(workspace_id, req.path)
        if not target.is_file():
            raise NotFoundError(f"File not found: {req.path}")

        if not req.old_string:
            raise ValueError("old_string cannot be empty")

        content = target.read_text(encoding="utf-8")

        match_mode, pos, matched_len = fuzzy_find(content, req.old_string)

        if match_mode is None:
            line_count = len(content.splitlines())
            best_line, ratio, snippet = find_closest_match(content, req.old_string)
            msg = f"old_string not found in {req.path} ({line_count} lines)."
            if ratio > 0.4:
                snippet_preview = snippet[:300]
                old_preview = req.old_string[:300]
                msg += (
                    f"\nClosest match (line {best_line}, {ratio:.0%} similar):\n"
                    f"  Expected: {old_preview!r}\n"
                    f"  Found:    {snippet_preview!r}\n"
                    f"Hint: Use read_file first to get the exact content, then retry."
                )
            raise ValueError(msg)

        if match_mode == "exact":
            count = content.count(req.old_string)
            if count > 1 and not req.replace_all:
                raise ValueError(
                    f"old_string found {count} times in {req.path}. "
                    "Use replace_all=true to replace all, or provide a more unique string."
                )
            if req.replace_all:
                new_content = content.replace(req.old_string, req.new_string)
            else:
                new_content = content.replace(req.old_string, req.new_string, 1)
            replaced = count if req.replace_all else 1
        else:
            new_content = fuzzy_replace(content, req.old_string, req.new_string, match_mode)
            replaced = 1

        target.write_text(new_content, encoding="utf-8")
        msg = f"Edited {req.path}: {replaced} replacement(s) made"
        if match_mode != "exact":
            msg += f" (matched via {match_mode})"
        return msg


workspace_manager = WorkspaceManager()
