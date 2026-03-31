"""Unified file operation tools — context-aware routing for workspace, page, and skill.

Replaces duplicated workspace_*/page_*/skill file tools with 7 unified tools:
  read_file, write_file, edit_file, search, list_files, apply_patch, bash

Context is auto-detected from active workspace/page state, or explicit via `context` param.
"""

import logging
from pathlib import Path
from typing import Any

from open_agent.core.exceptions import InvalidPathError
from open_agent.core.page_manager import page_manager
from open_agent.core.workspace_manager import workspace_manager

from core.request_context import get_current_user_id

logger = logging.getLogger(__name__)


def _current_owner_user_id() -> str | None:
    return get_current_user_id()


UNIFIED_TOOL_NAMES = {
    "read_file",
    "write_file",
    "edit_file",
    "search",
    "list_files",
    "apply_patch",
    "bash",
}

# Backward compatibility: old tool names → unified name + context hint
_LEGACY_NAME_MAP = {
    # Workspace tools
    "workspace_read_file": ("read_file", "workspace"),
    "workspace_write_file": ("write_file", "workspace"),
    "workspace_edit_file": ("edit_file", "workspace"),
    "workspace_grep": ("search", "workspace"),
    "workspace_list_dir": ("list_files", "workspace"),
    "workspace_apply_patch": ("apply_patch", "workspace"),
    "workspace_bash": ("bash", "workspace"),
    # Page tools
    "page_read_file": ("read_file", "page"),
    "page_write_file": ("write_file", "page"),
    "page_edit_file": ("edit_file", "page"),
    "page_grep": ("search", "page"),
    "page_list_files": ("list_files", "page"),
    # Skill tools
    "edit_skill_script": ("edit_file", "skill"),
    "patch_skill_script": ("apply_patch", "skill"),
    "add_skill_script": ("write_file", "skill"),
    "read_skill_reference": ("read_file", "skill"),
}

# Web-focused extensions allowed for page file creation
_PAGE_ALLOWED_EXTENSIONS = {
    ".html",
    ".htm",
    ".css",
    ".js",
    ".jsx",
    ".tsx",
    ".ts",
    ".mjs",
    ".json",
    ".xml",
    ".svg",
    ".md",
    ".txt",
    ".csv",
}


