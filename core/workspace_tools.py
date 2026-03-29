import asyncio
import fnmatch
import logging
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from open_agent.core.workspace_manager import workspace_manager, IGNORED_DIRS, IGNORED_FILES

logger = logging.getLogger(__name__)

# Windows 대소문자 무시를 위한 소문자 변환 집합
IGNORED_DIRS_LOWER = {d.lower() for d in IGNORED_DIRS}

WORKSPACE_TOOL_NAMES = {
    "workspace_read_file",
    "workspace_write_file",
    "workspace_edit_file",
    "workspace_apply_patch",
    "workspace_rename",
    "workspace_list_dir",
    "workspace_glob",
    "workspace_grep",
    "workspace_bash",
}

# bash 안전장치: 시스템 파괴 명령 패턴 (절대 실행 금지)
DANGEROUS_PATTERNS = [
    r"rm\s+-[^\s]*r[^\s]*f\s+/",  # rm -rf /
    r"rm\s+-[^\s]*f[^\s]*r\s+/",  # rm -fr /
    r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;",  # fork bomb
    r"dd\s+if=/dev/(zero|random|urandom)\s+of=/dev/[hs]d",  # dd overwrite disk
    r"mkfs\.",  # format filesystem
    r">\s*/dev/[hs]d",  # overwrite disk
    r"curl\s+.*\|\s*(ba)?sh",  # pipe-to-shell
    r"wget\s+.*\|\s*(ba)?sh",  # pipe-to-shell
    r"chmod\s+-R\s+777\s+/",  # chmod 777 /
    r"chown\s+-R\s+.*\s+/",  # chown /
    # Windows 전용 위험 패턴
    r"(?i)del\s+/[sS]\s+/[qQ]\s+[A-Za-z]:\\",  # del /s /q C:\
    r"(?i)format\s+[A-Za-z]:",  # format C:
    r"(?i)diskpart",  # 디스크 파티션 조작
    r"(?i)cipher\s+/[wW]:",  # 보안 와이프
    r"(?i)reg\s+delete\s+HK(LM|CU|CR)",  # 레지스트리 삭제
    r"(?i)Remove-Item\s+-Recurse\s+-Force\s+[A-Za-z]:\\",  # PowerShell rm -rf
    r"(?i)Clear-Disk",  # PowerShell 디스크 초기화
    r"(?i)Format-Volume",  # PowerShell 볼륨 포맷
    # 시스템 스케줄러 명령 차단 (Open Agent Jobs 사용 유도)
    r"\bcrontab\b",  # crontab 등록/수정/삭제
    r"\blaunchctl\b",  # macOS 서비스 등록/제거
    r"\bat\s+",  # at 명령 (일회성 예약)
    r"(?i)\bschtasks\b",  # Windows 작업 스케줄러 (CMD)
    r"(?i)Register-ScheduledTask",  # Windows 작업 스케줄러 (PowerShell)
    r"(?i)Set-ScheduledTask",  # Windows 작업 스케줄러 수정 (PowerShell)
    r"(?i)New-ScheduledTaskTrigger",  # Windows 작업 트리거 생성 (PowerShell)
    r"(?i)\bsc\s+create\b",  # Windows 서비스 등록
    r"\bsystemctl\s+(enable|start|restart)\b",  # Linux 서비스 등록/시작
]

# 서브프로세스에서 제거할 민감 환경변수 키
_SENSITIVE_ENV_KEYS = {
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "OPENROUTER_API_KEY",
    "GROQ_API_KEY",
    "DEEPSEEK_API_KEY",
    "MISTRAL_API_KEY",
    "COHERE_API_KEY",
    "TOGETHERAI_API_KEY",
    "PERPLEXITYAI_API_KEY",
    "FIREWORKS_AI_API_KEY",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AZURE_API_KEY",
    "HF_TOKEN",
    "HUGGINGFACE_TOKEN",
}


_SENSITIVE_ENV_PATTERNS = ("_KEY", "_SECRET", "_TOKEN", "_PASSWORD", "_CREDENTIAL")


def get_sanitized_env() -> Dict[str, str]:
    """현재 환경변수에서 민감 키를 제거한 사본 반환"""
    def _is_sensitive(key: str) -> bool:
        if key in _SENSITIVE_ENV_KEYS:
            return True
        upper = key.upper()
        return any(upper.endswith(p) for p in _SENSITIVE_ENV_PATTERNS)
    return {k: v for k, v in os.environ.items() if not _is_sensitive(k)}


