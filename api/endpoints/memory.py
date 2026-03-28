from fastapi import APIRouter, HTTPException

from open_agent.core.memory_manager import memory_manager
from open_agent.models.memory import CreateMemoryRequest, MemoryItem, UpdateMemoryRequest

router = APIRouter()


@router.get("/", response_model=list[MemoryItem])
async def list_memories():
    return memory_manager.get_all()


@router.post("/", response_model=MemoryItem, status_code=201)
async def create_memory(req: CreateMemoryRequest):
    return memory_manager.create(content=req.content, category=req.category, confidence=req.confidence)


@router.patch("/{memory_id}", response_model=MemoryItem)
async def update_memory(memory_id: str, req: UpdateMemoryRequest):
    updated = memory_manager.update(memory_id, **req.model_dump(exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Memory not found")
    return updated


@router.patch("/{memory_id}/pin", response_model=MemoryItem)
async def toggle_pin(memory_id: str):
    mem = memory_manager.get(memory_id)
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")
    updated = memory_manager.update(memory_id, is_pinned=not mem.is_pinned)
    return updated


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str):
    if not memory_manager.delete(memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"ok": True}


@router.delete("/")
async def clear_all_memories():
    count = memory_manager.clear_all()
    return {"ok": True, "deleted": count}
