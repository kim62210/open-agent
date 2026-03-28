"""Job 실행 엔진 — 등록된 Job의 프롬프트를 AgentOrchestrator로 실행합니다."""

import asyncio
import logging

from open_agent.core.exceptions import JobNotFoundError
from open_agent.core.job_manager import job_manager

logger = logging.getLogger(__name__)

JOB_TIMEOUT = 300  # 실행 타임아웃 (초)


async def execute_job(job_id: str) -> str:
    """Job을 실행하고 결과 요약 텍스트를 반환합니다.
    JOB_TIMEOUT 초과 시 asyncio.TimeoutError를 raise합니다."""
    from open_agent.core.agent import orchestrator
    from open_agent.core.mcp_manager import mcp_manager
    from open_agent.core.skill_manager import skill_manager

    job = job_manager.get_job(job_id)
    if not job:
        raise JobNotFoundError(f"Job not found: {job_id}")

    logger.info(f"Executing job: {job.name} ({job_id})")

    # 스킬 지시사항 수집 — skill_manager.load_skill_content() 사용
    skill_instructions = []
    for skill_name in job.skill_names:
        detail = skill_manager.load_skill_content(skill_name)
        if detail and detail.content:
            skill_instructions.append(f"## 스킬: {skill_name}\n{detail.content}")

    # MCP 도구 힌트 수집 — job.mcp_server_names 기반
    mcp_tool_hints = []
    for server_name in job.mcp_server_names:
        tools = await mcp_manager.get_tools_for_server(server_name)
        if tools:
            tool_lines = [f"  - {server_name}__{t.name}: {t.description or ''}" for t in tools]
            mcp_tool_hints.append(f"## MCP 서버: {server_name}\n" + "\n".join(tool_lines))

    messages = []

    system_parts = []
    if skill_instructions:
        system_parts.append(
            "이 작업에서 사용할 스킬 지시사항입니다. 아래 스킬의 절차를 따라주세요.\n\n"
            + "\n\n---\n\n".join(skill_instructions)
        )
        logger.info(f"Injected {len(skill_instructions)} skill instructions for job {job_id}")
    if mcp_tool_hints:
        system_parts.append(
            "이 작업에서 사용할 MCP 도구입니다. 아래 도구를 활용하여 작업을 수행하세요.\n\n"
            + "\n\n---\n\n".join(mcp_tool_hints)
        )
        logger.info(f"Injected {len(mcp_tool_hints)} MCP tool hints for job {job_id}")
    if system_parts:
        messages.append({"role": "system", "content": "\n\n".join(system_parts)})

    messages.append({"role": "user", "content": job.prompt})
    response = await asyncio.wait_for(
        orchestrator.run(messages, skip_routing=True), timeout=JOB_TIMEOUT
    )

    content = response["choices"][0]["message"].get("content", "")
    summary = content[:2000] if content else "(no output)"

    logger.info(f"Job completed: {job.name} ({job_id}) — {len(content)} chars")
    return summary
