"""Sandbox escalation API endpoints"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.auth.dependencies import require_user

from open_agent.core.sandbox import SandboxPolicy, sandbox_manager

logger = logging.getLogger(__name__)
router = APIRouter()


class EscalationRequest(BaseModel):
    approved: bool
    policy: str  # "network_allowed" | "unrestricted"
    command: str | None = None
    cwd: str | None = None
    workspace_id: str | None = None
    timeout: int = 30


class PolicyStatusResponse(BaseModel):
    sandbox_available: bool
    sandbox_type: str | None = None
    current_policy: str
    effective_policy: str


@router.get("/policy")
async def get_policy(current_user: Annotated[dict, Depends(require_user)]) -> PolicyStatusResponse:
    """현재 샌드박스 정책 상태 조회"""
    support = sandbox_manager.check_support()
    effective = sandbox_manager._get_effective_policy()
    return PolicyStatusResponse(
        sandbox_available=support.get("available", False),
        sandbox_type=support.get("type"),
        current_policy=sandbox_manager._policy.value,
        effective_policy=effective.value,
    )


@router.post("/escalate")
async def handle_escalation(req: EscalationRequest, current_user: Annotated[dict, Depends(require_user)]):
    """에스컬레이션 승인/거부 처리 — 승인 시 원래 명령 재실행"""
    if not req.approved:
        result = sandbox_manager.deny_escalation()
        return {"approved": False, "message": result["message"]}

    # 승인: 정책 캐시 (5분)
    try:
        policy = SandboxPolicy(req.policy)
    except ValueError:
        return {"approved": False, "message": f"Invalid policy: {req.policy}"}

    sandbox_manager.approve_escalation(policy)

    # 원래 명령 재실행
    if req.command and req.cwd:
        try:
            result = await sandbox_manager.execute(
                command=req.command,
                cwd=req.cwd,
                workspace_root=req.cwd,
                timeout=req.timeout,
            )

            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")
            exit_code = result.get("exit_code", -1)

            if len(stdout) > 30000:
                stdout = stdout[:30000] + "\n... (output truncated)"
            if len(stderr) > 5000:
                stderr = stderr[:5000] + "\n... (stderr truncated)"

            output = stdout
            if stderr:
                output += f"\n[stderr]\n{stderr}"
            if not output.strip():
                output = "(no output)"

            return {
                "approved": True,
                "result": f"{output}\n[exit code: {exit_code}]",
                "exit_code": exit_code,
            }
        except Exception as e:
            logger.error(f"Re-execution failed: {e}")
            return {"approved": True, "result": f"Error: {e}", "exit_code": -1}

    return {"approved": True, "message": "Policy escalated for 5 minutes."}


@router.post("/reset")
async def reset_policy(current_user: Annotated[dict, Depends(require_user)]):
    """샌드박스 정책을 기본값으로 초기화"""
    sandbox_manager.reset_policy()
    return {"message": "Policy reset to workspace_write"}
