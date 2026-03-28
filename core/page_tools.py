"""LLM tools for page file operations and page management.

Page management tools (create, folder, move) are always available.
File editing tools (list, read, write, edit) require a page activated via `//`.
Uses the same Rust-accelerated fuzzy matching engine as workspace and skill tools.
"""

import fnmatch
import json
import logging
import re
from typing import Any, Dict, List, Optional

from open_agent.core.page_manager import page_manager

logger = logging.getLogger(__name__)

# Tools that require an active page (// command)
_ACTIVE_PAGE_TOOL_NAMES = {
    "page_list_files",
    "page_read_file",
    "page_write_file",
    "page_edit_file",
    "page_grep",
}

# Tools always available (page management)
_MANAGEMENT_TOOL_NAMES = {
    "page_create_page",
    "page_create_folder",
    "page_move",
}

PAGE_TOOL_NAMES = _ACTIVE_PAGE_TOOL_NAMES | _MANAGEMENT_TOOL_NAMES

# Web-focused extensions allowed for page file creation
_ALLOWED_EXTENSIONS = {
    ".html", ".htm", ".css", ".js", ".jsx", ".tsx", ".ts", ".mjs",
    ".json", ".xml", ".svg", ".md", ".txt", ".csv",
}


# --- Tool definitions ---

_MANAGEMENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "page_create_page",
            "description": (
                "새로운 페이지를 생성하고 자동 활성화합니다. "
                "content에 초기 HTML을 제공하면 즉시 사용 가능한 페이지가 만들어집니다. "
                "여러 파일(CSS, JS 등)을 추가할 수 있는 번들 페이지로 생성됩니다. "
                "parent_id를 지정하면 특정 폴더 안에 생성합니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "페이지 이름"},
                    "description": {"type": "string", "description": "페이지 설명"},
                    "content": {"type": "string", "description": "초기 HTML 내용 (index.html)"},
                    "parent_id": {"type": "string", "description": "생성할 폴더 ID (생략 시 루트)"},
                },
                "required": ["name", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "page_create_folder",
            "description": (
                "페이지를 정리할 폴더를 생성합니다. "
                "parent_id를 지정하면 중첩 폴더를 만들 수 있습니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "폴더 이름"},
                    "description": {"type": "string", "description": "폴더 설명"},
                    "parent_id": {"type": "string", "description": "상위 폴더 ID (생략 시 루트)"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "page_move",
            "description": (
                "페이지나 폴더를 다른 폴더로 이동합니다. "
                "target_folder_id를 생략하거나 null로 설정하면 루트로 이동합니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "page_id": {"type": "string", "description": "이동할 페이지 또는 폴더의 ID"},
                    "target_folder_id": {
                        "type": ["string", "null"],
                        "description": "이동 대상 폴더 ID (null이면 루트)",
                    },
                },
                "required": ["page_id"],
            },
        },
    },
]


