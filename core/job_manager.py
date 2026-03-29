import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from open_agent.models.job import JobInfo, JobRunRecord

logger = logging.getLogger(__name__)

MAX_HISTORY = 50  # 보관할 최대 이력 수
MAX_CONSECUTIVE_FAILURES = 3  # 연속 실패 시 자동 비활성화 임계값
MAX_PROMPT_LENGTH = 10_000  # 프롬프트 최대 길이


def validate_job_prompt(prompt: str) -> Optional[str]:
    """프롬프트 안전 검증. 문제가 있으면 에러 메시지 반환, 유효하면 None."""
    if not prompt or not prompt.strip():
        return "프롬프트가 비어 있습니다."
    if len(prompt) > MAX_PROMPT_LENGTH:
        return f"프롬프트가 너무 깁니다 ({len(prompt)}자). 최대 {MAX_PROMPT_LENGTH}자까지 허용됩니다."
    # workspace_tools의 DANGEROUS_PATTERNS 재사용
    from open_agent.core.workspace_tools import DANGEROUS_PATTERNS
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, prompt):
            return f"프롬프트에 위험한 패턴이 포함되어 있습니다: {pattern}"
    return None


def _extract_mcp_servers_from_tools(tool_names: List[str]) -> List[str]:
    """allowed_tools에서 MCP 서버명을 추출합니다.

    MCP 도구 네이밍 패턴: "{server_name}__{tool_name}"
    예: "brave-search__brave_web_search" → 서버명 "brave-search"
    """
    servers = set()
    for tool in tool_names:
        if "__" in tool:
            server_name = tool.split("__")[0]
            if server_name:
                servers.add(server_name)
    return sorted(servers)


