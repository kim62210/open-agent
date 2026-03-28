import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from typing import List, Dict, Any, Tuple
from open_agent.core.agent import orchestrator
from open_agent.core.memory_manager import memory_manager

logger = logging.getLogger(__name__)

router = APIRouter()

_ALLOWED_ROLES = {"user", "assistant", "tool"}

# Batched memory extraction state (module-level, reset per server lifecycle)
_pending_turns: List[Tuple[str, str]] = []
_pending_turns_lock = asyncio.Lock()

# Background task 참조 보관 (GC 방지)
_background_tasks: set[asyncio.Task] = set()


def _get_extraction_interval() -> int:
    """Get the extraction interval from settings."""
    try:
        from open_agent.core.settings_manager import settings_manager
        return settings_manager.settings.memory.extraction_interval
    except Exception:
        return 3


async def _maybe_extract_memories():
    """Trigger batch extraction if enough turns have accumulated."""
    interval = _get_extraction_interval()
    async with _pending_turns_lock:
        if len(_pending_turns) >= interval:
            turns = _pending_turns.copy()
            _pending_turns.clear()
            logger.info("Memory extraction triggered: %d turns accumulated", len(turns))
            task = asyncio.create_task(
                memory_manager.extract_and_save_batch(turns)
            )
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
        else:
            logger.info("Memory pending: %d/%d turns", len(_pending_turns), interval)


class ChatRequest(BaseModel):
    messages: List[Dict[str, Any]]
    forced_workflow: str | None = None
    skip_routing: bool = False

    @field_validator("messages")
    @classmethod
    def validate_message_roles(cls, v: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        for msg in v:
            role = msg.get("role")
            if role and role not in _ALLOWED_ROLES:
                raise ValueError(f"허용되지 않는 role입니다: '{role}' (허용: {', '.join(sorted(_ALLOWED_ROLES))})")
        return v


def _extract_text(content) -> str:
    """Extract plain text from message content (string or multimodal array)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                return part.get("text", "")
    return ""


def _safe_get_content(full_response: dict) -> str:
    """full_response에서 assistant content를 안전하게 추출 (None → "" 변환)."""
    try:
        choices = full_response.get("choices") or [{}]
        message = choices[0].get("message") or {}
        # .get("content", "") 은 key 존재 + value=None 시 None 반환하므로 'or ""' 필수
        return message.get("content") or ""
    except (IndexError, AttributeError, TypeError):
        return ""


async def _enqueue_turn(messages: List[Dict[str, Any]], assistant_content: str):
    """Enqueue a conversation turn for batched memory extraction."""
    user_text = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_text = _extract_text(msg.get("content", ""))
            break

    if user_text and assistant_content:
        async with _pending_turns_lock:
            _pending_turns.append((user_text, assistant_content))
        logger.info("Turn enqueued for memory: user=%d chars, assistant=%d chars",
                     len(user_text), len(assistant_content))
        await _maybe_extract_memories()
    else:
        logger.info("Turn NOT enqueued: user_text=%r, assistant_content=%r",
                     bool(user_text), bool(assistant_content))


@router.post("/")
async def chat(request: ChatRequest):
    try:
        response = await orchestrator.run(request.messages, forced_workflow=request.forced_workflow)

        # Enqueue for batched memory extraction
        try:
            assistant_content = _safe_get_content(response)
            await _enqueue_turn(request.messages, assistant_content)
        except Exception as e:
            logger.debug(f"Memory extraction trigger failed: {e}")

        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def chat_stream(request: ChatRequest):
    async def event_generator():
        try:
            async for event in orchestrator.run_stream(request.messages, skip_routing=request.skip_routing, forced_workflow=request.forced_workflow):
                # done 이벤트 시 yield 전에 메모리 enqueue (generator 종료 후 코드 미실행 방지)
                if event["type"] == "done":
                    try:
                        assistant_content = _safe_get_content(event.get("full_response") or {})
                        await _enqueue_turn(request.messages, assistant_content)
                    except Exception as e:
                        logger.debug(f"Memory extraction trigger failed: {e}")
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error("Stream error: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'content': 'Internal server error'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
