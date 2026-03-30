"""Unit tests for core/exceptions.py — exception hierarchy."""

from core.exceptions import (
    AlreadyExistsError,
    ConfigError,
    InvalidPathError,
    JobError,
    JobNotFoundError,
    JobStateError,
    LLMContextWindowError,
    LLMError,
    LLMRateLimitError,
    MCPConnectionError,
    MCPError,
    NotFoundError,
    NotInitializedError,
    OpenAgentError,
    PermissionDeniedError,
    SkillError,
    SkillNotFoundError,
    SkillValidationError,
    StorageLimitError,
)


class TestExceptionHierarchy:
    """Verify all exceptions exist and inherit from OpenAgentError."""

    def test_base_exception(self):
        err = OpenAgentError("base error")
        assert str(err) == "base error"
        assert isinstance(err, Exception)

    def test_not_found_error(self):
        err = NotFoundError("not found")
        assert isinstance(err, OpenAgentError)
        assert str(err) == "not found"

    def test_already_exists_error(self):
        err = AlreadyExistsError("duplicate")
        assert isinstance(err, OpenAgentError)

    def test_permission_denied_error(self):
        err = PermissionDeniedError("forbidden")
        assert isinstance(err, OpenAgentError)

    def test_invalid_path_error(self):
        err = InvalidPathError("path traversal")
        assert isinstance(err, OpenAgentError)

    def test_not_initialized_error(self):
        err = NotInitializedError("not ready")
        assert isinstance(err, OpenAgentError)

    def test_config_error(self):
        err = ConfigError("bad config")
        assert isinstance(err, OpenAgentError)

    def test_llm_error(self):
        err = LLMError("llm failure")
        assert isinstance(err, OpenAgentError)

    def test_llm_rate_limit_error(self):
        err = LLMRateLimitError("rate limited")
        assert isinstance(err, LLMError)
        assert isinstance(err, OpenAgentError)

    def test_llm_context_window_error(self):
        err = LLMContextWindowError("context exceeded")
        assert isinstance(err, LLMError)
        assert isinstance(err, OpenAgentError)

    def test_job_error(self):
        err = JobError("job error")
        assert isinstance(err, OpenAgentError)

    def test_job_not_found_error_multiple_inheritance(self):
        err = JobNotFoundError("job missing")
        assert isinstance(err, JobError)
        assert isinstance(err, NotFoundError)
        assert isinstance(err, OpenAgentError)

    def test_job_state_error(self):
        err = JobStateError("bad state")
        assert isinstance(err, JobError)
        assert isinstance(err, OpenAgentError)

    def test_mcp_error(self):
        err = MCPError("mcp problem")
        assert isinstance(err, OpenAgentError)

    def test_mcp_connection_error(self):
        err = MCPConnectionError("connection failed")
        assert isinstance(err, MCPError)
        assert isinstance(err, OpenAgentError)

    def test_skill_error(self):
        err = SkillError("skill problem")
        assert isinstance(err, OpenAgentError)

    def test_skill_not_found_error_multiple_inheritance(self):
        err = SkillNotFoundError("skill missing")
        assert isinstance(err, SkillError)
        assert isinstance(err, NotFoundError)
        assert isinstance(err, OpenAgentError)

    def test_skill_validation_error(self):
        err = SkillValidationError("invalid skill")
        assert isinstance(err, SkillError)
        assert isinstance(err, OpenAgentError)

    def test_storage_limit_error(self):
        err = StorageLimitError("too large")
        assert isinstance(err, OpenAgentError)


class TestExceptionChaining:
    """Verify exceptions support chaining with 'from'."""

    def test_chaining(self):
        original = ValueError("original")
        try:
            raise LLMError("wrapped") from original
        except LLMError as err:
            assert err.__cause__ is original

    def test_all_accept_message(self):
        exception_classes = [
            OpenAgentError, NotFoundError, AlreadyExistsError,
            PermissionDeniedError, InvalidPathError, NotInitializedError,
            ConfigError, LLMError, LLMRateLimitError, LLMContextWindowError,
            JobError, JobNotFoundError, JobStateError,
            MCPError, MCPConnectionError,
            SkillError, SkillNotFoundError, SkillValidationError,
            StorageLimitError,
        ]
        for cls in exception_classes:
            err = cls(f"test {cls.__name__}")
            assert cls.__name__ in str(err)
