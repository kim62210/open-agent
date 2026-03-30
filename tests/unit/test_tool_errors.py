"""Unit tests for core/tool_errors.py — error classification and formatting."""

from core.tool_errors import ToolError, classify_error, format_error_for_llm, is_error_result


# ── classify_error ────────────────────────────────────────────────────


class TestClassifyError:
    def test_module_not_found(self):
        err = classify_error("No module named 'requests'")
        assert err.error_type == "module_not_found"
        assert err.recovery_hint

    def test_command_not_found(self):
        err = classify_error("bash: foo: command not found")
        assert err.error_type == "command_not_found"

    def test_file_not_found(self):
        err = classify_error("FileNotFoundError: [Errno 2] No such file or directory")
        assert err.error_type == "file_not_found"

    def test_permission_denied(self):
        err = classify_error("PermissionError: [Errno 13] Permission denied")
        assert err.error_type == "permission_denied"

    def test_timeout(self):
        err = classify_error("TimeoutError: operation timed out")
        assert err.error_type == "timeout"

    def test_server_disconnected(self):
        err = classify_error("Server 'mcp-1' is not connected")
        assert err.error_type == "server_disconnected"

    def test_env_restricted(self):
        err = classify_error("error: externally-managed-environment")
        assert err.error_type == "env_restricted"

    def test_syntax_error(self):
        err = classify_error("SyntaxError: invalid syntax at line 5")
        assert err.error_type == "syntax_error"

    def test_invalid_tool(self):
        err = classify_error("Invalid tool name: foobar")
        assert err.error_type == "invalid_tool"

    def test_ssl_error(self):
        err = classify_error("SSL: certificate verify failed")
        assert err.error_type == "ssl_error"

    def test_unknown_error(self):
        err = classify_error("something completely unexpected happened")
        assert err.error_type == "unknown"
        assert err.message == "something completely unexpected happened"
        assert err.recovery_hint

    def test_case_insensitive_matching(self):
        err = classify_error("FILENOTFOUNDERROR in module X")
        assert err.error_type == "file_not_found"


# ── format_error_for_llm ─────────────────────────────────────────────


class TestFormatErrorForLlm:
    def test_format_known_error(self):
        result = format_error_for_llm("No module named 'pandas'")
        assert "[TOOL_ERROR]" in result
        assert "type: module_not_found" in result
        assert "recovery_hint:" in result

    def test_format_unknown_error(self):
        result = format_error_for_llm("random error xyz")
        assert "[TOOL_ERROR]" in result
        assert "type: unknown" in result
        assert "message: random error xyz" in result

    def test_format_empty_string(self):
        result = format_error_for_llm("")
        assert "[TOOL_ERROR]" in result
        assert "type: unknown" in result


# ── is_error_result ───────────────────────────────────────────────────


class TestIsErrorResult:
    def test_error_prefix(self):
        assert is_error_result("Error: something went wrong") is True

    def test_tool_error_prefix(self):
        assert is_error_result("[TOOL_ERROR]\ntype: unknown") is True

    def test_blocked_prefix(self):
        assert is_error_result("Blocked: operation not allowed") is True

    def test_normal_result(self):
        assert is_error_result("Success: file created") is False

    def test_empty_string(self):
        assert is_error_result("") is False

    def test_none_like_empty(self):
        assert is_error_result("") is False

    def test_partial_prefix_no_match(self):
        assert is_error_result("Err: not quite") is False


# ── ToolError dataclass ──────────────────────────────────────────────


class TestToolErrorDataclass:
    def test_creation(self):
        err = ToolError(
            error_type="test_type",
            message="test message",
            recovery_hint="try again",
        )
        assert err.error_type == "test_type"
        assert err.message == "test message"
        assert err.recovery_hint == "try again"
