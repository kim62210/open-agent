"""Sandbox API integration tests — policy, escalation, reset."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


@pytest.fixture()
async def sandbox_client(_patch_db_factory, monkeypatch):
    """httpx.AsyncClient wired to sandbox router with mocked sandbox_manager."""
    import httpx
    from fastapi import FastAPI
    from httpx import ASGITransport
    from open_agent.api.endpoints import sandbox as sandbox_router

    from core.auth.dependencies import get_current_user

    test_app = FastAPI()
    test_app.include_router(sandbox_router.router, prefix="/api/sandbox")

    async def _fake_current_user() -> dict:
        return {
            "id": "test-user-id",
            "email": "test@example.com",
            "username": "testuser",
            "role": "admin",
        }

    test_app.dependency_overrides[get_current_user] = _fake_current_user

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture()
async def non_admin_sandbox_client(_patch_db_factory):
    import httpx
    from fastapi import FastAPI
    from httpx import ASGITransport
    from open_agent.api.endpoints import sandbox as sandbox_router

    from core.auth.dependencies import get_current_user

    test_app = FastAPI()
    test_app.include_router(sandbox_router.router, prefix="/api/sandbox")

    async def _fake_current_user() -> dict:
        return {
            "id": "test-user-id",
            "email": "user@example.com",
            "username": "regularuser",
            "role": "user",
        }

    test_app.dependency_overrides[get_current_user] = _fake_current_user

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestGetPolicy:
    """GET /api/sandbox/policy"""

    async def test_get_policy(self, sandbox_client: AsyncClient):
        """Returns current sandbox policy status."""
        with patch("open_agent.api.endpoints.sandbox.sandbox_manager") as mock_sm:
            mock_sm.check_support.return_value = {"available": True, "type": "seatbelt"}
            mock_policy = MagicMock()
            mock_policy.value = "workspace_write"
            mock_sm._policy = mock_policy
            mock_effective = MagicMock()
            mock_effective.value = "workspace_write"
            mock_sm._get_effective_policy.return_value = mock_effective
            resp = await sandbox_client.get("/api/sandbox/policy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sandbox_available"] is True
        assert data["sandbox_type"] == "seatbelt"
        assert data["current_policy"] == "workspace_write"

    async def test_get_policy_unavailable(self, sandbox_client: AsyncClient):
        """Returns sandbox_available=False when no sandbox support."""
        with patch("open_agent.api.endpoints.sandbox.sandbox_manager") as mock_sm:
            mock_sm.check_support.return_value = {"available": False, "type": None}
            mock_policy = MagicMock()
            mock_policy.value = "workspace_write"
            mock_sm._policy = mock_policy
            mock_effective = MagicMock()
            mock_effective.value = "workspace_write"
            mock_sm._get_effective_policy.return_value = mock_effective
            resp = await sandbox_client.get("/api/sandbox/policy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sandbox_available"] is False


class TestEscalation:
    """POST /api/sandbox/escalate"""

    async def test_approve_escalation_no_command(self, sandbox_client: AsyncClient):
        """Approves escalation without re-executing a command."""
        with patch("open_agent.api.endpoints.sandbox.sandbox_manager") as mock_sm:
            with patch("open_agent.api.endpoints.sandbox.SandboxPolicy") as mock_policy_cls:
                mock_policy_cls.return_value = MagicMock()
                mock_sm.approve_escalation = MagicMock()
                resp = await sandbox_client.post(
                    "/api/sandbox/escalate",
                    json={"approved": True, "policy": "network_allowed"},
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["approved"] is True
        assert "message" in data

    async def test_deny_escalation(self, sandbox_client: AsyncClient):
        """Denies escalation request."""
        with patch("open_agent.api.endpoints.sandbox.sandbox_manager") as mock_sm:
            mock_sm.deny_escalation.return_value = {"message": "Escalation denied"}
            resp = await sandbox_client.post(
                "/api/sandbox/escalate",
                json={"approved": False, "policy": "network_allowed"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["approved"] is False
        assert "denied" in data["message"].lower()

    async def test_approve_escalation_with_command(self, sandbox_client: AsyncClient):
        """Approves and re-executes the original command."""
        with patch("open_agent.api.endpoints.sandbox.sandbox_manager") as mock_sm:
            with patch("open_agent.api.endpoints.sandbox.SandboxPolicy") as mock_policy_cls:
                mock_policy_cls.return_value = MagicMock()
                mock_sm.approve_escalation = MagicMock()
                mock_sm.execute = AsyncMock(
                    return_value={
                        "stdout": "hello world",
                        "stderr": "",
                        "exit_code": 0,
                    }
                )
                resp = await sandbox_client.post(
                    "/api/sandbox/escalate",
                    json={
                        "approved": True,
                        "policy": "unrestricted",
                        "command": "echo hello",
                        "cwd": "/tmp",
                        "timeout": 10,
                    },
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["approved"] is True
        assert "hello world" in data["result"]
        assert data["exit_code"] == 0

    async def test_approve_escalation_command_failure(self, sandbox_client: AsyncClient):
        """Returns error when re-execution fails."""
        with patch("open_agent.api.endpoints.sandbox.sandbox_manager") as mock_sm:
            with patch("open_agent.api.endpoints.sandbox.SandboxPolicy") as mock_policy_cls:
                mock_policy_cls.return_value = MagicMock()
                mock_sm.approve_escalation = MagicMock()
                mock_sm.execute = AsyncMock(side_effect=RuntimeError("Permission denied"))
                resp = await sandbox_client.post(
                    "/api/sandbox/escalate",
                    json={
                        "approved": True,
                        "policy": "unrestricted",
                        "command": "rm -rf /",
                        "cwd": "/tmp",
                    },
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["approved"] is True
        assert "Error" in data["result"]
        assert data["exit_code"] == -1

    async def test_approve_escalation_invalid_policy(self, sandbox_client: AsyncClient):
        """Returns not-approved for invalid policy string."""
        with patch(
            "open_agent.api.endpoints.sandbox.SandboxPolicy", side_effect=ValueError("Invalid")
        ):
            resp = await sandbox_client.post(
                "/api/sandbox/escalate",
                json={"approved": True, "policy": "bad_policy"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["approved"] is False
        assert "Invalid policy" in data["message"]

    async def test_approve_escalation_truncated_output(self, sandbox_client: AsyncClient):
        """Long stdout/stderr is truncated."""
        with patch("open_agent.api.endpoints.sandbox.sandbox_manager") as mock_sm:
            with patch("open_agent.api.endpoints.sandbox.SandboxPolicy") as mock_policy_cls:
                mock_policy_cls.return_value = MagicMock()
                mock_sm.approve_escalation = MagicMock()
                mock_sm.execute = AsyncMock(
                    return_value={
                        "stdout": "x" * 40000,
                        "stderr": "e" * 10000,
                        "exit_code": 0,
                    }
                )
                resp = await sandbox_client.post(
                    "/api/sandbox/escalate",
                    json={
                        "approved": True,
                        "policy": "unrestricted",
                        "command": "big-output",
                        "cwd": "/tmp",
                    },
                )
        assert resp.status_code == 200
        data = resp.json()
        assert "truncated" in data["result"]

    async def test_approve_escalation_empty_output(self, sandbox_client: AsyncClient):
        """Empty command output shows '(no output)' placeholder."""
        with patch("open_agent.api.endpoints.sandbox.sandbox_manager") as mock_sm:
            with patch("open_agent.api.endpoints.sandbox.SandboxPolicy") as mock_policy_cls:
                mock_policy_cls.return_value = MagicMock()
                mock_sm.approve_escalation = MagicMock()
                mock_sm.execute = AsyncMock(
                    return_value={
                        "stdout": "",
                        "stderr": "",
                        "exit_code": 0,
                    }
                )
                resp = await sandbox_client.post(
                    "/api/sandbox/escalate",
                    json={
                        "approved": True,
                        "policy": "unrestricted",
                        "command": "true",
                        "cwd": "/tmp",
                    },
                )
        assert resp.status_code == 200
        data = resp.json()
        assert "(no output)" in data["result"]


class TestResetPolicy:
    """POST /api/sandbox/reset"""

    async def test_reset_policy(self, sandbox_client: AsyncClient):
        """Resets sandbox policy to default."""
        with patch("open_agent.api.endpoints.sandbox.sandbox_manager") as mock_sm:
            mock_sm.reset_policy = MagicMock()
            resp = await sandbox_client.post("/api/sandbox/reset")
        assert resp.status_code == 200
        assert "reset" in resp.json()["message"].lower()

    async def test_non_admin_cannot_reset_policy(self, non_admin_sandbox_client: AsyncClient):
        resp = await non_admin_sandbox_client.post("/api/sandbox/reset")
        assert resp.status_code == 403
