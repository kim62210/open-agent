from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException

from core.auth.dependencies import require_user

from open_agent.core.job_manager import job_manager, validate_job_prompt
from open_agent.core.job_scheduler import job_scheduler
from open_agent.models.job import CreateJobRequest, JobInfo, JobRunRecord, UpdateJobRequest

router = APIRouter()


@router.get("/", response_model=List[JobInfo])
async def list_jobs(current_user: Annotated[dict, Depends(require_user)]):
    return job_manager.get_all_jobs()


@router.get("/{job_id}", response_model=JobInfo)
async def get_job(job_id: str, current_user: Annotated[dict, Depends(require_user)]):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return job


@router.post("/", response_model=JobInfo)
async def create_job(req: CreateJobRequest, current_user: Annotated[dict, Depends(require_user)]):
    error = validate_job_prompt(req.prompt)
    if error:
        raise HTTPException(status_code=400, detail=error)
    try:
        job = await job_manager.create_job(req)
        job_scheduler.refresh_job(job.id)
        return job
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.patch("/{job_id}", response_model=JobInfo)
async def update_job(job_id: str, req: UpdateJobRequest, current_user: Annotated[dict, Depends(require_user)]):
    if req.prompt is not None:
        error = validate_job_prompt(req.prompt)
        if error:
            raise HTTPException(status_code=400, detail=error)
    result = await job_manager.update_job(job_id, req)
    if not result:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    job_scheduler.refresh_job(job_id)
    return result


@router.delete("/{job_id}")
async def delete_job(job_id: str, current_user: Annotated[dict, Depends(require_user)]):
    if job_scheduler.is_running(job_id):
        await job_scheduler.stop_job(job_id)
    if not await job_manager.delete_job(job_id):
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return {"status": "deleted", "job_id": job_id}


@router.post("/{job_id}/toggle", response_model=JobInfo)
async def toggle_job(job_id: str, current_user: Annotated[dict, Depends(require_user)]):
    result = await job_manager.toggle_job(job_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    job_scheduler.refresh_job(job_id)
    return result


@router.post("/{job_id}/run")
async def run_job(job_id: str, current_user: Annotated[dict, Depends(require_user)]):
    """수동 즉시 실행"""
    await job_scheduler.run_now(job_id)
    return {"status": "started", "job_id": job_id}


@router.post("/{job_id}/stop")
async def stop_job(job_id: str, current_user: Annotated[dict, Depends(require_user)]):
    """실행 중인 Job 중지"""
    await job_scheduler.stop_job(job_id)
    return {"status": "stopping", "job_id": job_id}


@router.get("/{job_id}/history", response_model=List[JobRunRecord])
async def get_job_history(job_id: str, current_user: Annotated[dict, Depends(require_user)], limit: int = 20):
    """실행 이력 조회"""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return job_manager.get_run_history(job_id, limit=limit)