class JobManager:
    def __init__(self):
        self._jobs: Dict[str, JobInfo] = {}

    async def load_from_db(self) -> None:
        """Load all jobs from database into in-memory cache."""
        from core.db.engine import async_session_factory
        from core.db.repositories.job_repo import JobRepository

        async with async_session_factory() as session:
            repo = JobRepository(session)
            rows = await repo.get_all()
            self._jobs.clear()
            for row in rows:
                # Load run records
                records = await repo.get_run_records(row.id, limit=MAX_HISTORY)
                run_history = [
                    JobRunRecord(
                        run_id=r.run_id,
                        started_at=r.started_at,
                        finished_at=r.finished_at,
                        status=r.status,
                        duration_seconds=r.duration_seconds,
                        summary=r.summary,
                    )
                    for r in records
                ]
                self._jobs[row.id] = JobInfo(
                    id=row.id,
                    name=row.name,
                    description=row.description,
                    prompt=row.prompt,
                    skill_names=row.skill_names or [],
                    mcp_server_names=row.mcp_server_names or [],
                    schedule_type=row.schedule_type,
                    schedule_config=row.schedule_config or {},
                    enabled=row.enabled,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                    next_run_at=row.next_run_at,
                    last_run_at=row.last_run_at,
                    last_run_status=row.last_run_status,
                    last_run_summary=row.last_run_summary,
                    run_count=row.run_count,
                    consecutive_failures=row.consecutive_failures,
                    run_history=run_history,
                )
            logger.info(f"Loaded {len(self._jobs)} jobs from database")

    async def _persist_job(self, job: JobInfo) -> None:
        """Write a single job to database."""
        from core.db.engine import async_session_factory
        from core.db.models.job import JobORM

        async with async_session_factory() as session:
            orm = JobORM(
                id=job.id,
                name=job.name,
                description=job.description,
                prompt=job.prompt,
                skill_names=job.skill_names,
                mcp_server_names=job.mcp_server_names,
                schedule_type=job.schedule_type if isinstance(job.schedule_type, str) else job.schedule_type.value,
                schedule_config=job.schedule_config,
                enabled=job.enabled,
                created_at=job.created_at,
                updated_at=job.updated_at,
                next_run_at=job.next_run_at,
                last_run_at=job.last_run_at,
                last_run_status=job.last_run_status if isinstance(job.last_run_status, (str, type(None))) else (job.last_run_status.value if job.last_run_status else None),
                last_run_summary=job.last_run_summary,
                run_count=job.run_count,
                consecutive_failures=job.consecutive_failures,
            )
            await session.merge(orm)
            await session.commit()

    def get_all_jobs(self) -> List[JobInfo]:
        return list(self._jobs.values())

    def get_job(self, job_id: str) -> Optional[JobInfo]:
        return self._jobs.get(job_id)

    async def create_job(self, req: "CreateJobRequest") -> JobInfo:
        from open_agent.models.job import CreateJobRequest  # noqa: F811

        error = validate_job_prompt(req.prompt)
        if error:
            raise ValueError(error)

        # Auto-delete jobs with same name
        existing = [jid for jid, j in self._jobs.items() if j.name == req.name]
        for jid in existing:
            self._jobs.pop(jid, None)
            from core.db.engine import async_session_factory
            from core.db.repositories.job_repo import JobRepository
            async with async_session_factory() as session:
                repo = JobRepository(session)
                await repo.delete_by_id(jid)
                await session.commit()
            logger.info(f"Auto-replaced existing job with same name: {req.name} ({jid})")

        job_id = uuid.uuid4().hex[:8]
        now = datetime.now(timezone.utc).isoformat()
        job = JobInfo(
            id=job_id,
            name=req.name,
            description=req.description,
            prompt=req.prompt,
            skill_names=req.skill_names,
            mcp_server_names=req.mcp_server_names,
            schedule_type=req.schedule_type,
            schedule_config=req.schedule_config,
            created_at=now,
            updated_at=now,
        )
        self._jobs[job_id] = job
        await self._persist_job(job)
        logger.info(f"Created job: {req.name} ({job_id})")
        return job

    async def update_job(self, job_id: str, req: "UpdateJobRequest") -> Optional[JobInfo]:
        job = self._jobs.get(job_id)
        if not job:
            return None

        update_data = req.model_dump(exclude_none=True)
        for field, value in update_data.items():
            setattr(job, field, value)
        job.updated_at = datetime.now(timezone.utc).isoformat()

        self._jobs[job_id] = job
        await self._persist_job(job)
        logger.info(f"Updated job: {job.name} ({job_id})")
        return job

    async def delete_job(self, job_id: str) -> bool:
        job = self._jobs.pop(job_id, None)
        if not job:
            return False

        from core.db.engine import async_session_factory
        from core.db.repositories.job_repo import JobRepository

        async with async_session_factory() as session:
            repo = JobRepository(session)
            await repo.delete_by_id(job_id)
            await session.commit()

        logger.info(f"Deleted job: {job.name} ({job_id})")
        return True

    async def toggle_job(self, job_id: str) -> Optional[JobInfo]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        job.enabled = not job.enabled
        job.updated_at = datetime.now(timezone.utc).isoformat()
        self._jobs[job_id] = job
        await self._persist_job(job)
        logger.info(f"Toggled job: {job.name} → enabled={job.enabled}")
        return job

    # --- Run state & history ---

    async def start_run(self, job_id: str) -> Optional[str]:
        """Record run start and return run_id."""
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc).isoformat()
        run_id = uuid.uuid4().hex[:8]
        job.last_run_status = "running"
        job.last_run_at = now
        job.last_run_summary = None
        job.updated_at = now
        job.run_history.insert(0, JobRunRecord(
            run_id=run_id, started_at=now, status="running",
        ))
        self._jobs[job_id] = job

        # Persist job + run record
        from core.db.engine import async_session_factory
        from core.db.models.job import JobRunRecordORM
        from core.db.repositories.job_repo import JobRepository

        async with async_session_factory() as session:
            repo = JobRepository(session)
            await repo.add_run_record(JobRunRecordORM(
                run_id=run_id, job_id=job_id, started_at=now, status="running",
            ))
            await session.commit()

        await self._persist_job(job)
        return run_id

    async def finish_run(
        self,
        job_id: str,
        run_id: str,
        status: str,
        summary: Optional[str] = None,
    ) -> Optional[JobInfo]:
        """Record run completion."""
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc).isoformat()
        job.last_run_status = status
        if summary is not None:
            job.last_run_summary = summary[:2000]
        job.run_count += 1
        job.updated_at = now

        if status == "success":
            job.consecutive_failures = 0
        elif status in ("failed", "timeout"):
            job.consecutive_failures += 1
            if job.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                job.enabled = False
                logger.warning(
                    f"Job auto-disabled after {job.consecutive_failures} consecutive failures: "
                    f"{job.name} ({job_id})"
                )

        # Update run record in memory
        for rec in job.run_history:
            if rec.run_id == run_id:
                rec.status = status
                rec.finished_at = now
                rec.summary = summary[:2000] if summary else None
                started = datetime.fromisoformat(rec.started_at)
                finished = datetime.fromisoformat(now)
                rec.duration_seconds = round((finished - started).total_seconds(), 1)
                break

        if len(job.run_history) > MAX_HISTORY:
            job.run_history = job.run_history[:MAX_HISTORY]

        self._jobs[job_id] = job

        # Update run record in DB
        from core.db.engine import async_session_factory
        from core.db.models.job import JobRunRecordORM

        async with async_session_factory() as session:
            orm_rec = await session.get(JobRunRecordORM, run_id)
            if orm_rec:
                orm_rec.status = status
                orm_rec.finished_at = now
                orm_rec.summary = summary[:2000] if summary else None
                started = datetime.fromisoformat(orm_rec.started_at)
                finished = datetime.fromisoformat(now)
                orm_rec.duration_seconds = round((finished - started).total_seconds(), 1)
            await session.commit()

        await self._persist_job(job)
        return job

    def get_run_history(self, job_id: str, limit: int = 20) -> List[JobRunRecord]:
        job = self._jobs.get(job_id)
        if not job:
            return []
        return job.run_history[:limit]

    async def set_next_run_at(self, job_id: str, next_run: Optional[str]) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        job.next_run_at = next_run
        self._jobs[job_id] = job
        await self._persist_job(job)

    # --- LLM 도구 통합 ---

    async def get_job_tools(self) -> List[Dict[str, Any]]:
        """채팅에서 Scheduled Task를 관리할 수 있는 LLM 도구 정의를 반환합니다."""
        from open_agent.core.skill_manager import skill_manager
        from open_agent.core.mcp_manager import mcp_manager

        # 동적 컨텍스트: 사용 가능한 스킬 목록
        skills = [s for s in skill_manager.get_all_skills() if s.enabled]
        skills_info = ""
        if skills:
            lines = ["\n\n사용 가능한 스킬:"]
            for s in skills:
                tools_note = f" (도구: {', '.join(s.allowed_tools)})" if s.allowed_tools else ""
                lines.append(f"  - {s.name}: {s.description}{tools_note}")
            skills_info = "\n".join(lines)

        # 동적 컨텍스트: 연결된 MCP 서버 + 도구 목록 (LLM이 적절한 서버 선택 가능하도록)
        servers = [s for s in mcp_manager.get_all_server_statuses() if s.status.value == "connected"]
        mcp_info = ""
        if servers:
            lines = ["\n\n연결된 MCP 서버 (작업에 필요한 서버만 선택하세요, 불필요한 서버는 포함하지 마세요):"]
            for s in servers:
                tools = await self._get_server_tool_names(s.name, mcp_manager)
                tools_str = f" — 도구: {', '.join(tools)}" if tools else ""
                lines.append(f"  - {s.name}{tools_str}")
            mcp_info = "\n".join(lines)

        # skill_names enum 생성
        skill_name_list = [s.name for s in skills]

        return [
            {
                "type": "function",
                "function": {
                    "name": "create_scheduled_task",
                    "description": (
                        "예약 실행 작업(Scheduled Task)을 생성합니다. "
                        "사용자가 '매일 아침 9시에 뉴스 요약해줘', '30분마다 서버 상태 체크해줘' 등 "
                        "반복/예약 작업을 요청하면 이 도구로 Job을 등록합니다. "
                        "반복 잡(daily/interval/cron)은 테스트 실행 없이 바로 활성화됩니다. 실제 실행은 스케줄된 시간에만 수행됩니다. "
                        "prompt는 AI 에이전트가 독립적으로 실행할 수 있는 명확하고 구체적인 지시여야 합니다. "
                        "작업에 적합한 스킬이 있으면 skill_names에 지정하세요. "
                        "작업 실행에 필요한 MCP 서버가 있으면 mcp_server_names에 해당 서버만 선택적으로 포함하세요. "
                        "모든 MCP 서버를 포함하지 말고, 작업에 실제로 필요한 도구를 제공하는 서버만 지정하세요. "
                        "스킬의 allowed_tools에서 MCP 서버는 자동 추출되므로, "
                        "스킬 없이 MCP 도구를 직접 사용해야 하는 경우에만 해당 서버를 명시하세요. "
                        "schedule_type: once(1회 실행), interval(N분 간격), daily(매일 특정 시각), "
                        "weekly(매주 특정 요일/시각), cron(cron 표현식). "
                        "schedule_config 예시: "
                        "once → {\"run_at\": \"2026-02-26T14:32:00\"} (특정 시각에 1회 예약, 생략 시 즉시 실행), "
                        "interval → {\"interval_minutes\": 30}, "
                        "daily → {\"hour\": 9, \"minute\": 0}, "
                        "weekly → {\"weekday\": 1, \"hour\": 9, \"minute\": 0} (0=일~6=토), "
                        "cron → {\"cron_expr\": \"0 9 * * 1-5\"}. "
                        "시각은 시스템 로컬 타임존 기준입니다. "
                        "다른 타임존을 사용하려면 schedule_config에 \"timezone\" 키를 추가하세요 "
                        "(예: {\"cron_expr\": \"0 9 * * *\", \"timezone\": \"US/Eastern\"})."
                        + skills_info
                        + mcp_info
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "작업 이름 (간결하게, 예: '뉴스 요약', '서버 상태 체크')"},
                            "prompt": {"type": "string", "description": "실행할 프롬프트 — AI 에이전트에게 전달될 지시 내용"},
                            "description": {"type": "string", "description": "작업 설명 (선택)"},
                            "skill_names": {
                                "type": "array",
                                "items": (
                                    {"type": "string", "enum": skill_name_list}
                                    if skill_name_list
                                    else {"type": "string"}
                                ),
                                "description": "사용할 스킬 이름 목록 (선택, 등록된 스킬명)",
                            },
                            "mcp_server_names": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "작업에 필요한 MCP 서버만 선택 (전체 포함 금지, 스킬 사용 시 자동 추출되므로 보통 생략)",
                            },
                            "schedule_type": {
                                "type": "string",
                                "enum": ["once", "interval", "daily", "weekly", "cron"],
                                "description": "스케줄 유형",
                            },
                            "schedule_config": {
                                "type": "object",
                                "description": "스케줄 상세 설정 (유형별 키: interval_minutes, hour, minute, weekday, cron_expr)",
                            },
                        },
                        "required": ["name", "prompt", "schedule_type", "schedule_config"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_scheduled_tasks",
                    "description": (
                        "등록된 Scheduled Task 목록을 조회합니다. "
                        "각 작업의 이름, 스케줄, 활성화 상태, 마지막 실행 결과를 확인할 수 있습니다."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "delete_scheduled_task",
                    "description": (
                        "등록된 Scheduled Task를 삭제합니다. "
                        "삭제할 작업의 ID 또는 이름을 지정합니다. "
                        "이름으로 지정하면 해당 이름의 작업을 찾아 삭제합니다."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "job_id": {"type": "string", "description": "삭제할 작업 ID (id 또는 name 중 하나 필수)"},
                            "name": {"type": "string", "description": "삭제할 작업 이름 (id 또는 name 중 하나 필수)"},
                        },
                    },
                },
            },
        ]

    async def handle_tool_call(self, function_name: str, args: Dict[str, Any]) -> str:
        """LLM 도구 호출을 처리합니다."""
        if function_name == "create_scheduled_task":
            return await self._handle_create_job(args)
        elif function_name == "list_scheduled_tasks":
            return self._handle_list_jobs()
        elif function_name == "delete_scheduled_task":
            return await self._handle_delete_job(args)
        return f"Error: Unknown job tool '{function_name}'"

    async def _handle_create_job(self, args: Dict[str, Any]) -> str:
        from open_agent.core.skill_manager import skill_manager
        from open_agent.models.job import CreateJobRequest

        # 1) 스킬 이름 검증 (활성화된 스킬만 허용)
        skill_names = args.get("skill_names", [])
        if skill_names:
            enabled_skills = {s.name for s in skill_manager.get_all_skills() if s.enabled}
            missing = [s for s in skill_names if s not in enabled_skills]
            if missing:
                return (
                    f"Error: 존재하지 않거나 비활성화된 스킬이 포함되어 있습니다: {', '.join(missing)}\n"
                    f"활성화된 스킬 목록: {', '.join(sorted(enabled_skills))}"
                )

        # 2) 프롬프트 검증
        prompt_error = validate_job_prompt(args.get("prompt", ""))
        if prompt_error:
            return f"Error: {prompt_error}"

        try:
            from open_agent.core.mcp_manager import mcp_manager

            # 스킬의 allowed_tools에서 MCP 서버 자동 추출
            auto_mcp_servers: set[str] = set()
            for sn in skill_names:
                skill = skill_manager.get_skill(sn)
                if skill and skill.allowed_tools:
                    auto_mcp_servers.update(
                        _extract_mcp_servers_from_tools(skill.allowed_tools)
                    )

            # 사용자(LLM) 지정 + 스킬에서 자동 추출 병합
            explicit_mcp = args.get("mcp_server_names", [])
            final_mcp_servers = sorted(set(explicit_mcp) | auto_mcp_servers)

            req = CreateJobRequest(
                name=args["name"],
                prompt=args["prompt"],
                description=args.get("description", ""),
                skill_names=skill_names,
                mcp_server_names=final_mcp_servers,
                schedule_type=args.get("schedule_type", "once"),
                schedule_config=args.get("schedule_config", {}),
            )
            # 2) 비활성 상태로 생성 (테스트 후 활성화)
            job = await self.create_job(req)
            job.enabled = False
            job.updated_at = datetime.now(timezone.utc).isoformat()
            self._jobs[job.id] = job
            await self._persist_job(job)

            schedule_desc = self._format_schedule_text(job)

            # 3) once + run_at(미래 예약)이면 테스트 실행 없이 바로 스케줄 등록
            is_scheduled_once = (
                req.schedule_type == "once"
                and req.schedule_config.get("run_at")
            )
            if is_scheduled_once:
                job.enabled = True
                job.updated_at = datetime.now(timezone.utc).isoformat()
                self._jobs[job.id] = job
                await self._persist_job(job)

                try:
                    from open_agent.core.job_scheduler import job_scheduler
                    job_scheduler.refresh_job(job.id)
                except Exception as e:
                    logger.warning(f"Failed to register job with scheduler: {e}")

                # refresh 후 next_run_at 다시 읽기
                refreshed = self.get_job(job.id)
                next_run_display = refreshed.next_run_at if refreshed else "알 수 없음"

                return (
                    f"Scheduled Task가 예약되었습니다.\n"
                    f"- ID: {job.id}\n"
                    f"- 이름: {job.name}\n"
                    f"- 예약 시각: {next_run_display}\n"
                    f"- 상태: 활성화됨 (예약 대기 중)"
                )

            # 4) 반복 잡(daily/interval/cron): 테스트 실행 없이 바로 활성화
            #    실제 실행은 스케줄된 시간에만 수행. 즉시 재생은 사용자가 명시적으로 요청할 때만.
            job.enabled = True
            job.updated_at = datetime.now(timezone.utc).isoformat()
            self._jobs[job.id] = job
            await self._persist_job(job)

            try:
                from open_agent.core.job_scheduler import job_scheduler
                job_scheduler.refresh_job(job.id)
            except Exception as e:
                logger.warning(f"Failed to register job with scheduler: {e}")

            return (
                f"Scheduled Task가 생성되었습니다.\n"
                f"- ID: {job.id}\n"
                f"- 이름: {job.name}\n"
                f"- 스케줄: {schedule_desc}\n"
                f"- 상태: 활성화됨\n"
                f"- 참고: 실제 실행은 스케줄된 시간에 수행됩니다. 즉시 실행하려면 UI에서 'Run Now'를 사용하세요."
                )

        except Exception as e:
            return f"Error: Job 생성 실패 — {e}"

    async def _test_run_job(self, job_id: str) -> Dict[str, Any]:
        """Job 프롬프트를 1회 테스트 실행합니다."""
        try:
            from open_agent.core.job_executor import execute_job
            from open_agent.core.job_manager import job_manager as mgr

            run_id = await mgr.start_run(job_id)
            if not run_id:
                return {"success": False, "error": "Failed to start test run", "summary": ""}

            try:
                summary = await execute_job(job_id)
                await mgr.finish_run(job_id, run_id, "success", summary)
                return {"success": True, "summary": summary, "error": ""}
            except asyncio.TimeoutError:
                await mgr.finish_run(job_id, run_id, "timeout", "테스트 실행 타임아웃")
                return {"success": False, "error": "실행 시간이 초과되었습니다 (300초)", "summary": ""}
            except asyncio.CancelledError:
                await mgr.finish_run(job_id, run_id, "cancelled", "테스트 실행 취소됨")
                return {"success": False, "error": "실행이 취소되었습니다", "summary": ""}
            except Exception as e:
                error_msg = str(e)[:300]
                await mgr.finish_run(job_id, run_id, "failed", f"테스트 실패: {error_msg}")
                return {"success": False, "error": error_msg, "summary": ""}
        except Exception as e:
            return {"success": False, "error": str(e)[:300], "summary": ""}

    def _handle_list_jobs(self) -> str:
        jobs = self.get_all_jobs()
        if not jobs:
            return "등록된 Scheduled Task가 없습니다."

        lines = [f"등록된 Scheduled Task ({len(jobs)}개):"]
        for job in jobs:
            status = "활성" if job.enabled else "비활성"
            schedule = self._format_schedule_text(job)
            last_run = job.last_run_status or "미실행"
            lines.append(
                f"- [{job.id}] {job.name} | {schedule} | {status} | 마지막: {last_run}"
            )
        return "\n".join(lines)

    async def _handle_delete_job(self, args: Dict[str, Any]) -> str:
        job_id = args.get("job_id")
        name = args.get("name")

        # 이름으로 검색
        if not job_id and name:
            for job in self._jobs.values():
                if job.name == name:
                    job_id = job.id
                    break
            if not job_id:
                return f"Error: '{name}' 이름의 Job을 찾을 수 없습니다."

        if not job_id:
            return "Error: job_id 또는 name을 지정해야 합니다."

        job = self.get_job(job_id)
        if not job:
            return f"Error: ID '{job_id}'의 Job을 찾을 수 없습니다."

        job_name = job.name

        # 실행 중이면 중지
        try:
            from open_agent.core.job_scheduler import job_scheduler
            if job_id in job_scheduler._running_tasks:
                await job_scheduler.stop_job(job_id)
        except Exception:
            pass

        await self.delete_job(job_id)
        return f"Scheduled Task '{job_name}' (ID: {job_id})이 삭제되었습니다."

    @staticmethod
    async def _get_server_tool_names(server_name: str, mcp_manager) -> List[str]:
        """MCP 서버의 도구 이름 목록을 가져옵니다."""
        try:
            tools = await mcp_manager.get_tools_for_server(server_name)
            return [t.name for t in tools]
        except Exception:
            return []

    @staticmethod
    def _format_schedule_text(job: JobInfo) -> str:
        cfg = job.schedule_config
        if job.schedule_type == "interval":
            return f"{cfg.get('interval_minutes', '?')}분 간격"
        elif job.schedule_type == "daily":
            return f"매일 {cfg.get('hour', 0):02d}:{cfg.get('minute', 0):02d}"
        elif job.schedule_type == "weekly":
            days = ["일", "월", "화", "수", "목", "금", "토"]
            day = days[int(cfg.get("weekday", 0))]
            return f"매주 {day}요일 {cfg.get('hour', 0):02d}:{cfg.get('minute', 0):02d}"
        elif job.schedule_type == "cron":
            return f"cron: {cfg.get('cron_expr', '* * * * *')}"
        elif job.schedule_type == "once":
            run_at = cfg.get("run_at")
            if run_at:
                return f"1회 예약: {run_at}"
            return "1회 즉시 실행"
        return "1회 실행"


SCHEDULED_TASK_TOOL_NAMES = {"create_scheduled_task", "list_scheduled_tasks", "delete_scheduled_task"}

job_manager = JobManager()