# bash 안전장치: 제한된 작업 패턴 (파일 삭제, 이동 등 파괴적 작업)
RESTRICTED_PATTERNS = [
    (r"\brm\b", "파일 삭제(rm)"),
    (r"\brmdir\b", "디렉토리 삭제(rmdir)"),
    (r"\bunlink\b", "파일 삭제(unlink)"),
    (r"\bshred\b", "파일 완전 삭제(shred)"),
    (r"\bmv\b", "파일 이동/이름변경(mv)"),
    (r"\btrash\b", "파일 휴지통 이동(trash)"),
    (r"\bgit\s+clean\b", "git 파일 정리(git clean)"),
    (r"\bgit\s+reset\s+--hard\b", "git 강제 리셋(git reset --hard)"),
    # Windows 전용 제한 패턴
    (r"(?i)\bdel\b", "파일 삭제(del)"),
    (r"(?i)\berase\b", "파일 삭제(erase)"),
    (r"(?i)\bmove\b", "파일 이동(move)"),
    (r"(?i)Remove-Item", "파일 삭제(Remove-Item)"),
    (r"(?i)Move-Item", "파일 이동(Move-Item)"),
    (r"(?<!\w)env(?:\s|$)", "환경변수 조회(env)"),
    (r"\bprintenv\b", "환경변수 조회(printenv)"),
    (r"(?<!\w)set(?:\s|$)", "환경변수 조회(set)"),
]


def _is_dangerous_command(command: str) -> Optional[str]:
    """시스템 파괴 명령 검사"""
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command):
            return f"Blocked: dangerous command pattern detected ({pattern})"
    return None


def _is_restricted_command(command: str) -> Optional[str]:
    """제한된 작업 검사 — 명확한 한글 메시지 반환"""
    for pattern, desc in RESTRICTED_PATTERNS:
        if re.search(pattern, command):
            return (
                f"🚫 보안상 실행할 수 없습니다.\n\n"
                f"차단된 작업: {desc}\n"
                f"요청한 명령: {command}\n\n"
                f"워크스페이스에서는 파일 삭제, 이동 등 파괴적인 작업이 제한됩니다. "
                f"파일 읽기, 쓰기, 편집, 검색 작업만 가능합니다."
            )
    return None


def _detect_sensitive_env_access(command: str) -> Optional[str]:
    """명령어에서 민감 환경변수 참조를 감지하여 안내 메시지 반환"""
    referenced = []
    for key in _SENSITIVE_ENV_KEYS:
        # $KEY, ${KEY}, %KEY% (Windows) 패턴 감지
        if re.search(rf'\$\{{?{key}\}}?|%{key}%', command):
            referenced.append(key)
    if referenced:
        keys_str = ", ".join(referenced)
        return (
            f"\n[sandbox] 보안 안내: 이 명령은 보호된 환경변수({keys_str})를 참조했습니다. "
            f"민감한 환경변수는 샌드박스 보안 정책에 의해 서브프로세스에서 자동 제거되어 값이 비어 있습니다."
        )
    return None


