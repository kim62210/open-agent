"""Job repository with run record management."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.db.models.job import JobORM, JobRunRecordORM
from core.db.repositories.base import BaseRepository


class JobRepository(BaseRepository[JobORM]):
    """Repository for job persistence and run history."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, JobORM)

    async def get_with_records(self, job_id: str) -> JobORM | None:
        """Fetch a job with all run records eagerly loaded."""
        stmt = (
            select(JobORM)
            .where(JobORM.id == job_id)
            .options(selectinload(JobORM.run_records))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_enabled_jobs(self) -> list[JobORM]:
        """Fetch all enabled jobs."""
        stmt = select(JobORM).where(JobORM.enabled == True)  # noqa: E712
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add_run_record(self, record: JobRunRecordORM) -> JobRunRecordORM:
        """Add a run record and flush."""
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_run_records(self, job_id: str, limit: int = 50) -> list[JobRunRecordORM]:
        """Fetch recent run records for a job, newest first."""
        stmt = (
            select(JobRunRecordORM)
            .where(JobRunRecordORM.job_id == job_id)
            .order_by(JobRunRecordORM.started_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
