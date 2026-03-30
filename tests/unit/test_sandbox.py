"""Unit tests for core/sandbox.py — sandbox policy and escalation."""

import time
from unittest.mock import AsyncMock, patch

import pytest

from core.sandbox import (
    SandboxManager,
    SandboxPolicy,
    EscalationStatus,
    _policy_level,
    sandbox_manager,
)


# ── SandboxPolicy enum ───────────────────────────────────────────────


class TestSandboxPolicy:
    def test_enum_values(self):
        assert SandboxPolicy.READ_ONLY == "read_only"
        assert SandboxPolicy.WORKSPACE_WRITE == "workspace_write"
        assert SandboxPolicy.NETWORK_ALLOWED == "network_allowed"
        assert SandboxPolicy.UNRESTRICTED == "unrestricted"

    def test_enum_is_string(self):
        assert isinstance(SandboxPolicy.READ_ONLY, str)


class TestEscalationStatus:
    def test_enum_values(self):
        assert EscalationStatus.PENDING == "pending"
        assert EscalationStatus.APPROVED == "approved"
        assert EscalationStatus.DENIED == "denied"


# ── _policy_level ─────────────────────────────────────────────────────


class TestPolicyLevel:
    def test_levels_ordered(self):
        assert _policy_level(SandboxPolicy.READ_ONLY) == 0
        assert _policy_level(SandboxPolicy.WORKSPACE_WRITE) == 1
        assert _policy_level(SandboxPolicy.NETWORK_ALLOWED) == 2
        assert _policy_level(SandboxPolicy.UNRESTRICTED) == 3

    def test_increasing_order(self):
        levels = [
            _policy_level(SandboxPolicy.READ_ONLY),
            _policy_level(SandboxPolicy.WORKSPACE_WRITE),
            _policy_level(SandboxPolicy.NETWORK_ALLOWED),
            _policy_level(SandboxPolicy.UNRESTRICTED),
        ]
        assert levels == sorted(levels)


# ── SandboxManager init ──────────────────────────────────────────────


class TestSandboxManagerInit:
    def test_default_policy(self):
        mgr = SandboxManager()
        assert mgr.policy == SandboxPolicy.WORKSPACE_WRITE

    def test_is_available_without_rust(self):
        with patch("core.sandbox._HAVE_SANDBOX", False):
            mgr = SandboxManager()
            assert mgr.is_available is False

    def test_check_support_without_rust(self):
        with patch("core.sandbox._HAVE_SANDBOX", False):
            mgr = SandboxManager()
            result = mgr.check_support()
            assert result["available"] is False
            assert result["mechanism"] == "none"
            assert "nexus_rust" in result["reason"]


# ── request_escalation ────────────────────────────────────────────────


class TestRequestEscalation:
    def test_no_escalation_needed(self):
        mgr = SandboxManager()
        result = mgr.request_escalation(SandboxPolicy.READ_ONLY)
        assert result["needed"] is False

    def test_same_level_not_needed(self):
        mgr = SandboxManager()
        result = mgr.request_escalation(SandboxPolicy.WORKSPACE_WRITE)
        assert result["needed"] is False

    def test_escalation_to_network(self):
        mgr = SandboxManager()
        result = mgr.request_escalation(SandboxPolicy.NETWORK_ALLOWED)
        assert result["needed"] is True
        assert result["current_policy"] == "workspace_write"
        assert result["requested_policy"] == "network_allowed"

    def test_escalation_to_unrestricted(self):
        mgr = SandboxManager()
        result = mgr.request_escalation(SandboxPolicy.UNRESTRICTED)
        assert result["needed"] is True
        assert result["requested_policy"] == "unrestricted"


# ── approve_escalation / deny_escalation ──────────────────────────────


class TestApproveEscalation:
    def test_approve(self):
        mgr = SandboxManager()
        result = mgr.approve_escalation(SandboxPolicy.NETWORK_ALLOWED, duration_minutes=5)
        assert result["approved"] is True
        assert result["policy"] == "network_allowed"
        assert result["expires_in_minutes"] == 5

    def test_approved_policy_takes_effect(self):
        mgr = SandboxManager()
        mgr.approve_escalation(SandboxPolicy.NETWORK_ALLOWED, duration_minutes=5)
        effective = mgr._get_effective_policy()
        assert effective == SandboxPolicy.NETWORK_ALLOWED

    def test_expired_escalation_ignored(self):
        mgr = SandboxManager()
        # Manually set an already-expired escalation
        mgr._escalation_cache["network_allowed"] = time.time() - 10
        effective = mgr._get_effective_policy()
        assert effective == SandboxPolicy.WORKSPACE_WRITE
        assert "network_allowed" not in mgr._escalation_cache

    def test_deny(self):
        mgr = SandboxManager()
        result = mgr.deny_escalation()
        assert result["approved"] is False


# ── reset_policy ──────────────────────────────────────────────────────


class TestResetPolicy:
    def test_reset_clears_cache(self):
        mgr = SandboxManager()
        mgr.approve_escalation(SandboxPolicy.NETWORK_ALLOWED)
        mgr.reset_policy()
        assert mgr.policy == SandboxPolicy.WORKSPACE_WRITE
        assert mgr._escalation_cache == {}


# ── _fallback_execute ─────────────────────────────────────────────────


class TestFallbackExecute:
    async def test_simple_command(self):
        mgr = SandboxManager()
        with patch("core.sandbox._HAVE_SANDBOX", False):
            result = await mgr.execute("echo hello", "/tmp", "/tmp", timeout=10)
        assert result["timed_out"] is False
        assert "hello" in result["stdout"]
        assert result["sandbox_violation"] is None

    async def test_timeout_handling(self):
        mgr = SandboxManager()
        with patch("core.sandbox._HAVE_SANDBOX", False):
            result = await mgr.execute("sleep 60", "/tmp", "/tmp", timeout=1)
        assert result["timed_out"] is True
        assert result["exit_code"] == -1


# ── singleton ─────────────────────────────────────────────────────────


class TestSingleton:
    def test_singleton_exists(self):
        assert isinstance(sandbox_manager, SandboxManager)