def get_workspace_extra_tools() -> List[Dict[str, Any]]:
    """Return workspace-only tools not covered by unified tools (rename, glob)."""
    active = workspace_manager.get_active()
    if not active:
        return []
    return [
        {
            "type": "function",
            "function": {
                "name": "workspace_rename",
                "description": (
                    "워크스페이스의 파일이나 디렉토리 이름을 변경하거나 이동합니다. "
                    "old_path에서 new_path로 이동하며, 상위 디렉토리가 없으면 자동 생성됩니다."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "old_path": {"type": "string", "description": "현재 파일/디렉토리 경로"},
                        "new_path": {"type": "string", "description": "새 파일/디렉토리 경로"},
                    },
                    "required": ["old_path", "new_path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workspace_glob",
                "description": (
                    "워크스페이스에서 glob 패턴으로 파일을 검색하여 경로 목록을 반환합니다. "
                    "** 패턴으로 재귀 검색이 가능합니다 (예: **/*.py, src/**/*.ts)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "glob 패턴 (예: **/*.py)"},
                        "limit": {"type": "integer", "description": "최대 결과 수 (기본: 100)", "default": 100},
                    },
                    "required": ["pattern"],
                },
            },
        },
    ]


def get_workspace_tools() -> List[Dict[str, Any]]:
    """활성 워크스페이스가 있을 때만 도구 목록 반환 (legacy — backward compat)"""
    active = workspace_manager.get_active()
    if not active:
        return []

    return [
        {
            "type": "function",
            "function": {
                "name": "workspace_read_file",
                "description": (
                    "워크스페이스의 파일 내용을 읽어 라인 번호가 포함된 텍스트로 반환합니다. "
                    "대용량 파일은 offset/limit으로 범위를 지정하여 부분 읽기가 가능합니다. "
                    "바이너리 파일(.png, .pdf 등)은 읽을 수 없으며, 텍스트 파일만 지원합니다."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "워크스페이스 루트 기준 상대 경로 (예: src/main.py)"},
                        "offset": {"type": "integer", "description": "읽기 시작 라인 번호 (0-based, 기본: 0)", "default": 0},
                        "limit": {"type": "integer", "description": "읽을 라인 수 (생략 시 전체 파일)"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workspace_write_file",
                "description": (
                    "워크스페이스에 새 파일을 생성하거나 기존 파일을 덮어씁니다. "
                    "상위 디렉토리가 없으면 자동 생성됩니다. "
                    "기존 파일의 일부만 수정하려면 workspace_edit_file을 사용하세요 — write_file은 전체 덮어쓰기입니다."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "워크스페이스 루트 기준 상대 경로 (예: src/utils.py)"},
                        "content": {"type": "string", "description": "파일에 쓸 전체 내용"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workspace_edit_file",
                "description": (
                    "파일 내용에서 특정 문자열(old_string)을 찾아 새 문자열(new_string)로 교체합니다. "
                    "4-pass fuzzy matching으로 공백 차이, 들여쓰기 차이, 유니코드(스마트 따옴표) 차이도 자동 처리합니다. "
                    "매칭 실패 시 가장 유사한 코드 블록과 유사도를 힌트로 제공합니다. "
                    "old_string이 파일 내에서 유일해야 하며, 여러 곳에 존재하면 replace_all=true를 명시해야 합니다. "
                    "빈 old_string은 거부됩니다. 전체 파일을 교체하려면 workspace_write_file을 사용하세요."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "워크스페이스 루트 기준 상대 경로"},
                        "old_string": {"type": "string", "description": "교체할 기존 문자열 (파일 내 유일해야 함, 또는 replace_all 사용)"},
                        "new_string": {"type": "string", "description": "교체될 새 문자열"},
                        "replace_all": {"type": "boolean", "description": "true: 모든 매치를 교체, false(기본): 유일 매치만 교체", "default": False},
                    },
                    "required": ["path", "old_string", "new_string"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workspace_apply_patch",
                "description": (
                    "unified diff 형식의 패치를 워크스페이스 파일에 적용합니다. "
                    "한 번의 호출로 여러 파일을 동시에 수정할 수 있어 대규모 리팩토링에 적합합니다. "
                    "패치 형식: '--- a/path\\n+++ b/path\\n@@ -start,count +start,count @@\\n context/-removed/+added'. "
                    "컨텍스트 라인이 실제 파일과 불일치하면 해당 hunk가 거부됩니다."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patch": {
                            "type": "string",
                            "description": "unified diff 형식의 패치 텍스트 (여러 파일 포함 가능)",
                        },
                    },
                    "required": ["patch"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workspace_rename",
                "description": (
                    "워크스페이스의 파일이나 디렉토리 이름을 변경하거나 이동합니다. "
                    "old_path에서 new_path로 이동하며, 상위 디렉토리가 없으면 자동 생성됩니다. "
                    "경로는 워크스페이스 루트 기준 상대 경로입니다."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "old_path": {"type": "string", "description": "현재 파일/디렉토리 경로 (워크스페이스 루트 기준 상대 경로)"},
                        "new_path": {"type": "string", "description": "새 파일/디렉토리 경로 (워크스페이스 루트 기준 상대 경로)"},
                    },
                    "required": ["old_path", "new_path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workspace_list_dir",
                "description": (
                    "워크스페이스의 디렉토리 구조를 트리 형태로 반환합니다. "
                    "recursive=true로 하위 디렉토리까지 탐색할 수 있으며, max_depth로 깊이를 제한합니다. "
                    ".git, node_modules, __pycache__ 등은 자동 제외됩니다. "
                    "프로젝트 구조를 파악할 때 먼저 호출하세요."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "탐색 시작 경로 (워크스페이스 루트 기준 상대 경로, 기본: 루트)", "default": "."},
                        "recursive": {"type": "boolean", "description": "하위 디렉토리 재귀 탐색 여부 (기본: false)", "default": False},
                        "max_depth": {"type": "integer", "description": "재귀 탐색 시 최대 깊이 (기본: 3)", "default": 3},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workspace_glob",
                "description": (
                    "워크스페이스에서 glob 패턴으로 파일을 검색하여 상대 경로 목록을 반환합니다. "
                    "** 패턴으로 재귀 검색이 가능합니다 (예: **/*.py, src/**/*.ts). "
                    ".git, node_modules 등 무시 디렉토리는 자동 제외됩니다. 결과가 많으면 limit으로 제한하세요."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "glob 패턴 (예: **/*.py, src/**/*.ts, *.json)"},
                        "limit": {"type": "integer", "description": "최대 결과 수 (기본: 100)", "default": 100},
                    },
                    "required": ["pattern"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workspace_grep",
                "description": (
                    "워크스페이스의 파일 내용을 정규식(regex)으로 검색하여 매칭 라인과 파일 경로를 반환합니다. "
                    "glob_filter로 특정 파일 유형만 검색할 수 있습니다 (예: *.py). "
                    "context 파라미터로 매치 전후 라인을 함께 표시할 수 있습니다. "
                    ".git, node_modules 등 무시 디렉토리는 자동 제외됩니다."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "검색할 정규식 패턴 (Python re 문법)"},
                        "path": {"type": "string", "description": "검색 시작 경로 (워크스페이스 루트 기준 상대 경로, 기본: 루트)", "default": "."},
                        "glob_filter": {"type": "string", "description": "파일 필터 glob 패턴 (예: *.py, *.ts)"},
                        "case_insensitive": {"type": "boolean", "description": "대소문자 무시 여부 (기본: false)", "default": False},
                        "context": {"type": "integer", "description": "매치 전후로 표시할 컨텍스트 라인 수 (기본: 0)", "default": 0},
                        "limit": {"type": "integer", "description": "최대 매치 수 (기본: 50)", "default": 50},
                    },
                    "required": ["pattern"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workspace_bash",
                "description": (
                    "활성 워크스페이스의 프로젝트 컨텍스트에서 셸 명령을 실행합니다. "
                    "빌드, 테스트, 린트, 의존성 설치, git 명령, 코드 실행 등 프로젝트 개발 작업에 사용하세요. "
                    "보안상 파일 삭제(rm), 이동(mv) 등 파괴적 명령은 차단됩니다. "
                    "타임아웃은 기본 30초, 최대 120초이며, stdout은 30,000자에서 절삭됩니다."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "실행할 셸 명령어"},
                        "cwd": {"type": "string", "description": "작업 디렉토리 (워크스페이스 루트 기준 상대 경로, 생략 시 루트)"},
                        "timeout": {"type": "integer", "description": "타임아웃 초 (기본: 30, 최대: 120)", "default": 30},
                    },
                    "required": ["command"],
                },
            },
        },
    ]


