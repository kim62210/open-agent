import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from open_agent.core.llm import llm_client
from open_agent.core.memory_manager import memory_manager
from open_agent.core.session_manager import session_manager
from open_agent.core.settings_manager import settings_manager
from open_agent.models.session import (
    CreateSessionRequest,
    SaveMessagesRequest,
    SessionDetail,
    SessionInfo,
    UpdateSessionRequest,
)

from core.auth.dependencies import require_any, require_user
from core.task_supervisor import task_supervisor

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=list[SessionInfo])
async def list_sessions(current_user: Annotated[dict, Depends(require_any)]):
    return session_manager.get_all(owner_user_id=current_user["id"])


async def _summarize_previous_session() -> None:
    """가장 최근 세션의 요약을 비동기로 생성합니다 (L2 계층)."""
    try:
        sessions = session_manager.get_all()
        if not sessions:
            return
        prev = sessions[0]  # 가장 최근 세션
        if prev.message_count < 4:  # 최소 4개 메시지 (2턴)
            return
        messages_objs = await session_manager.get_messages(prev.id)
        if not messages_objs:
            return
        messages = [m.model_dump(exclude_none=True) for m in messages_objs]
        await memory_manager.generate_session_summary(prev.id, prev.title, messages)
    except Exception as e:
        logger.debug(f"Previous session summary failed: {e}")


@router.post("/", response_model=SessionInfo)
async def create_session(
    req: CreateSessionRequest, current_user: Annotated[dict, Depends(require_user)]
):
    # 새 세션 생성 전, 이전 세션을 백그라운드에서 요약
    summary_task = asyncio.create_task(_summarize_previous_session())
    task_supervisor.track(
        summary_task, name="session.summary", metadata={"user_id": current_user["id"]}
    )
    return await session_manager.create_session(req.title, owner_user_id=current_user["id"])


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str, current_user: Annotated[dict, Depends(require_any)]):
    info = session_manager.get_session(session_id, owner_user_id=current_user["id"])
    if not info:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = (
        await session_manager.get_messages(session_id, owner_user_id=current_user["id"]) or []
    )
    return SessionDetail(info=info, messages=messages)


@router.put("/{session_id}/messages", response_model=SessionInfo)
async def save_messages(
    session_id: str, req: SaveMessagesRequest, current_user: Annotated[dict, Depends(require_user)]
):
    result = await session_manager.save_messages(
        session_id, req.messages, owner_user_id=current_user["id"]
    )
    if not result:
        raise HTTPException(status_code=404, detail="Session not found")
    return result


@router.patch("/{session_id}", response_model=SessionInfo)
async def update_session(
    session_id: str, req: UpdateSessionRequest, current_user: Annotated[dict, Depends(require_user)]
):
    result = await session_manager.update_session(
        session_id, req.title, owner_user_id=current_user["id"]
    )
    if not result:
        raise HTTPException(status_code=404, detail="Session not found")
    return result


@router.get("/{session_id}/context")
async def get_context_status(session_id: str, current_user: Annotated[dict, Depends(require_any)]):
    """세션의 현재 컨텍스트 사용 상태를 반환합니다 (경량 토큰 카운팅)."""
    info = session_manager.get_session(session_id, owner_user_id=current_user["id"])
    if not info:
        raise HTTPException(status_code=404, detail="Session not found")
    messages_objs = await session_manager.get_messages(session_id, owner_user_id=current_user["id"])
    if not messages_objs:
        return {
            "context_window": 0,
            "used_tokens": 0,
            "available_tokens": 0,
            "usage_ratio": 0,
            "compact_threshold": settings_manager.llm.compact_threshold,
        }
    messages = [m.model_dump(exclude_none=True) for m in messages_objs]
    context_window = llm_client.get_context_window()
    used_tokens = llm_client.count_tokens(messages)
    usage_ratio = used_tokens / context_window if context_window > 0 else 0
    return {
        "context_window": context_window,
        "used_tokens": used_tokens,
        "available_tokens": max(0, context_window - used_tokens),
        "usage_ratio": round(usage_ratio, 4),
        "compact_threshold": settings_manager.llm.compact_threshold,
    }


@router.delete("/{session_id}")
async def delete_session(session_id: str, current_user: Annotated[dict, Depends(require_user)]):
    if not await session_manager.delete_session(session_id, owner_user_id=current_user["id"]):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted"}
