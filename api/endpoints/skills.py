from typing import List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from open_agent.core.skill_manager import skill_manager
from open_agent.core.workflow_router import workflow_router
from open_agent.models.skill import (
    CreateSkillRequest,
    SkillDetail,
    SkillInfo,
    UpdateSkillRequest,
)

router = APIRouter()


@router.get("/workflows")
async def list_workflows():
    """번들 워크플로우 목록 반환."""
    return [
        {"name": name, "description": summary}
        for name, summary in workflow_router._skill_summaries.items()
    ]


@router.get("/", response_model=List[SkillInfo])
async def list_skills():
    return [s for s in skill_manager.get_all_skills() if not s.is_bundled]


@router.get("/{name}", response_model=SkillDetail)
async def get_skill(name: str):
    detail = skill_manager.load_skill_content(name)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    return detail


@router.post("/", response_model=SkillInfo)
async def create_skill(req: CreateSkillRequest):
    try:
        return skill_manager.create_skill(req.name, req.description, req.instructions)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/{name}")
async def delete_skill(name: str):
    skill = skill_manager.get_skill(name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    if skill.is_bundled:
        raise HTTPException(status_code=403, detail=f"번들 스킬 '{name}'은(는) 삭제할 수 없습니다.")
    if not skill_manager.delete_skill(name):
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    return {"status": "deleted", "name": name}


@router.patch("/{name}", response_model=SkillInfo)
async def update_skill(name: str, req: UpdateSkillRequest):
    result = skill_manager.update_skill(
        name,
        description=req.description,
        instructions=req.instructions,
        enabled=req.enabled,
    )
    if not result:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    return result


@router.post("/{name}/execute")
async def execute_script(name: str, script: str, args: Optional[List[str]] = None):
    skill = skill_manager.get_skill(name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    result = await skill_manager.execute_script(name, script, args)
    return result


@router.post("/reload")
async def reload_skills():
    if skill_manager._base_dirs:
        skill_manager.discover_skills([str(d) for d in skill_manager._base_dirs])
    return {"status": "reloaded", "count": len(skill_manager.get_all_skills())}


@router.post("/upload", response_model=SkillInfo)
async def upload_skill_zip(file: UploadFile = File(...)):
    """zip 파일을 업로드하여 스킬 등록"""
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="zip 파일만 업로드 가능합니다.")
    try:
        data = await file.read()
        return skill_manager.import_from_zip_bytes(data, file.filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class ImportPathRequest(BaseModel):
    path: str


@router.post("/import", response_model=SkillInfo)
async def import_skill_from_path(req: ImportPathRequest):
    """로컬 경로의 스킬 폴더를 등록"""
    try:
        return skill_manager.import_from_path(req.path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 스크립트/참조 파일 읽기·쓰기 ──────────────────────────────

@router.get("/{name}/scripts/{script_name}")
async def read_script(name: str, script_name: str):
    """스킬의 스크립트 파일 내용을 읽습니다."""
    from pathlib import Path
    skill = skill_manager.get_skill(name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    skill_base = Path(skill.path).resolve()
    script_path = skill_manager._resolve_subdir(skill_base, ["scripts", "templates"], script_name)
    if not script_path:
        raise HTTPException(status_code=404, detail=f"Script not found: {script_name}")
    return {"name": script_name, "content": script_path.read_text(encoding="utf-8")}


class UpdateFileRequest(BaseModel):
    content: str


@router.put("/{name}/scripts/{script_name}")
async def write_script(name: str, script_name: str, req: UpdateFileRequest):
    """스킬의 스크립트 파일 내용을 수정합니다."""
    from pathlib import Path
    skill = skill_manager.get_skill(name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    if skill.is_bundled:
        raise HTTPException(status_code=403, detail=f"번들 스킬 '{name}'의 스크립트는 수정할 수 없습니다.")
    if "/" in script_name or "\\" in script_name or ".." in script_name:
        raise HTTPException(status_code=400, detail="파일명에 경로 구분자나 '..'를 포함할 수 없습니다")
    skill_base = Path(skill.path).resolve()
    script_path = skill_manager._resolve_subdir(skill_base, ["scripts", "templates"], script_name)
    if not script_path:
        raise HTTPException(status_code=404, detail=f"Script not found: {script_name}")
    script_path.write_text(req.content, encoding="utf-8")
    return {"name": script_name, "status": "updated"}


@router.get("/{name}/references/{ref_path:path}")
async def read_reference(name: str, ref_path: str):
    """스킬의 참조 파일 내용을 읽습니다."""
    content = skill_manager.load_skill_reference(name, ref_path)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Reference not found: {ref_path}")
    return {"name": ref_path, "content": content}


@router.put("/{name}/references/{ref_path:path}")
async def write_reference(name: str, ref_path: str, req: UpdateFileRequest):
    """스킬의 참조 파일 내용을 수정합니다."""
    from pathlib import Path
    skill = skill_manager.get_skill(name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    if skill.is_bundled:
        raise HTTPException(status_code=403, detail=f"번들 스킬 '{name}'의 참조 파일은 수정할 수 없습니다.")
    if ".." in ref_path:
        raise HTTPException(status_code=400, detail="경로에 '..'를 포함할 수 없습니다")
    skill_base = Path(skill.path).resolve()
    full_path = skill_manager._resolve_subdir(skill_base, ["references", "reference"], ref_path)
    if not full_path:
        raise HTTPException(status_code=404, detail=f"Reference not found: {ref_path}")
    full_path.write_text(req.content, encoding="utf-8")
    return {"name": ref_path, "status": "updated"}