def get_workspace_system_prompt() -> Optional[str]:
    """활성 워크스페이스 정보를 시스템 프롬프트로"""
    active = workspace_manager.get_active()
    if not active:
        return None

    return (
        f"## Active Workspace\n"
        f"- Name: {active.name}\n"
        f"- Path: {active.path}\n"
        f"- Description: {active.description}\n\n"
        f"파일 도구(read_file, write_file, edit_file, search, list_files, apply_patch, bash)로 "
        f"코드 읽기/쓰기/편집, 프로젝트 구조 탐색, 빌드/테스트/린트 실행을 수행하세요. "
        f"모든 파일 경로는 워크스페이스 루트 기준 상대 경로입니다.\n"
        f"**스킬 스크립트에 워크스페이스 파일을 전달할 때는 반드시 절대 경로를 사용하세요.** "
        f"절대 경로 = Workspace Path + 상대 경로 (예: {active.path}/파일명)\n\n"
        f"## Workspace Security Rules\n"
        f"bash에서는 파괴적 명령(rm, mv, mkfs 등)이 자동으로 차단됩니다.\n"
        f"**파일 삭제는 지원하지 않습니다.** 사용자가 파일 삭제를 요청하면 "
        f"워크스페이스에서는 파일 삭제가 지원되지 않는다고 안내하세요. "
        f"write_file로 내용을 비우는 것은 삭제가 아니므로 절대 하지 마세요."
    )