def _get_active_page_tools() -> List[Dict[str, Any]]:
    """Return file editing tools (only when a page is active)."""
    return [
        {
            "type": "function",
            "function": {
                "name": "page_list_files",
                "description": (
                    "활성 페이지의 파일 목록을 반환합니다. "
                    "번들 페이지는 여러 파일(HTML, CSS, JS 등)을 포함하며, "
                    "단일 파일 페이지는 해당 파일 하나만 반환합니다."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "page_read_file",
                "description": (
                    "활성 페이지의 파일 내용을 읽습니다. "
                    "page_list_files로 파일 목록을 먼저 확인한 후, "
                    "수정하려는 파일의 정확한 경로를 지정하세요."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "읽을 파일 경로 (번들 루트 기준, 예: index.html, css/style.css)",
                        },
                    },
                    "required": ["file_path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "page_write_file",
                "description": (
                    "활성 페이지에 파일을 생성하거나 덮어씁니다. "
                    "새 파일을 추가할 때도 이 도구를 사용합니다. "
                    "허용 확장자: .html, .htm, .css, .js, .jsx, .tsx, .ts, .json, .xml, .svg, .md, .txt, .csv. "
                    "단일 파일 페이지에서 새 파일을 추가하면 자동으로 번들로 변환됩니다."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "파일 경로 (번들 루트 기준, 예: style.css, js/app.js)",
                        },
                        "content": {
                            "type": "string",
                            "description": "파일 내용 전체",
                        },
                    },
                    "required": ["file_path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "page_edit_file",
                "description": (
                    "활성 페이지 파일의 특정 부분을 찾아 교체합니다 (전체 덮어쓰기 대신 부분 수정). "
                    "4단계 퍼지 매칭을 사용하여 공백·들여쓰기 차이를 자동 보정합니다. "
                    "전체 파일을 다시 쓸 필요 없이 변경할 부분만 지정하세요."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "수정할 파일 경로",
                        },
                        "old_string": {
                            "type": "string",
                            "description": "교체할 기존 코드 (파일에서 찾을 텍스트)",
                        },
                        "new_string": {
                            "type": "string",
                            "description": "새로 삽입할 코드",
                        },
                        "replace_all": {
                            "type": "boolean",
                            "description": "true면 모든 일치를 교체 (기본: false)",
                        },
                    },
                    "required": ["file_path", "old_string", "new_string"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "page_grep",
                "description": (
                    "활성 페이지의 파일 내용을 정규식으로 검색합니다. "
                    "특정 코드 패턴, 클래스명, 함수명 등을 빠르게 찾을 수 있습니다. "
                    "glob_filter로 파일 유형을 제한할 수 있습니다."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "검색할 정규식 패턴 (Python re 문법)",
                        },
                        "glob_filter": {
                            "type": "string",
                            "description": "파일 필터 (예: *.css, *.js)",
                        },
                        "case_insensitive": {
                            "type": "boolean",
                            "description": "대소문자 무시 여부 (기본: false)",
                        },
                        "context": {
                            "type": "integer",
                            "description": "매치 전후 표시할 라인 수 (기본: 0)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "최대 매치 수 (기본: 50)",
                        },
                    },
                    "required": ["pattern"],
                },
            },
        },
    ]


def get_page_management_tools() -> List[Dict[str, Any]]:
    """Return page management tools (always available, no file editing)."""
    return list(_MANAGEMENT_TOOLS)


def get_page_tools() -> List[Dict[str, Any]]:
    """Return page tools. Management tools always; file tools only when page active.
    Legacy — kept for backward compatibility.
    """
    tools = list(_MANAGEMENT_TOOLS)
    if page_manager.get_active_page():
        tools.extend(_get_active_page_tools())
    return tools


def get_page_system_prompt() -> Optional[str]:
    """Build system prompt for active page context."""
    active = page_manager.get_active_page()
    if not active:
        return None

    files = page_manager.list_page_files(active.id) or []
    file_list = "\n".join(f"  - {f}" for f in files) if files else "  (파일 없음)"

    return (
        f"## Active Page\n"
        f"- Name: {active.name}\n"
        f"- ID: {active.id}\n"
        f"- Type: {active.content_type}\n"
        f"- Description: {active.description}\n"
        f"- Files:\n{file_list}\n\n"
        f"파일 도구(read_file, write_file, edit_file, search, list_files)로 "
        f"웹 파일(HTML, CSS, JS 등)을 읽고, 쓰고, 편집할 수 있습니다. "
        f"대시보드, 커스텀 UI, 데이터 시각화 페이지 등을 구축하세요. "
        f"모든 파일 경로는 페이지 번들 루트 기준 상대 경로입니다.\n"
        f"페이지 수정 후 사용자는 /pages/viewer?id={active.id} 에서 결과를 확인할 수 있습니다."
    )


# --- Tool call handlers ---

