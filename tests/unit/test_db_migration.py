import importlib
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.db.models.job import JobORM
from core.db.models.memory import MemoryORM
from core.db.models.page import PageORM
from core.db.models.session import SessionORM
from core.db.models.workspace import WorkspaceORM


def test_owned_resource_models_include_owner_user_id() -> None:
    models = [SessionORM, MemoryORM, JobORM, WorkspaceORM, PageORM]

    for model in models:
        assert "owner_user_id" in model.__table__.columns.keys()


@pytest.mark.asyncio
async def test_migrate_json_to_db_skips_marker_when_import_step_fails(
    db_engine, monkeypatch, tmp_path: Path
) -> None:
    from core.db import migrate as migrate_module

    db_engine_module = importlib.import_module("core.db.engine")
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(db_engine_module, "async_session_factory", factory)

    async def _raise_import_error(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(migrate_module, "_import_settings", _raise_import_error)

    await migrate_module.migrate_json_to_db(tmp_path)

    assert not (tmp_path / ".migrated").exists()


@pytest.mark.asyncio
async def test_session_import_defaults_owner_user_id_to_none(
    db_engine, monkeypatch, tmp_path: Path
) -> None:
    from core.db import migrate as migrate_module

    db_engine_module = importlib.import_module("core.db.engine")
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(db_engine_module, "async_session_factory", factory)

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    (tmp_path / "sessions.json").write_text(
        '{"sessions": {"session-1": {"title": "Imported", "created_at": "2026-03-30T00:00:00+00:00", "updated_at": "2026-03-30T00:00:00+00:00", "message_count": 1, "preview": "hello"}}}',
        encoding="utf-8",
    )
    (sessions_dir / "session-1.json").write_text(
        '[{"role": "user", "content": "hello"}]',
        encoding="utf-8",
    )

    await migrate_module.migrate_json_to_db(tmp_path)

    async with factory() as session:
        result = await session.execute(select(SessionORM).where(SessionORM.id == "session-1"))
        imported_session = result.scalar_one()

    assert imported_session.owner_user_id is None