async def handle_workspace_tool_call(name: str, args: Dict[str, Any]) -> "str | Dict[str, Any]":
    active = workspace_manager.get_active()
    if not active:
        return "Error: No active workspace. Please activate a workspace first."

    try:
        if name == "workspace_read_file":
            return _handle_read_file(active.id, args)
        elif name == "workspace_write_file":
            return _handle_write_file(active.id, args)
        elif name == "workspace_edit_file":
            return _handle_edit_file(active.id, args)
        elif name == "workspace_apply_patch":
            return _handle_apply_patch(active.id, args)
        elif name == "workspace_rename":
            return _handle_rename(active.id, args)
        elif name == "workspace_list_dir":
            return _handle_list_dir(active.id, args)
        elif name == "workspace_glob":
            return _handle_glob(active.id, args)
        elif name == "workspace_grep":
            return _handle_grep(active.id, args)
        elif name == "workspace_bash":
            return await _handle_bash(active.id, args)
        else:
            return f"Error: Unknown workspace tool '{name}'"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.error(f"Workspace tool error ({name}): {e}")
        return f"Error: {e}"


def _handle_read_file(ws_id: str, args: Dict[str, Any]) -> str:
    fc = workspace_manager.read_file(
        ws_id,
        args["path"],
        offset=args.get("offset", 0),
        limit=args.get("limit"),
    )
    lines = fc.content.split("\n")
    offset = fc.offset
    numbered = "\n".join(
        f"{offset + i + 1:>6}\t{line}" for i, line in enumerate(lines)
    )
    header = f"File: {fc.path} ({fc.total_lines} lines total)"
    if fc.offset > 0 or fc.limit:
        header += f" [showing lines {fc.offset + 1}-{fc.offset + len(lines)}]"
    return f"{header}\n{numbered}"


def _handle_write_file(ws_id: str, args: Dict[str, Any]) -> str:
    return workspace_manager.write_file(ws_id, args["path"], args["content"])


def _handle_edit_file(ws_id: str, args: Dict[str, Any]) -> str:
    from open_agent.models.workspace import EditFileRequest
    req = EditFileRequest(
        path=args["path"],
        old_string=args["old_string"],
        new_string=args["new_string"],
        replace_all=args.get("replace_all", False),
    )
    return workspace_manager.edit_file(ws_id, req)


def _handle_apply_patch(ws_id: str, args: Dict[str, Any]) -> str:
    from open_agent.core.fuzzy import apply_patch_to_files

    ws = workspace_manager.get_workspace(ws_id)
    if not ws:
        return "Error: Workspace not found"

    root = Path(ws.path).resolve()
    patch_text = args.get("patch", "")
    if not patch_text.strip():
        return "Error: patch text is empty"

    def path_validator(rel_path: str) -> Path:
        return workspace_manager._resolve_safe_path(ws_id, rel_path)

    return apply_patch_to_files(patch_text, str(root), path_validator=path_validator)


def _handle_rename(ws_id: str, args: Dict[str, Any]) -> str:
    return workspace_manager.rename_file(ws_id, args["old_path"], args["new_path"])


def _handle_list_dir(ws_id: str, args: Dict[str, Any]) -> str:
    path = args.get("path", ".")
    recursive = args.get("recursive", False)
    max_depth = args.get("max_depth", 3) if recursive else 1

    nodes = workspace_manager.get_file_tree(ws_id, path, max_depth)
    lines: List[str] = []
    _format_tree(nodes, lines, "")

    if not lines:
        return f"Directory '{path}' is empty."
    return "\n".join(lines)


def _format_tree(nodes: List[Any], lines: List[str], prefix: str) -> None:
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


