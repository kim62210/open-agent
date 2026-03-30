import uuid
from datetime import UTC, datetime
from typing import Any

from core.db.models.run import RunEventORM, RunORM
from core.db.repositories.run_repo import RunRepository
from models.run import RunDetail, RunEvent


class RunManager:
    async def create_run(
        self,
        owner_user_id: str,
        request_messages: list[dict[str, Any]],
    ) -> RunDetail:
        from core.db.engine import async_session_factory

        now = datetime.now(UTC).isoformat()
        run_id = uuid.uuid4().hex[:12]

        async with async_session_factory() as session:
            repo = RunRepository(session)
            orm = RunORM(
                id=run_id,
                owner_user_id=owner_user_id,
                status="running",
                request_messages=request_messages,
                created_at=now,
                updated_at=now,
            )
            await repo.create(orm)
            await session.commit()

        return RunDetail(
            id=run_id,
            owner_user_id=owner_user_id,
            status="running",
            request_messages=request_messages,
            created_at=now,
            updated_at=now,
            events=[],
        )

    async def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> RunEvent | None:
        from core.db.engine import async_session_factory

        now = datetime.now(UTC).isoformat()

        async with async_session_factory() as session:
            repo = RunRepository(session)
            run = await repo.get_by_id(run_id)
            if not run:
                return None

            seq = await repo.next_event_seq(run_id)
            event = RunEventORM(
                run_id=run_id,
                seq=seq,
                event_type=event_type,
                payload=payload,
                created_at=now,
            )
            await repo.add_event(event)
            run.updated_at = now
            await session.commit()

        return RunEvent(seq=seq, event_type=event_type, payload=payload, created_at=now)

    async def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        response_payload: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> RunDetail | None:
        from core.db.engine import async_session_factory

        now = datetime.now(UTC).isoformat()

        async with async_session_factory() as session:
            repo = RunRepository(session)
            run = await repo.get_with_events(run_id)
            if not run:
                return None

            run.status = status
            run.response_payload = response_payload
            run.error_message = error_message
            run.updated_at = now
            run.finished_at = now
            await session.commit()

            return self._to_detail(run)

    async def get_run(self, run_id: str, owner_user_id: str) -> RunDetail | None:
        from core.db.engine import async_session_factory

        async with async_session_factory() as session:
            repo = RunRepository(session)
            run = await repo.get_with_events(run_id, owner_user_id=owner_user_id)
            if not run:
                return None
            return self._to_detail(run)

    async def list_runs(self, owner_user_id: str) -> list[RunDetail]:
        from core.db.engine import async_session_factory

        async with async_session_factory() as session:
            repo = RunRepository(session)
            runs = await repo.get_by_owner(owner_user_id)
            details: list[RunDetail] = []
            for run in runs:
                hydrated = await repo.get_with_events(run.id, owner_user_id=owner_user_id)
                if hydrated:
                    details.append(self._to_detail(hydrated))
            return details

    @staticmethod
    def _to_detail(run: RunORM) -> RunDetail:
        return RunDetail(
            id=run.id,
            owner_user_id=run.owner_user_id,
            status=run.status,
            request_messages=run.request_messages or [],
            response_payload=run.response_payload,
            error_message=run.error_message,
            created_at=run.created_at,
            updated_at=run.updated_at,
            finished_at=run.finished_at,
            events=[
                RunEvent(
                    seq=event.seq,
                    event_type=event.event_type,
                    payload=event.payload,
                    created_at=event.created_at,
                )
                for event in run.events
            ],
        )


run_manager = RunManager()