async def handle_page_tool_call(tool_name: str, args: Dict[str, Any]) -> str:
    """Route page tool calls."""

    # --- Management tools (no active page required) ---

    if tool_name == "page_create_page":
        return _handle_create_page(args)

    if tool_name == "page_create_folder":
        return _handle_create_folder(args)

    if tool_name == "page_move":
        return _handle_move(args)

    # --- File tools (require active page) ---

    active = page_manager.get_active_page()
    if not active:
        return "Error: 활성 페이지가 없습니다. // 명령으로 페이지를 선택하세요."

    page_id = active.id

    if tool_name == "page_list_files":
        files = page_manager.list_page_files(page_id)
        if files is None:
            return "Error: 페이지를 찾을 수 없습니다."
        if not files:
            return "파일이 없습니다."
        return "\n".join(files)

    elif tool_name == "page_read_file":
        content = page_manager.read_page_file(page_id, args["file_path"])
        if content is None:
            return f"Error: 파일 '{args['file_path']}'을(를) 찾을 수 없습니다."
        return content

    elif tool_name == "page_write_file":
        file_path = args["file_path"]
        from pathlib import Path as P
        ext = P(file_path).suffix.lower()
        if ext not in _ALLOWED_EXTENSIONS:
            return f"Error: 허용되지 않는 확장자: {ext} (허용: {', '.join(sorted(_ALLOWED_EXTENSIONS))})"
        from pathlib import PurePosixPath
        if ".." in PurePosixPath(file_path).parts:
            return "Error: '..'은 허용되지 않습니다."

        page = page_manager.get_page(page_id)
        if page and page.content_type == "html":
            existing_files = page_manager.list_page_files(page_id) or []
            if file_path not in existing_files:
                page_manager.convert_to_bundle(page_id)

        result = page_manager.write_page_file(page_id, file_path, args["content"])
        if result is None:
            return f"Error: 파일 '{file_path}' 쓰기 실패."
        return f"파일 '{file_path}' 저장 완료."

    elif tool_name == "page_edit_file":
        return _handle_page_edit_file(page_id, args)

    elif tool_name == "page_grep":
        return _handle_page_grep(page_id, args)

    return f"Error: Unknown page tool '{tool_name}'"


def _handle_create_page(args: Dict[str, Any]) -> str:
    try:
        name = args["name"]
        description = args.get("description", "")
        content = args["content"]
        parent_id = args.get("parent_id")

        files = [("index.html", content.encode("utf-8"))]
        page = page_manager.add_bundle(name, description, files, parent_id=parent_id)

        # Auto-activate the new page
        page_manager.activate_page(page.id)
        folder_info = f", 폴더: {parent_id}" if parent_id else ""
        return f"페이지 '{name}' 생성 완료 (ID: {page.id}{folder_info}). 자동 활성화됨. 이제 write_file/edit_file로 파일을 추가·수정할 수 있습니다."
    except Exception as e:
        return f"Error: 페이지 생성 실패 — {e}"


def _handle_create_folder(args: Dict[str, Any]) -> str:
    try:
        name = args["name"]
        description = args.get("description", "")
        parent_id = args.get("parent_id")
        folder = page_manager.create_folder(name, description, parent_id)
        return f"폴더 '{name}' 생성 완료 (ID: {folder.id})."
    except Exception as e:
        return f"Error: 폴더 생성 실패 — {e}"


def _handle_move(args: Dict[str, Any]) -> str:
    page_id = args["page_id"]
    target_folder_id = args.get("target_folder_id")

    page = page_manager.get_page(page_id)
    if not page:
        return f"Error: 페이지 '{page_id}'을(를) 찾을 수 없습니다."

    # Validate target folder exists (if specified)
    if target_folder_id:
        target = page_manager.get_page(target_folder_id)
        if not target:
            return f"Error: 대상 폴더 '{target_folder_id}'을(를) 찾을 수 없습니다."
        if target.content_type != "folder":
            return f"Error: '{target.name}'은(는) 폴더가 아닙니다."
        # Prevent moving a folder into itself or its descendants
        if page.content_type == "folder":
            current = target_folder_id
            visited = set()
            while current and current not in visited:
                if current == page_id:
                    return "Error: 폴더를 자기 자신의 하위로 이동할 수 없습니다."
                visited.add(current)
                parent = page_manager.get_page(current)
                current = parent.parent_id if parent else None

    result = page_manager.update_page(page_id, parent_id=target_folder_id)
    if not result:
        return "Error: 이동 실패."

    dest_name = "루트" if not target_folder_id else page_manager.get_page(target_folder_id).name
    return f"'{page.name}'을(를) '{dest_name}'(으)로 이동 완료."