def _handle_glob(ws_id: str, args: Dict[str, Any]) -> str:
    pattern = args["pattern"]
    limit = args.get("limit", 100)
    ws = workspace_manager.get_workspace(ws_id)
    if not ws:
        return "Error: Workspace not found"

    root = Path(ws.path)
    matches: List[str] = []
    for p in root.rglob(pattern):
        if any(part.lower() in IGNORED_DIRS_LOWER for part in p.relative_to(root).parts):
            continue
        if p.name in IGNORED_FILES:
            continue
        rel = p.relative_to(root).as_posix()
        matches.append(rel)
        if len(matches) >= limit:
            break

    if not matches:
        return f"No files matching '{pattern}'"
    result = f"Found {len(matches)} file(s) matching '{pattern}':\n"
    result += "\n".join(matches)
    return result


def _handle_grep(ws_id: str, args: Dict[str, Any]) -> str:
    pattern = args["pattern"]
    search_path = args.get("path", ".")
    glob_filter = args.get("glob_filter")
    case_insensitive = args.get("case_insensitive", False)
    context_lines = args.get("context", 0)
    limit = args.get("limit", 50)

    ws = workspace_manager.get_workspace(ws_id)
    if not ws:
        return "Error: Workspace not found"

    root = Path(ws.path).resolve()
    target = (root / search_path).resolve()
    if not target.is_relative_to(root):
        return "Error: Path traversal detected"

    # Tier 1: Native Rust grep (fastest — in-process, no subprocess)
    try:
        import nexus_rust
        logger.debug("workspace_grep: using native Rust backend")
        return _handle_grep_rust(
            nexus_rust, root, target, pattern, glob_filter,
            case_insensitive, context_lines, limit,
        )
    except ImportError:
        pass
    except Exception as e:
        logger.warning("workspace_grep: Rust grep failed (%s), falling back", e)

    # Tier 2: ripgrep subprocess (10-100x faster than Python re)
    rg_path = shutil.which("rg")
    if rg_path:
        logger.debug("workspace_grep: using ripgrep subprocess backend")
        return _handle_grep_rg(
            rg_path, root, target, pattern, glob_filter,
            case_insensitive, context_lines, limit,
        )

    # Tier 3: Pure Python grep fallback
    logger.debug("workspace_grep: using Python re backend")
    return _handle_grep_python(
        root, target, pattern, glob_filter,
        case_insensitive, context_lines, limit,
    )


def _handle_grep_rust(
    nexus_rust, root: Path, target: Path, pattern: str,
    glob_filter: Optional[str], case_insensitive: bool,
    context_lines: int, limit: int,
) -> str:
    """Native Rust grep via nexus_rust module (fastest)."""
    matches = nexus_rust.rust_grep(
        pattern,
        str(target),
        glob_filter,
        context_lines,
        limit,
        case_insensitive,
    )

    if not matches:
        return f"No matches for pattern '{pattern}'"

    # Format output similar to ripgrep style
    lines: List[str] = []
    root_str = str(root)
    prev_path = None

    for m in matches:
        # Make path relative to workspace root
        rel_path = m["path"]
        if rel_path.startswith(root_str):
            rel_path = rel_path[len(root_str):].lstrip("/")

        if context_lines > 0:
            if prev_path is not None and prev_path != rel_path:
                lines.append("--")
            elif prev_path == rel_path and lines:
                lines.append("--")

            for ctx_line in m["context_before"]:
                lines.append(f"{rel_path}-{ctx_line}")
            lines.append(f"{rel_path}:{m['line_number']}:{m['line_content']}")
            for ctx_line in m["context_after"]:
                lines.append(f"{rel_path}-{ctx_line}")
        else:
            lines.append(f"{rel_path}:{m['line_number']}:{m['line_content']}")

        prev_path = rel_path

    match_count = len(matches)
    header = f"Found {min(match_count, limit)} match(es) for '{pattern}':\n"
    output = "\n".join(lines)
    if len(output) > 100000:
        output = output[:100000] + "\n... (output truncated)"
    return header + output


