from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from open_agent.core.memory_manager import memory_manager
from open_agent.models.memory import CreateMemoryRequest, MemoryItem, UpdateMemoryRequest

from core.auth.dependencies import require_any, require_user

router = APIRouter()


@router.get("/", response_model=list[MemoryItem])
async def list_memories(current_user: Annotated[dict, Depends(require_any)]):
    return memory_manager.get_all(owner_user_id=current_user["id"])


@router.post("/", response_model=MemoryItem, status_code=201)
async def create_memory(
    req: CreateMemoryRequest, current_user: Annotated[dict, Depends(require_user)]
):
    return await memory_manager.create(
        content=req.content,
        category=req.category,
        confidence=req.confidence,
        owner_user_id=current_user["id"],
    )


@router.patch("/{memory_id}", response_model=MemoryItem)
async def update_memory(
    memory_id: str, req: UpdateMemoryRequest, current_user: Annotated[dict, Depends(require_user)]
):
    updated = await memory_manager.update(
        memory_id,
        owner_user_id=current_user["id"],
        **req.model_dump(exclude_unset=True),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Memory not found")
    return updated


@router.patch("/{memory_id}/pin", response_model=MemoryItem)
async def toggle_pin(memory_id: str, current_user: Annotated[dict, Depends(require_user)]):
    mem = memory_manager.get(memory_id, owner_user_id=current_user["id"])
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")
    updated = await memory_manager.update(
        memory_id,
        owner_user_id=current_user["id"],
        is_pinned=not mem.is_pinned,
    )
    return updated


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str, current_user: Annotated[dict, Depends(require_user)]):
    if not await memory_manager.delete(memory_id, owner_user_id=current_user["id"]):
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"ok": True}


@router.delete("/")
async def clear_all_memories(current_user: Annotated[dict, Depends(require_user)]):
    count = await memory_manager.clear_all(owner_user_id=current_user["id"])
    return {"ok": True, "deleted": count}