def _handle_page_edit_file(page_id: str, args: Dict[str, Any]) -> str:
    """Fuzzy find-replace on page file using Rust engine."""
    from open_agent.core.fuzzy import find_closest_match, fuzzy_find, fuzzy_replace

    file_path = args["file_path"]
    old_string = args["old_string"]
    new_string = args["new_string"]
    replace_all = args.get("replace_all", False)

    if not old_string:
        return "Error: old_string은 비어 있을 수 없습니다."

    content = page_manager.read_page_file(page_id, file_path)
    if content is None:
        return f"Error: 파일 '{file_path}'을(를) 찾을 수 없습니다."

    match_mode, pos, matched_len = fuzzy_find(content, old_string)

    if match_mode is None:
        line_count = len(content.splitlines())
        best_line, ratio, snippet = find_closest_match(content, old_string)
        msg = f"old_string을 '{file_path}'에서 찾을 수 없습니다 ({line_count}줄)."
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
                f"Error: old_string이 '{file_path}'에서 {count}번 발견되었습니다. "
                "replace_all=true로 모두 교체하거나, 더 고유한 문자열을 지정하세요."
            )
        if replace_all:
            new_content = content.replace(old_string, new_string)
        else:
            new_content = content.replace(old_string, new_string, 1)
        replaced = count if replace_all else 1
    else:
        new_content = fuzzy_replace(content, old_string, new_string, match_mode)
        replaced = 1

    result = page_manager.write_page_file(page_id, file_path, new_content)
    if result is None:
        return "Error: 파일 쓰기 실패."

    msg = f"파일 '{file_path}' 수정 완료: {replaced}건 교체"
    if match_mode != "exact":
        msg += f" ({match_mode} 매칭)"
    return msg


def _handle_page_grep(page_id: str, args: Dict[str, Any]) -> str:
    """Search page files by regex pattern."""
    pattern = args["pattern"]
    glob_filter = args.get("glob_filter")
    case_insensitive = args.get("case_insensitive", False)
    context_lines = args.get("context", 0)
    limit = args.get("limit", 50)

    flags = re.IGNORECASE if case_insensitive else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"

    files = page_manager.list_page_files(page_id)
    if files is None:
        return "Error: 페이지를 찾을 수 없습니다."
    if not files:
        return "파일이 없습니다."

    if glob_filter:
        files = [f for f in files if fnmatch.fnmatch(f, glob_filter)]
        if not files:
            return f"No files matching '{glob_filter}'"

    results: List[str] = []
    match_count = 0

    for file_path in sorted(files):
        content = page_manager.read_page_file(page_id, file_path)
        if content is None:
            continue

        file_lines = content.split("\n")
        file_matches: List[str] = []

        for i, line in enumerate(file_lines):
            if regex.search(line):
                start = max(0, i - context_lines)
                end = min(len(file_lines), i + context_lines + 1)
                for j in range(start, end):
                    marker = ">" if j == i else " "
                    file_matches.append(f"  {marker} {j + 1:>4}\t{file_lines[j]}")
                match_count += 1
                if match_count >= limit:
                    break

        if file_matches:
            results.append(f"\n{file_path}:")
            results.extend(file_matches)

        if match_count >= limit:
            break

    if not results:
        return f"No matches for pattern '{pattern}'"
    header = f"Found {match_count} match(es) for '{pattern}':"
    return header + "\n".join(results)
