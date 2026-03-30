from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from core.auth.dependencies import require_user
from core.run_manager import run_manager
from models.run import RunDetail, RunStatus

router = APIRouter()


@router.get("/", response_model=list[RunDetail])
async def list_runs(current_user: Annotated[dict, Depends(require_user)]):
    return await run_manager.list_runs(current_user["id"])


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(run_id: str, current_user: Annotated[dict, Depends(require_user)]):
    run = await run_manager.get_run(run_id, owner_user_id=current_user["id"])
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/{run_id}/status", response_model=RunStatus)
async def get_run_status(run_id: str, current_user: Annotated[dict, Depends(require_user)]):
    run = await run_manager.get_run_status(run_id, owner_user_id=current_user["id"])
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/{run_id}/abort", response_model=RunStatus)
async def abort_run(run_id: str, current_user: Annotated[dict, Depends(require_user)]):
    run = await run_manager.abort_run(run_id, owner_user_id=current_user["id"])
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
