"""OS-native process sandboxing with escalation support.

Provides kernel-level process isolation:
- macOS: Seatbelt (sandbox-exec)
- Linux: bubblewrap (bwrap) + namespace isolation
- Windows: Job Objects (basic), with Restricted Token support planned

The escalation strategy allows sandboxed commands to request
additional permissions (e.g., network access) through user approval.
"""

from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Rust sandbox (optional) ──────────────────────────────────────────

try:
    from nexus_rust import check_sandbox_support as _rust_check_support
    from nexus_rust import run_sandboxed as _rust_run_sandboxed

    _HAVE_SANDBOX = True
except ImportError:
    _HAVE_SANDBOX = False


# ── Policy model ─────────────────────────────────────────────────────


class SandboxPolicy(str, Enum):
    """Sandbox permission levels, from most restrictive to least."""

    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    NETWORK_ALLOWED = "network_allowed"
    UNRESTRICTED = "unrestricted"


class EscalationStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


# ── Sandbox Manager ──────────────────────────────────────────────────


class SandboxManager:
    """Manages sandbox policy and escalation for workspace commands."""

    def __init__(self) -> None:
        self._policy = SandboxPolicy.WORKSPACE_WRITE
        self._escalation_cache: Dict[str, float] = {}  # policy → expiry timestamp
        self._cache_duration = 300  # 5 minutes

    @property
    def policy(self) -> SandboxPolicy:
        return self._policy

    @property
    def is_available(self) -> bool:
        if not _HAVE_SANDBOX:
            return False
        supported, _ = _rust_check_support()
        return supported

    def check_support(self) -> Dict[str, Any]:
        """Check sandbox support on the current platform."""
        if not _HAVE_SANDBOX:
            return {
                "available": False,
                "mechanism": "none",
                "reason": "nexus_rust extension not installed",
            }
        supported, mechanism = _rust_check_support()
        return {
            "available": supported,
            "mechanism": mechanism,
            "reason": None if supported else f"{mechanism} not found on this system",
        }

    async def execute(
        self,
        command: str,
        cwd: str,
        workspace_root: str,
        timeout: int = 30,
        git_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a command with sandbox protection.

        Args:
            command: Shell command to execute
            cwd: Working directory
            workspace_root: Root path of the workspace (writable)
            timeout: Timeout in seconds
            git_dir: Path to .git directory to protect (read-only)

        Returns:
            Dict with exit_code, stdout, stderr, timed_out, sandbox_violation
        """
        if not _HAVE_SANDBOX:
            return await self._fallback_execute(command, cwd, timeout)

        supported, _ = _rust_check_support()
        if not supported:
            return await self._fallback_execute(command, cwd, timeout)

        # Build sandbox config based on current policy
        effective_policy = self._get_effective_policy()

        if effective_policy == SandboxPolicy.UNRESTRICTED:
            return await self._fallback_execute(command, cwd, timeout)

        allowed_write = [workspace_root]
        denied_write = []

        # Protect .git directory
        if git_dir:
            denied_write.append(git_dir)
        else:
            git_path = str(Path(workspace_root) / ".git")
            if Path(git_path).exists():
                denied_write.append(git_path)

        allow_network = effective_policy in (
            SandboxPolicy.NETWORK_ALLOWED,
            SandboxPolicy.UNRESTRICTED,
        )

        # Run in thread pool to avoid blocking asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: _rust_run_sandboxed(
                command=command,
                cwd=cwd,
                allowed_read_paths=[],  # Seatbelt defaults handle system reads
                allowed_write_paths=allowed_write,
                denied_write_paths=denied_write,
                allow_network=allow_network,
                timeout_secs=timeout,
            ),
        )

        return dict(result)

    def _get_effective_policy(self) -> SandboxPolicy:
        """Get the current effective policy, considering cached escalations."""
        now = time.time()
        # Check if there's a cached escalation that's still valid
        for policy_value, expiry in list(self._escalation_cache.items()):
            if now > expiry:
                del self._escalation_cache[policy_value]
                continue
            cached_policy = SandboxPolicy(policy_value)
            # Return the highest privilege level that's cached
            if _policy_level(cached_policy) > _policy_level(self._policy):
                return cached_policy

        return self._policy

    def request_escalation(self, requested_policy: SandboxPolicy) -> Dict[str, Any]:
        """Create an escalation request for the user.

        Returns a dict describing what permission is being requested.
        """
        current = self._get_effective_policy()

        if _policy_level(requested_policy) <= _policy_level(current):
            return {
                "needed": False,
                "message": "Current policy already permits this operation.",
            }

        descriptions = {
            SandboxPolicy.NETWORK_ALLOWED: "네트워크 접근 (npm install, pip install 등에 필요)",
            SandboxPolicy.UNRESTRICTED: "전체 권한 (샌드박스 비활성화)",
        }

        return {
            "needed": True,
            "current_policy": current.value,
            "requested_policy": requested_policy.value,
            "description": descriptions.get(requested_policy, requested_policy.value),
            "message": (
                f"이 작업을 수행하려면 '{descriptions.get(requested_policy, requested_policy.value)}' 권한이 필요합니다. "
                f"허용하시겠습니까? (5분간 유효)"
            ),
        }

    def approve_escalation(
        self,
        policy: SandboxPolicy,
        duration_minutes: int = 5,
    ) -> Dict[str, Any]:
        """Approve an escalation request. Cached for duration_minutes."""
        self._escalation_cache[policy.value] = time.time() + (duration_minutes * 60)
        logger.info(
            f"Sandbox escalation approved: {policy.value} for {duration_minutes}m"
        )
        return {
            "approved": True,
            "policy": policy.value,
            "expires_in_minutes": duration_minutes,
        }

    def deny_escalation(self) -> Dict[str, Any]:
        """Deny an escalation request."""
        return {
            "approved": False,
            "message": "Escalation denied. Command will run with current sandbox restrictions.",
        }

    def reset_policy(self) -> None:
        """Reset to default policy and clear all cached escalations."""
        self._policy = SandboxPolicy.WORKSPACE_WRITE
        self._escalation_cache.clear()
        logger.info("Sandbox policy reset to workspace_write")

    async def _fallback_execute(
        self, command: str, cwd: str, timeout: int
    ) -> Dict[str, Any]:
        """Execute without sandbox (fallback when Rust extension unavailable)."""
        import os
        import shutil
        import sys

        from open_agent.core.workspace_tools import get_sanitized_env

        if sys.platform == "win32":
            shell_exe = shutil.which("pwsh") or shutil.which("powershell") or shutil.which("cmd")
        else:
            shell_exe = shutil.which("sh") or shutil.which("bash")

        shell_kwargs: dict = {}
        if shell_exe:
            shell_kwargs["executable"] = shell_exe

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=get_sanitized_env(),
                **shell_kwargs,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )

            return {
                "exit_code": proc.returncode or 0,
                "stdout": stdout_bytes.decode(errors="replace"),
                "stderr": stderr_bytes.decode(errors="replace"),
                "timed_out": False,
                "sandbox_violation": None,
            }
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout}s",
                "timed_out": True,
                "sandbox_violation": None,
            }
        except Exception as e:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "timed_out": False,
                "sandbox_violation": None,
            }


def _policy_level(policy: SandboxPolicy) -> int:
    """Return numeric level for policy comparison."""
    return {
        SandboxPolicy.READ_ONLY: 0,
        SandboxPolicy.WORKSPACE_WRITE: 1,
        SandboxPolicy.NETWORK_ALLOWED: 2,
        SandboxPolicy.UNRESTRICTED: 3,
    }.get(policy, 0)


# ── Singleton ────────────────────────────────────────────────────────

sandbox_manager = SandboxManager()
