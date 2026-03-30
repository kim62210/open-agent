import asyncio
import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from open_agent.core.agent import orchestrator
from open_agent.core.memory_manager import memory_manager
from pydantic import BaseModel, field_validator

from core.auth.dependencies import require_user
from core.auth.rate_limit import limiter
from core.run_manager import run_manager
from models.run import AsyncRunAccepted

logger = logging.getLogger(__name__)

router = APIRouter()

_ALLOWED_ROLES = {"user", "assistant", "tool"}

# Batched memory extraction state (module-level, reset per server lifecycle)
_pending_turns: list[tuple[str, str]] = []
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
            task = asyncio.create_task(memory_manager.extract_and_save_batch(turns))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
        else:
            logger.info("Memory pending: %d/%d turns", len(_pending_turns), interval)


class ChatRequest(BaseModel):
    messages: list[dict[str, Any]]
    forced_workflow: str | None = None
    skip_routing: bool = False

    @field_validator("messages")
    @classmethod
    def validate_message_roles(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for msg in v:
            role = msg.get("role")
            if role and role not in _ALLOWED_ROLES:
                raise ValueError(
                    f"허용되지 않는 role입니다: '{role}' (허용: {', '.join(sorted(_ALLOWED_ROLES))})"
                )
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


async def _enqueue_turn(messages: list[dict[str, Any]], assistant_content: str):
    """Enqueue a conversation turn for batched memory extraction."""
    user_text = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_text = _extract_text(msg.get("content", ""))
            break

    if user_text and assistant_content:
        async with _pending_turns_lock:
            _pending_turns.append((user_text, assistant_content))
        logger.info(
            "Turn enqueued for memory: user=%d chars, assistant=%d chars",
            len(user_text),
            len(assistant_content),
        )
        await _maybe_extract_memories()
    else:
        logger.info(
            "Turn NOT enqueued: user_text=%r, assistant_content=%r",
            bool(user_text),
            bool(assistant_content),
        )


@router.post("/")
@limiter.limit("20/minute")
async def chat(
    request: Request,
    body: ChatRequest,
    current_user: Annotated[dict, Depends(require_user)],
):
    run = await run_manager.create_run(
        owner_user_id=current_user["id"],
        request_messages=body.messages,
    )
    await run_manager.append_event(
        run.id,
        "request.received",
        {"message_count": len(body.messages), "forced_workflow": body.forced_workflow},
    )
    try:
        response = await orchestrator.run(body.messages, forced_workflow=body.forced_workflow)
        await run_manager.append_event(
            run.id, "response.completed", {"has_choices": bool(response.get("choices"))}
        )
        await run_manager.finish_run(run.id, status="completed", response_payload=response)

        # Enqueue for batched memory extraction
        try:
            assistant_content = _safe_get_content(response)
            await _enqueue_turn(body.messages, assistant_content)
        except Exception as e:
            logger.debug(f"Memory extraction trigger failed: {e}")

        return response
    except Exception as e:
        await run_manager.append_event(run.id, "response.failed", {"error": str(e)})
        await run_manager.finish_run(run.id, status="failed", error_message=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/async", status_code=202, response_model=AsyncRunAccepted)
@limiter.limit("20/minute")
async def chat_async(
    request: Request,
    body: ChatRequest,
    current_user: Annotated[dict, Depends(require_user)],
):
    run = await run_manager.create_run(
        owner_user_id=current_user["id"],
        request_messages=body.messages,
    )
    await run_manager.append_event(
        run.id,
        "async.request.received",
        {"message_count": len(body.messages), "forced_workflow": body.forced_workflow},
    )

    async def _background_run() -> None:
        try:
            response = await orchestrator.run(body.messages, forced_workflow=body.forced_workflow)
            await run_manager.append_event(
                run.id,
                "async.response.completed",
                {"has_choices": bool(response.get("choices"))},
            )
            await run_manager.finish_run(run.id, status="completed", response_payload=response)
            try:
                assistant_content = _safe_get_content(response)
                await _enqueue_turn(body.messages, assistant_content)
            except Exception as e:
                logger.debug(f"Memory extraction trigger failed: {e}")
        except asyncio.CancelledError:
            await run_manager.finish_run(
                run.id, status="cancelled", error_message="Cancelled by user"
            )
            raise
        except Exception as e:
            await run_manager.append_event(run.id, "async.response.failed", {"error": str(e)})
            await run_manager.finish_run(run.id, status="failed", error_message=str(e))

    task = asyncio.create_task(_background_run())
    run_manager.register_background_task(run.id, task)
    return AsyncRunAccepted(run_id=run.id, status=run.status)


@router.post("/stream")
@limiter.limit("10/minute")
async def chat_stream(
    request: Request,
    body: ChatRequest,
    current_user: Annotated[dict, Depends(require_user)],
):
    run = await run_manager.create_run(
        owner_user_id=current_user["id"],
        request_messages=body.messages,
    )
    await run_manager.append_event(
        run.id,
        "stream.request.received",
        {"message_count": len(body.messages), "forced_workflow": body.forced_workflow},
    )

    async def event_generator():
        try:
            async for event in orchestrator.run_stream(
                body.messages, skip_routing=body.skip_routing, forced_workflow=body.forced_workflow
            ):
                if event["type"] != "content_delta":
                    await run_manager.append_event(
                        run.id,
                        event["type"],
                        {key: value for key, value in event.items() if key != "type"},
                    )
                # done 이벤트 시 yield 전에 메모리 enqueue (generator 종료 후 코드 미실행 방지)
                if event["type"] == "done":
                    try:
                        assistant_content = _safe_get_content(event.get("full_response") or {})
                        await _enqueue_turn(body.messages, assistant_content)
                    except Exception as e:
                        logger.debug(f"Memory extraction trigger failed: {e}")
                    await run_manager.finish_run(
                        run.id,
                        status="completed",
                        response_payload=event.get("full_response"),
                    )
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error("Stream error: %s", e)
            await run_manager.append_event(run.id, "stream.failed", {"error": str(e)})
            await run_manager.finish_run(run.id, status="failed", error_message=str(e))
            yield f"data: {json.dumps({'type': 'error', 'content': 'Internal server error'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
