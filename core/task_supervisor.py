import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class TaskRecord:
    name: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str | None = None
    status: str = "running"
    error: str | None = None


class TaskSupervisor:
    def __init__(self) -> None:
        self._tasks: dict[asyncio.Task[Any], TaskRecord] = {}

    def track(
        self,
        task: asyncio.Task[Any],
        *,
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> asyncio.Task[Any]:
        record = TaskRecord(name=name, metadata=metadata or {})
        self._tasks[task] = record
        task.add_done_callback(self._finalize_task)
        return task

    def _finalize_task(self, task: asyncio.Task[Any]) -> None:
        record = self._tasks.get(task)
        if not record:
            return

        record.finished_at = datetime.now(UTC).isoformat()
        if task.cancelled():
            record.status = "cancelled"
        else:
            exc = task.exception()
            if exc is None:
                record.status = "completed"
            else:
                record.status = "failed"
                record.error = str(exc)

    def active_tasks(self) -> list[TaskRecord]:
        return [record for record in self._tasks.values() if record.status == "running"]


task_supervisor = TaskSupervisor()
