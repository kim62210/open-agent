"""Open Agent 커스텀 예외 계층."""


class OpenAgentError(Exception):
    """Base class for all Open Agent exceptions."""


# -- 리소스 접근 --
class NotFoundError(OpenAgentError):
    """리소스 없음 -> 404"""


class AlreadyExistsError(OpenAgentError):
    """리소스 중복 -> 409"""


class PermissionDeniedError(OpenAgentError):
    """금지된 작업 -> 403"""


class InvalidPathError(OpenAgentError):
    """경로 순회 감지 -> 400"""


# -- 초기화/설정 --
class NotInitializedError(OpenAgentError):
    """매니저 미초기화 -> 500"""


class ConfigError(OpenAgentError):
    """설정 오류 -> 500"""


# -- LLM --
class LLMError(OpenAgentError):
    """LLM 호출 오류 -> 502"""


class LLMRateLimitError(LLMError):
    """API 한도 초과 -> 429"""


class LLMContextWindowError(LLMError):
    """컨텍스트 윈도우 초과 -> 400"""


# -- Job --
class JobError(OpenAgentError):
    """Job 관련 베이스"""


class JobNotFoundError(JobError, NotFoundError):
    """Job 없음 -> 404"""


class JobStateError(JobError):
    """Job 상태 전환 불가 -> 409"""


# -- MCP --
class MCPError(OpenAgentError):
    """MCP 관련 베이스"""


class MCPConnectionError(MCPError):
    """MCP 연결 실패 -> 502"""


# -- Skill --
class SkillError(OpenAgentError):
    """스킬 관련 베이스"""


class SkillNotFoundError(SkillError, NotFoundError):
    """스킬 없음 -> 404"""


class SkillValidationError(SkillError):
    """스킬 형식 오류 -> 400"""


# -- Storage --
class StorageLimitError(OpenAgentError):
    """저장 한도 초과 -> 413"""
