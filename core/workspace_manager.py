import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

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
        self._config_path: Optional[Path] = None

    def load_config(self, config_path: str) -> None:
        path = Path(config_path)
        if not path.is_absolute():
            from open_agent.config import get_config_path
            path = get_config_path(config_path)
        self._config_path = path

        if not path.exists():
            path.write_text(json.dumps({"workspaces": {}}, indent=2), encoding="utf-8")
            self._workspaces = {}
            return

        data = json.loads(path.read_text(encoding="utf-8"))
        for wid, info in data.get("workspaces", {}).items():
            self._workspaces[wid] = WorkspaceInfo(
                id=wid,
                name=info["name"],
                path=info["path"],
                description=info.get("description", ""),
                created_at=info.get("created_at", ""),
                is_active=info.get("is_active", False),
            )
        logger.info(f"Loaded {len(self._workspaces)} workspaces from {path}")

    def _save_config(self) -> None:
        if not self._config_path:
            return
        data: dict = {"workspaces": {}}
        for wid, w in self._workspaces.items():
            data["workspaces"][wid] = {
                "name": w.name,
                "path": w.path,
                "description": w.description,
                "created_at": w.created_at,
                "is_active": w.is_active,
            }
        self._config_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    # --- CRUD ---

    def create_workspace(self, name: str, path: str, description: str = "") -> WorkspaceInfo:
        abs_path = Path(path).expanduser().resolve()
        if not abs_path.is_dir():
            raise ValueError(f"Directory not found: {path}")

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
        self._save_config()
        logger.info(f"Created workspace: {name} ({abs_path})")
        return workspace

    def get_all(self) -> List[WorkspaceInfo]:
        return list(self._workspaces.values())

    def get_workspace(self, workspace_id: str) -> Optional[WorkspaceInfo]:
        return self._workspaces.get(workspace_id)

    def update_workspace(
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
        self._save_config()
        return ws

    def delete_workspace(self, workspace_id: str) -> bool:
        if workspace_id not in self._workspaces:
            return False
        self._workspaces.pop(workspace_id)
        self._save_config()
        logger.info(f"Deleted workspace: {workspace_id}")
        return True

    def set_active(self, workspace_id: str) -> Optional[WorkspaceInfo]:
        ws = self._workspaces.get(workspace_id)
        if not ws:
            return None
        # 기존 활성 워크스페이스 비활성화
        for w in self._workspaces.values():
            w.is_active = False
        ws.is_active = True
        self._save_config()
        logger.info(f"Activated workspace: {ws.name}")
        return ws

    def deactivate(self) -> None:
        for w in self._workspaces.values():
            w.is_active = False
        self._save_config()
        logger.info("All workspaces deactivated")

    def get_active(self) -> Optional[WorkspaceInfo]:
        for w in self._workspaces.values():
            if w.is_active:
                return w
        return None

    # --- File Operations ---

    def _resolve_safe_path(self, workspace_id: str, relative_path: str) -> Path:
        ws = self._workspaces.get(workspace_id)
        if not ws:
            raise ValueError(f"Workspace not found: {workspace_id}")
        root = Path(ws.path).resolve()
        # 절대경로가 워크스페이스 내부이면 상대경로로 변환
        abs_candidate = Path(relative_path).resolve()
        if abs_candidate != Path(relative_path) and abs_candidate.is_relative_to(root):
            relative_path = str(abs_candidate.relative_to(root))
        target = (root / relative_path).resolve()
        if not target.is_relative_to(root):
            raise ValueError("Path traversal detected")
        return target

    def get_file_tree(
        self, workspace_id: str, path: str = ".", max_depth: int = 3
    ) -> List[FileTreeNode]:
        target = self._resolve_safe_path(workspace_id, path)
        if not target.is_dir():
            raise ValueError(f"Not a directory: {path}")
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
            raise ValueError(f"File not found: {path}")

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
        """바이너리 파일 서빙을 위한 경로 반환 (보안 검증 포함)."""
        target = self._resolve_safe_path(workspace_id, path)
        if not target.is_file():
            raise ValueError(f"File not found: {path}")
        return target

    def rename_file(self, workspace_id: str, old_path: str, new_path: str) -> str:
        source = self._resolve_safe_path(workspace_id, old_path)
        target = self._resolve_safe_path(workspace_id, new_path)
        if not source.exists():
            raise ValueError(f"Source not found: {old_path}")
        if target.exists():
            raise ValueError(f"Target already exists: {new_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
        return f"Renamed: {old_path} → {new_path}"

    def mkdir(self, workspace_id: str, path: str) -> str:
        target = self._resolve_safe_path(workspace_id, path)
        if target.exists():
            raise ValueError(f"Already exists: {path}")
        target.mkdir(parents=True, exist_ok=True)
        return f"Created directory: {path}"

    def delete_path(self, workspace_id: str, path: str) -> str:
        import shutil
        target = self._resolve_safe_path(workspace_id, path)
        if not target.exists():
            raise ValueError(f"Not found: {path}")
        ws = self._workspaces.get(workspace_id)
        root = Path(ws.path).resolve()  # type: ignore[union-attr]
        if target == root:
            raise ValueError("Cannot delete workspace root")
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
        # 빈 content로 기존 파일 덮어쓰기 차단 (삭제 우회 방지)
        if not content.strip() and target.is_file():
            raise ValueError(
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
            raise ValueError(f"File not found: {req.path}")

        if not req.old_string:
            raise ValueError("old_string cannot be empty")

        content = target.read_text(encoding="utf-8")

        # 4-pass fuzzy matching: exact → rstrip → trim → unicode
        match_mode, pos, matched_len = fuzzy_find(content, req.old_string)

        if match_mode is None:
            # Build detailed error with closest match hint
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
            # Fuzzy match: replace matched line range
            new_content = fuzzy_replace(content, req.old_string, req.new_string, match_mode)
            replaced = 1

        target.write_text(new_content, encoding="utf-8")
        msg = f"Edited {req.path}: {replaced} replacement(s) made"
        if match_mode != "exact":
            msg += f" (matched via {match_mode})"
        return msg


workspace_manager = WorkspaceManager()