def _handle_grep_rg(
    rg_path: str, root: Path, target: Path, pattern: str,
    glob_filter: Optional[str], case_insensitive: bool,
    context_lines: int, limit: int,
) -> str:
    """ripgrep subprocess-based grep (10-100x faster)."""
    import subprocess

    cmd = [rg_path, "--no-heading", "--line-number", "--color=never"]
    if case_insensitive:
        cmd.append("-i")
    if context_lines > 0:
        cmd.extend(["-C", str(context_lines)])
    if glob_filter:
        cmd.extend(["--glob", glob_filter])
    # Exclude ignored directories
    for d in IGNORED_DIRS:
        cmd.extend(["--glob", f"!{d}/"])
    cmd.extend(["--max-count", str(limit)])
    cmd.append(pattern)
    cmd.append(str(target))

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(root),
            env=get_sanitized_env(),
        )
    except subprocess.TimeoutExpired:
        return "Error: grep timed out after 30s"
    except Exception as e:
        return f"Error: ripgrep failed: {e}"

    if proc.returncode == 1:
        return f"No matches for pattern '{pattern}'"
    if proc.returncode > 1:
        return f"Error: ripgrep error: {proc.stderr[:500]}"

    output = proc.stdout

    # 전역 limit 적용 (rg --max-count는 파일당이므로 후처리 필요)
    lines = output.splitlines()
    match_lines = [l for l in lines if l and not l.startswith("--")]
    if len(match_lines) > limit:
        # limit까지만 잘라서 재구성
        kept = 0
        trimmed = []
        for l in lines:
            if l and not l.startswith("--"):
                kept += 1
                if kept > limit:
                    break
            trimmed.append(l)
        output = "\n".join(trimmed)

    if len(output) > 100000:
        output = output[:100000] + "\n... (output truncated)"

    # Convert absolute paths to relative paths
    root_str = str(root) + "/"
    output = output.replace(root_str, "")

    # Count matches
    match_count = sum(1 for line in output.splitlines() if line and not line.startswith("--"))
    header = f"Found {min(match_count, limit)} match(es) for '{pattern}':\n"
    return header + output


def _handle_grep_python(
    root: Path, target: Path, pattern: str,
    glob_filter: Optional[str], case_insensitive: bool,
    context_lines: int, limit: int,
) -> str:
    """Pure Python grep fallback."""
    if len(pattern) > 1000:
        return "Error: Regex pattern too long (max 1000 characters)"
    flags = re.IGNORECASE if case_insensitive else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"

    results: List[str] = []
    match_count = 0

    if target.is_file():
        files = [target]
    else:
        files_iter = target.rglob("*") if not glob_filter else target.rglob(glob_filter)
        files = []
        for f in files_iter:
            if not f.is_file():
                continue
            if any(part.lower() in IGNORED_DIRS_LOWER for part in f.relative_to(root).parts):
                continue
            if f.name in IGNORED_FILES:
                continue
            files.append(f)

    for file_path in sorted(files):
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            continue

        file_lines = content.split("\n")
        file_matches: List[str] = []

        for i, line in enumerate(file_lines):
            if regex.search(line):
                rel = file_path.relative_to(root).as_posix()
                start = max(0, i - context_lines)
                end = min(len(file_lines), i + context_lines + 1)
                for j in range(start, end):
                    marker = ">" if j == i else " "
                    file_matches.append(f"  {marker} {j + 1:>4}\t{file_lines[j]}")
                match_count += 1
                if match_count >= limit:
                    break

        if file_matches:
            rel = file_path.relative_to(root).as_posix()
            results.append(f"\n{rel}:")
            results.extend(file_matches)

        if match_count >= limit:
            break

    if not results:
        return f"No matches for pattern '{pattern}'"
    header = f"Found {match_count} match(es) for '{pattern}':"
    return header + "\n".join(results)


