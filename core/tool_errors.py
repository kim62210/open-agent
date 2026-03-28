"""도구 호출 에러 분류 및 LLM 복구 컨텍스트 생성 엔진."""

import re
from dataclasses import dataclass

# 에러 패턴 테이블: (regex, error_type, recovery_hint)
_ERROR_PATTERNS: list[tuple[str, str, str]] = [
    (
        r"No module named ['\"]?(\S+)['\"]?",
        "module_not_found",
        "해당 모듈이 설치되어 있지 않습니다. 표준 라이브러리 대안을 사용하거나, 워크스페이스 내에서 uv/pip으로 설치하세요.",
    ),
    (
        r"command not found|No such command",
        "command_not_found",
        "해당 명령어가 시스템에 없습니다. PATH 확인 또는 대체 명령어를 시도하세요.",
    ),
    (
        r"No such file or directory|FileNotFoundError",
        "file_not_found",
        "파일/디렉토리가 존재하지 않습니다. list_files로 실제 경로를 확인하세요.",
    ),
    (
        r"Permission denied|PermissionError",
        "permission_denied",
        "권한이 부족합니다. 파일 권한을 확인하거나 다른 경로를 사용하세요.",
    ),
    (
        r"timed?\s*out|TimeoutError",
        "timeout",
        "작업이 시간 초과되었습니다. 작업을 더 작은 단위로 분할하거나 타임아웃을 늘려보세요.",
    ),
    (
        r"Server .* is not connected|not connected",
        "server_disconnected",
        "MCP 서버에 연결되어 있지 않습니다. 다른 도구를 사용하거나 사용자에게 서버 상태 확인을 요청하세요.",
    ),
    (
        r"externally[- ]managed[- ]environment",
        "env_restricted",
        "시스템 Python 환경은 직접 패키지 설치가 차단됩니다. uv 또는 pipx를 사용하세요.",
    ),
    (
        r"SyntaxError|IndentationError",
        "syntax_error",
        "코드에 문법 오류가 있습니다. 들여쓰기와 구문을 다시 확인하세요.",
    ),
    (
        r"Invalid tool name|Unknown .* tool",
        "invalid_tool",
        "존재하지 않는 도구입니다. 사용 가능한 도구 목록을 확인하세요.",
    ),
    (
        r"SSL|CERTIFICATE|certificate verify failed",
        "ssl_error",
        "SSL/인증서 오류입니다. REQUESTS_CA_BUNDLE 환경변수 설정 또는 certifi 패키지 사용을 고려하세요.",
    ),
]


@dataclass
class ToolError:
    error_type: str
    message: str
    recovery_hint: str


def classify_error(error_str: str) -> ToolError:
    """에러 문자열을 분석하여 유형과 복구 힌트를 반환합니다."""
    for pattern, error_type, hint in _ERROR_PATTERNS:
        if re.search(pattern, error_str, re.IGNORECASE):
            return ToolError(error_type=error_type, message=error_str, recovery_hint=hint)
    return ToolError(
        error_type="unknown",
        message=error_str,
        recovery_hint="이전과 다른 접근 방식을 시도하세요.",
    )


def format_error_for_llm(error_str: str) -> str:
    """에러 문자열을 LLM이 이해하기 쉬운 구조화된 형식으로 변환합니다."""
    err = classify_error(error_str)
    return (
        f"[TOOL_ERROR]\n"
        f"type: {err.error_type}\n"
        f"message: {err.message}\n"
        f"recovery_hint: {err.recovery_hint}"
    )


def is_error_result(result: str) -> bool:
    """도구 결과가 에러인지 판별합니다."""
    if not result:
        return False
    prefixes = ("Error:", "[TOOL_ERROR]", "Blocked:")
    return any(result.startswith(p) for p in prefixes)