def resolve_legacy_tool(function_name: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Map legacy tool names to unified names with context hint injection."""
    if function_name in _LEGACY_NAME_MAP:
        unified_name, context_hint = _LEGACY_NAME_MAP[function_name]
        args = dict(args)  # shallow copy
        args.setdefault("context", context_hint)

        # Remap parameter names for skill tools
        if function_name == "edit_skill_script":
            args["path"] = args.pop("filename", args.get("path", ""))
            args["_skill_name"] = args.pop("skill_name", "")
        elif function_name == "patch_skill_script":
            args["_skill_name"] = args.pop("skill_name", "")
            args["_filename"] = args.pop("filename", "")
        elif function_name == "add_skill_script":
            args["path"] = args.pop("filename", args.get("path", ""))
            args["_skill_name"] = args.pop("skill_name", "")
        elif function_name == "read_skill_reference":
            args["path"] = args.pop("reference_path", args.get("path", ""))
            args["_skill_name"] = args.pop("skill_name", "")

        return unified_name, args
    return function_name, args


def _resolve_context(args: dict[str, Any]) -> str:
    """Determine the target context: 'workspace', 'page', or error."""
    explicit = args.get("context")
    if explicit in ("workspace", "page", "skill"):
        return explicit

    owner_user_id = _current_owner_user_id()
    has_workspace = workspace_manager.get_active(owner_user_id=owner_user_id) is not None
    has_page = page_manager.get_active_page() is not None

    if has_workspace and not has_page:
        return "workspace"
    if has_page and not has_workspace:
        return "page"
    if has_workspace and has_page:
        # Both active: check if path exists in either context
        path = args.get("path", "")
        if path:
            # Try workspace first (safe path check)
            try:
                active_ws = workspace_manager.get_active(owner_user_id=owner_user_id)
                if active_ws:
                    ws_root = Path(active_ws.path).resolve()
                    ws_path = (ws_root / path).resolve()
                    if ws_path.is_relative_to(ws_root) and ws_path.exists():
                        return "workspace"
            except (FileNotFoundError, PermissionError, OSError):
                pass
            # Try page
            page = page_manager.get_active_page()
            if page:
                content = page_manager.read_page_file(page.id, path)
                if content is not None:
                    return "page"
        # Default to workspace when both are active and path is ambiguous
        return "workspace"

    return "__none__"


# --- Unified tool definitions ---


def get_unified_tools() -> list[dict[str, Any]]:
    """Return unified tools based on active contexts."""
    owner_user_id = _current_owner_user_id()
    has_workspace = workspace_manager.get_active(owner_user_id=owner_user_id) is not None
    has_page = page_manager.get_active_page() is not None

    if not has_workspace and not has_page:
        return []

    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": (
                    "활성 워크스페이스 또는 페이지의 파일을 읽습니다 (스킬 파일은 read_skill 사용). "
                    "활성 컨텍스트에 따라 자동 라우팅됩니다. "
                    "대용량 파일은 offset/limit으로 범위를 지정하여 부분 읽기가 가능합니다."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "파일 경로 (상대 경로)"},
                        "offset": {
                            "type": "integer",
                            "description": "읽기 시작 라인 번호 (0-based, 기본: 0)",
                            "default": 0,
                        },
                        "limit": {
                            "type": "integer",
                            "description": "읽을 라인 수 (생략 시 전체 파일)",
                        },
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": (
                    "파일을 생성하거나 덮어씁니다. "
                    "워크스페이스에서는 상위 디렉토리를 자동 생성합니다. "
                    "페이지에서는 허용된 웹 확장자(.html, .css, .js 등)만 가능하며, "
                    "단일 파일 페이지는 자동으로 번들로 변환됩니다. "
                    "일부만 수정하려면 edit_file을 사용하세요."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "파일 경로 (상대 경로)"},
                        "content": {"type": "string", "description": "파일에 쓸 전체 내용"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "edit_file",
                "description": (
                    "파일의 특정 부분을 찾아 교체합니다 (전체 덮어쓰기 대신 부분 수정). "
                    "4단계 퍼지 매칭(정확→우측공백→양측공백→유니코드)으로 "
                    "공백·들여쓰기 차이를 자동 보정합니다. "
                    "매칭 실패 시 가장 유사한 코드 블록과 유사도를 힌트로 제공합니다."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "수정할 파일 경로"},
                        "old_string": {
                            "type": "string",
                            "description": "교체할 기존 문자열 (파일 내 유일해야 함)",
                        },
                        "new_string": {"type": "string", "description": "새로 삽입할 문자열"},
                        "replace_all": {
                            "type": "boolean",
                            "description": "true면 모든 일치를 교체 (기본: false)",
                            "default": False,
                        },
                    },
                    "required": ["path", "old_string", "new_string"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": (
                    "활성 워크스페이스 또는 페이지의 파일 내용을 정규식(regex)으로 검색합니다 (스킬 파일은 검색 불가). "
                    "Rust 네이티브 엔진으로 고속 검색됩니다. "
                    "glob_filter로 특정 파일 유형만 검색할 수 있습니다 (예: *.py). "
                    ".git, node_modules 등은 자동 제외됩니다."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "검색할 정규식 패턴"},
                        "path": {
                            "type": "string",
                            "description": "검색 시작 경로 (기본: 루트)",
                            "default": ".",
                        },
                        "glob_filter": {
                            "type": "string",
                            "description": "파일 필터 glob 패턴 (예: *.py, *.ts)",
                        },
                        "case_insensitive": {
                            "type": "boolean",
                            "description": "대소문자 무시 여부 (기본: false)",
                            "default": False,
                        },
                        "context_lines": {
                            "type": "integer",
                            "description": "매치 전후로 표시할 컨텍스트 라인 수 (기본: 0)",
                            "default": 0,
                        },
                        "limit": {
                            "type": "integer",
                            "description": "최대 매치 수 (기본: 50)",
                            "default": 50,
                        },
                    },
                    "required": ["pattern"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": (
                    "활성 워크스페이스 또는 페이지의 파일/디렉토리 구조를 반환합니다 (스킬 디렉토리는 탐색 불가). "
                    "워크스페이스에서는 트리 형태, 페이지에서는 번들 파일 목록. "
                    ".git, node_modules 등은 자동 제외됩니다."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "탐색 시작 경로 (기본: 루트)",
                            "default": ".",
                        },
                        "recursive": {
                            "type": "boolean",
                            "description": "하위 디렉토리 재귀 탐색 (기본: false)",
                            "default": False,
                        },
                        "max_depth": {
                            "type": "integer",
                            "description": "최대 탐색 깊이 (기본: 3)",
                            "default": 3,
                        },
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "apply_patch",
                "description": (
                    "unified diff 형식의 패치를 파일에 적용합니다. "
                    "한 번의 호출로 여러 파일을 동시에 수정할 수 있어 대규모 변경에 적합합니다. "
                    "패치 형식: '--- a/path\\n+++ b/path\\n@@ -start,count +start,count @@'."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patch": {
                            "type": "string",
                            "description": "unified diff 형식의 패치 텍스트",
                        },
                    },
                    "required": ["patch"],
                },
            },
        },
    ]

    # bash is workspace-only
    if has_workspace:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": (
                        "워크스페이스에서 셸 명령을 실행합니다 (워크스페이스 전용). "
                        "빌드, 테스트, 린트, 의존성 설치, git 명령 등에 사용하세요. "
                        "보안상 파일 삭제(rm), 이동(mv) 등 파괴적 명령은 차단됩니다. "
                        "타임아웃 기본 30초, 최대 120초."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "실행할 셸 명령어"},
                            "cwd": {
                                "type": "string",
                                "description": "작업 디렉토리 (상대 경로, 생략 시 루트)",
                            },
                            "timeout": {
                                "type": "integer",
                                "description": "타임아웃 초 (기본: 30, 최대: 120)",
                                "default": 30,
                            },
                        },
                        "required": ["command"],
                    },
                },
            }
        )

    return tools


# --- Handlers ---


async def handle_unified_tool_call(tool_name: str, args: dict[str, Any]) -> "str | dict[str, Any]":
    """Route unified tool calls to appropriate backend."""
    ctx = _resolve_context(args)

    try:
        if tool_name == "read_file":
            return _handle_read_file(ctx, args)
        elif tool_name == "write_file":
            return await _handle_write_file(ctx, args)
        elif tool_name == "edit_file":
            return await _handle_edit_file(ctx, args)
        elif tool_name == "search":
            return _handle_search(ctx, args)
        elif tool_name == "list_files":
            return _handle_list_files(ctx, args)
        elif tool_name == "apply_patch":
            return _handle_apply_patch(ctx, args)
        elif tool_name == "bash":
            return await _handle_bash(args)
        else:
            return f"Error: Unknown unified tool '{tool_name}'"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.error("Unified tool error (%s): %s", tool_name, e)
        return f"Error: {e}"


def _handle_read_file(ctx: str, args: dict[str, Any]) -> str:
    path = args.get("path", "")
    if not path:
        return 'Error: path is required. 예: {"path": "folder/filename.ext", "content": "..."}'

    if ctx == "workspace":
        owner_user_id = _current_owner_user_id()
        active = workspace_manager.get_active(owner_user_id=owner_user_id)
        if not active:
            return "Error: 활성 워크스페이스가 없습니다."
        fc = workspace_manager.read_file(
            active.id,
            path,
            offset=args.get("offset", 0),
            limit=args.get("limit"),
            owner_user_id=owner_user_id,
        )
        lines = fc.content.split("\n")
        offset = fc.offset
        numbered = "\n".join(f"{offset + i + 1:>6}\t{line}" for i, line in enumerate(lines))
        header = f"File: {fc.path} ({fc.total_lines} lines total)"
        if fc.offset > 0 or fc.limit:
            header += f" [showing lines {fc.offset + 1}-{fc.offset + len(lines)}]"
        return f"{header}\n{numbered}"

    elif ctx == "page":
        page = page_manager.get_active_page()
        if not page:
            return "Error: 활성 페이지가 없습니다. // 명령으로 페이지를 선택하세요."
        content = page_manager.read_page_file(page.id, path)
        if content is None:
            return f"Error: 파일 '{path}'을(를) 찾을 수 없습니다."
        # Apply offset/limit if provided
        offset = args.get("offset", 0)
        limit = args.get("limit")
        lines = content.split("\n")
        total = len(lines)
        if offset > 0 or limit:
            end = offset + limit if limit else total
            lines = lines[offset:end]
        numbered = "\n".join(f"{offset + i + 1:>6}\t{line}" for i, line in enumerate(lines))
        header = f"File: {path} ({total} lines total)"
        if offset > 0 or limit:
            header += f" [showing lines {offset + 1}-{offset + len(lines)}]"
        return f"{header}\n{numbered}"

    elif ctx == "skill":
        from open_agent.core.skill_manager import skill_manager

        skill_name = args.get("_skill_name", "")
        if not skill_name:
            return "Error: skill_name is required for skill context"
        content = skill_manager.load_skill_reference(skill_name, path)
        if content is None:
            return f"Error: Reference '{path}' not found in skill '{skill_name}'"
        return content

    return "Error: 활성 워크스페이스 또는 페이지가 없습니다."


async def _handle_write_file(ctx: str, args: dict[str, Any]) -> str:
    path = args.get("path", "")
    content = args.get("content", "")
    if not path:
        return 'Error: path is required. 예: {"path": "folder/filename.ext", "content": "..."}'

    if ctx == "workspace":
        owner_user_id = _current_owner_user_id()
        active = workspace_manager.get_active(owner_user_id=owner_user_id)
        if not active:
            return "Error: 활성 워크스페이스가 없습니다."
        return workspace_manager.write_file(
            active.id,
            path,
            content,
            owner_user_id=owner_user_id,
        )

    elif ctx == "page":
        page = page_manager.get_active_page()
        if not page:
            return "Error: 활성 페이지가 없습니다."

        ext = Path(path).suffix.lower()
        if ext not in _PAGE_ALLOWED_EXTENSIONS:
            return f"Error: 허용되지 않는 확장자: {ext} (허용: {', '.join(sorted(_PAGE_ALLOWED_EXTENSIONS))})"
        # Path traversal check
        page_dir = page_manager.get_page_dir(page.id)
        if page_dir:
            target = (page_dir / path).resolve()
            if not target.is_relative_to(page_dir.resolve()):
                return "Error: 경로 순회가 감지되었습니다."

        # Auto-convert single file page to bundle
        p = page_manager.get_page(page.id)
        if p and p.content_type == "html":
            existing = page_manager.list_page_files(page.id) or []
            if path not in existing:
                await page_manager.convert_to_bundle(page.id)

        result = await page_manager.write_page_file(page.id, path, content)
        if result is None:
            return f"Error: 파일 '{path}' 쓰기 실패."
        return f"파일 '{path}' 저장 완료."

    elif ctx == "skill":
        from open_agent.core.skill_manager import skill_manager

        skill_name = args.get("_skill_name", "")
        if not skill_name:
            return "Error: skill_name is required for skill context"
        # Skill's add_skill_script is sync (only execute_script is async)
        skill = skill_manager.get_skill(skill_name)
        if not skill:
            return f"Error: 스킬 '{skill_name}'을(를) 찾을 수 없습니다."
        if "/" in path or "\\" in path or ".." in path:
            return f"Error: 파일명에 경로 구분자나 '..'를 포함할 수 없습니다: {path}"
        allowed_extensions = {".py", ".sh", ".js", ".ts", ".bat", ".cmd", ".ps1"}
        ext = Path(path).suffix.lower()
        if ext not in allowed_extensions:
            return f"Error: 허용되지 않는 확장자: {ext}"
        scripts_dir = Path(skill.path) / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        script_path = (scripts_dir / path).resolve()
        if not script_path.is_relative_to(scripts_dir.resolve()):
            return f"Error: 경로 순회 감지: {path}"
        script_path.write_text(content, encoding="utf-8")
        return f"스크립트 '{path}' 추가 완료. 경로: {script_path}"

    return "Error: 활성 워크스페이스 또는 페이지가 없습니다."


async def _handle_edit_file(ctx: str, args: dict[str, Any]) -> str:
    from open_agent.core.fuzzy import find_closest_match, fuzzy_find, fuzzy_replace

    path = args.get("path", "")
    old_string = args.get("old_string", "")
    new_string = args.get("new_string", "")
    replace_all = args.get("replace_all", False)

    if not path:
        return 'Error: path is required. 예: {"path": "folder/filename.ext", "content": "..."}'
    if not old_string:
        return "Error: old_string은 비어 있을 수 없습니다."

    # Read content based on context
    if ctx == "workspace":
        owner_user_id = _current_owner_user_id()
        active = workspace_manager.get_active(owner_user_id=owner_user_id)
        if not active:
            return "Error: 활성 워크스페이스가 없습니다."
        from open_agent.models.workspace import EditFileRequest

        req = EditFileRequest(
            path=path,
            old_string=old_string,
            new_string=new_string,
            replace_all=replace_all,
        )
        return workspace_manager.edit_file(active.id, req, owner_user_id=owner_user_id)

    elif ctx == "page":
        page = page_manager.get_active_page()
        if not page:
            return "Error: 활성 페이지가 없습니다."

        content = page_manager.read_page_file(page.id, path)
        if content is None:
            return f"Error: 파일 '{path}'을(를) 찾을 수 없습니다."

        match_mode, _pos, _matched_len = fuzzy_find(content, old_string)

        if match_mode is None:
            line_count = len(content.splitlines())
            best_line, ratio, snippet = find_closest_match(content, old_string)
            msg = f"old_string을 '{path}'에서 찾을 수 없습니다 ({line_count}줄)."
            if ratio > 0.4:
                msg += (
                    f"\n가장 유사한 영역 (줄 {best_line}, 유사도 {ratio:.0%}):\n"
                    f"  기대: {old_string[:300]!r}\n"
                    f"  발견: {snippet[:300]!r}\n"
                    f"힌트: read_file로 정확한 내용을 먼저 확인하세요."
                )
            return f"Error: {msg}"

        if match_mode == "exact":
            count = content.count(old_string)
            if count > 1 and not replace_all:
                return (
                    f"Error: old_string이 '{path}'에서 {count}번 발견되었습니다. "
                    "replace_all=true로 모두 교체하거나, 더 고유한 문자열을 지정하세요."
                )
            new_content = (
                content.replace(old_string, new_string)
                if replace_all
                else content.replace(old_string, new_string, 1)
            )
            replaced = count if replace_all else 1
        else:
            new_content = fuzzy_replace(content, old_string, new_string, match_mode)
            replaced = 1

        result = await page_manager.write_page_file(page.id, path, new_content)
        if result is None:
            return "Error: 파일 쓰기 실패."

        msg = f"파일 '{path}' 수정 완료: {replaced}건 교체"
        if match_mode != "exact":
            msg += f" ({match_mode} 매칭)"
        return msg

    elif ctx == "skill":
        from open_agent.core.skill_manager import skill_manager

        skill_name = args.get("_skill_name", "")
        if not skill_name:
            return "Error: skill_name is required for skill context"
        return skill_manager._handle_edit_skill_script(
            {
                "skill_name": skill_name,
                "filename": path,
                "old_string": old_string,
                "new_string": new_string,
                "replace_all": replace_all,
            }
        )

    return "Error: 활성 워크스페이스 또는 페이지가 없습니다."


def _handle_search(ctx: str, args: dict[str, Any]) -> str:
    from open_agent.core.grep_engine import grep

    pattern = args.get("pattern", "")
    search_path = args.get("path", ".")
    glob_filter = args.get("glob_filter")
    case_insensitive = args.get("case_insensitive", False)
    context_lines = args.get("context_lines", args.get("context", 0))
    limit = args.get("limit", 50)

    if not pattern:
        return "Error: pattern is required"

    if ctx == "workspace":
        owner_user_id = _current_owner_user_id()
        active = workspace_manager.get_active(owner_user_id=owner_user_id)
        if not active:
            return "Error: 활성 워크스페이스가 없습니다."
        ws = workspace_manager.get_workspace(active.id, owner_user_id=owner_user_id)
        if not ws:
            return "Error: Workspace not found"
        root = Path(ws.path).resolve()
        target = (root / search_path).resolve()
        if not target.is_relative_to(root):
            return "Error: Path traversal detected"
        return grep(root, target, pattern, glob_filter, case_insensitive, context_lines, limit)

    elif ctx == "page":
        page = page_manager.get_active_page()
        if not page:
            return "Error: 활성 페이지가 없습니다."
        # Get page's filesystem directory for Rust grep
        page_dir = page_manager.get_page_dir(page.id)
        if page_dir and page_dir.is_dir():
            return grep(
                page_dir, page_dir, pattern, glob_filter, case_insensitive, context_lines, limit
            )
        # Fallback: single file page
        html_path = page_manager.get_html_path(page.id)
        if html_path and html_path.is_file():
            return grep(
                html_path.parent,
                html_path,
                pattern,
                glob_filter,
                case_insensitive,
                context_lines,
                limit,
            )
        return "Error: 페이지 파일을 찾을 수 없습니다."

    return "Error: 활성 워크스페이스 또는 페이지가 없습니다."


def _handle_list_files(ctx: str, args: dict[str, Any]) -> str:
    if ctx == "workspace":
        owner_user_id = _current_owner_user_id()
        active = workspace_manager.get_active(owner_user_id=owner_user_id)
        if not active:
            return "Error: 활성 워크스페이스가 없습니다."
        path = args.get("path", ".")
        recursive = args.get("recursive", False)
        max_depth = args.get("max_depth", 3) if recursive else 1
        nodes = workspace_manager.get_file_tree(
            active.id,
            path,
            max_depth,
            owner_user_id=owner_user_id,
        )
        lines: list[str] = []
        _format_tree(nodes, lines, "")
        if not lines:
            return f"Directory '{path}' is empty."
        return "\n".join(lines)

    elif ctx == "page":
        page = page_manager.get_active_page()
        if not page:
            return "Error: 활성 페이지가 없습니다."
        files = page_manager.list_page_files(page.id)
        if files is None:
            return "Error: 페이지를 찾을 수 없습니다."
        if not files:
            return "파일이 없습니다."
        return "\n".join(files)

    return "Error: 활성 워크스페이스 또는 페이지가 없습니다."


def _format_tree(nodes: list[Any], lines: list[str], prefix: str) -> None:
    for node in nodes:
        if node.type == "dir":
            lines.append(f"{prefix}{node.name}/")
            if node.children:
                _format_tree(node.children, lines, prefix + "  ")
        else:
            size_str = _format_size(node.size)
            lines.append(f"{prefix}{node.name}  ({size_str})")


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    else:
        return f"{size / (1024 * 1024):.1f}MB"


def _handle_apply_patch(ctx: str, args: dict[str, Any]) -> str:
    from open_agent.core.fuzzy import apply_patch_to_files

    patch_text = args.get("patch", "")
    if not patch_text.strip():
        return "Error: patch text is empty"

    if ctx == "workspace":
        owner_user_id = _current_owner_user_id()
        active = workspace_manager.get_active(owner_user_id=owner_user_id)
        if not active:
            return "Error: 활성 워크스페이스가 없습니다."
        ws = workspace_manager.get_workspace(active.id, owner_user_id=owner_user_id)
        if not ws:
            return "Error: Workspace not found"
        root = Path(ws.path).resolve()

        def path_validator(rel_path: str) -> Path:
            return workspace_manager._resolve_safe_path(
                active.id,
                rel_path,
                owner_user_id=owner_user_id,
            )

        return apply_patch_to_files(patch_text, str(root), path_validator=path_validator)

    elif ctx == "page":
        # Page: apply patch to page files
        page = page_manager.get_active_page()
        if not page:
            return "Error: 활성 페이지가 없습니다."
        page_dir = page_manager.get_page_dir(page.id)
        if not page_dir or not page_dir.is_dir():
            return "Error: 페이지 디렉토리를 찾을 수 없습니다."

        def page_path_validator(rel_path: str) -> Path:
            full = (page_dir / rel_path).resolve()
            if not full.is_relative_to(page_dir):
                raise InvalidPathError(f"Path traversal detected: {rel_path}")
            return full

        return apply_patch_to_files(patch_text, str(page_dir), path_validator=page_path_validator)

    elif ctx == "skill":
        from open_agent.core.skill_manager import skill_manager

        skill_name = args.get("_skill_name", "")
        filename = args.get("_filename", "")
        if skill_name and filename:
            return skill_manager._handle_patch_skill_script(
                {
                    "skill_name": skill_name,
                    "filename": filename,
                    "patch": patch_text,
                }
            )
        return "Error: skill_name and filename are required for skill context"

    return "Error: 활성 워크스페이스 또는 페이지가 없습니다."


async def _handle_bash(args: dict[str, Any]) -> "str | dict[str, Any]":
    """Bash is always workspace-only."""
    from open_agent.core.workspace_tools import handle_workspace_tool_call

    active = workspace_manager.get_active(owner_user_id=_current_owner_user_id())
    if not active:
        return "Error: bash는 워크스페이스 전용입니다. 워크스페이스를 먼저 활성화하세요."
    return await handle_workspace_tool_call("workspace_bash", args)