async def _handle_bash(ws_id: str, args: Dict[str, Any]) -> "str | Dict[str, Any]":
    command = args["command"]
    cwd_rel = args.get("cwd")
    timeout = min(args.get("timeout", 30), 120)

    # Layer 0: 정규식 패턴 차단 (기존 유지 — 빠른 1차 방어)
    danger = _is_dangerous_command(command)
    if danger:
        return danger

    restricted = _is_restricted_command(command)
    if restricted:
        return restricted

    ws = workspace_manager.get_workspace(ws_id)
    if not ws:
        return "Error: Workspace not found"

    root = Path(ws.path).resolve()

    if cwd_rel:
        cwd = (root / cwd_rel).resolve()
        if not cwd.is_relative_to(root):
            return "Error: cwd must be within workspace"
        if not cwd.is_dir():
            return f"Error: Directory not found: {cwd_rel}"
    else:
        cwd = root

    # 네트워크 차단 감지 헬퍼
    _NETWORK_KEYWORDS = ["network", "resolve", "connect", "eperm", "npm error", "pip", "fetch", "econnrefused", "etimedout", "enetunreach"]
    _NETWORK_COMMANDS = re.compile(
        r"\b(npm\s+install|npm\s+i\b|yarn\s+add|yarn\s+install|pnpm\s+add|pnpm\s+install|"
        r"pip\s+install|pip3\s+install|uv\s+pip\s+install|"
        r"cargo\s+add|cargo\s+install|go\s+get|gem\s+install|"
        r"curl\b|wget\b|git\s+clone|git\s+fetch|git\s+pull|git\s+push)",
        re.IGNORECASE,
    )

    def _is_network_blocked(violation_text: str, stderr_text: str) -> bool:
        combined = (violation_text + " " + stderr_text).lower()
        return any(kw in combined for kw in _NETWORK_KEYWORDS)

    def _is_network_command(cmd: str) -> bool:
        return bool(_NETWORK_COMMANDS.search(cmd))

    # Layer 1: OS 네이티브 샌드박스 (커널 레벨 격리)
    from open_agent.core.sandbox import sandbox_manager, SandboxPolicy

    def _try_escalation(violation: str, stderr_preview: str) -> "Dict[str, Any] | None":
        escalation = sandbox_manager.request_escalation(SandboxPolicy.NETWORK_ALLOWED)
        if escalation.get("needed"):
            return {
                "__escalation__": True,
                "command": command,
                "cwd": str(cwd),
                "workspace_id": ws_id,
                "timeout": max(timeout, 120),  # 네트워크 명령은 더 긴 타임아웃
                "violation": violation,
                "stderr_preview": stderr_preview,
                "escalation": escalation,
            }
        return None

    # Pre-flight: 네트워크 명령이면 실행 전에 즉시 에스컬레이션 요청 (30초 낭비 방지)
    if _is_network_command(command):
        esc = _try_escalation("network_required", f"네트워크가 필요한 명령: {command}")
        if esc:
            return esc

    try:
        result = await sandbox_manager.execute(
            command=command,
            cwd=str(cwd),
            workspace_root=str(root),
            timeout=timeout,
        )
    except Exception as e:
        return f"Error executing command: {e}"

    stderr_text_raw = result.get("stderr", "")[:500]

    # 타임아웃 시: stderr 키워드 또는 명령어 패턴으로 네트워크 차단 감지
    if result.get("timed_out"):
        if _is_network_blocked("", stderr_text_raw) or _is_network_command(command):
            esc = _try_escalation("network_timeout", stderr_text_raw or f"timed out: {command}")
            if esc:
                return esc
        return f"Error: Command timed out after {timeout}s"

    # sandbox_violation이 설정된 경우
    violation = result.get("sandbox_violation")
    if violation:
        if _is_network_blocked(violation, stderr_text_raw):
            esc = _try_escalation(violation, stderr_text_raw)
            if esc:
                return esc
        return (
            f"[sandbox] 보안 정책에 의해 작업이 제한되었습니다: {violation}\n"
            f"stderr: {stderr_text_raw}\n\n"
            f"네트워크 접근이나 추가 권한이 필요하면 알려주세요."
        )

    # sandbox_violation 없지만 stderr에 네트워크 차단 패턴이 있는 경우 (npm EPERM 등)
    exit_code = result.get("exit_code", 0)
    if exit_code != 0 and _is_network_blocked("", stderr_text_raw):
        esc = _try_escalation("network_blocked", stderr_text_raw)
        if esc:
            return esc

    # Format output
    output_parts: List[str] = []
    stdout_text = result.get("stdout", "")
    stderr_text = result.get("stderr", "")

    if stdout_text:
        if len(stdout_text) > 100000:
            stdout_text = stdout_text[:100000] + "\n... (output truncated at 100000 chars)"
        output_parts.append(stdout_text)

    if stderr_text:
        if len(stderr_text) > 5000:
            stderr_text = stderr_text[:5000] + "\n... (stderr truncated)"
        output_parts.append(f"[stderr]\n{stderr_text}")

    output = "\n".join(output_parts) if output_parts else "(no output)"
    exit_info = f"[exit code: {result.get('exit_code', -1)}]"

    # 민감 환경변수 참조 감지 → 안내 메시지 추가
    env_note = _detect_sensitive_env_access(command)
    if env_note:
        return f"{output}\n{exit_info}{env_note}"

    return f"{output}\n{exit_info}"
