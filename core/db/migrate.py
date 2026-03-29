"""One-time migration from JSON files to database."""

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

logger = logging.getLogger(__name__)


async def migrate_json_to_db(data_dir: Path) -> None:
    """Import existing JSON data into the database.

    Skips if .migrated marker exists or if DB already has data.
    Individual file failures are logged but do not block the rest.
    """
    marker = data_dir / ".migrated"
    if marker.exists():
        logger.debug("Migration marker found, skipping JSON import")
        return

    from core.db.engine import async_session_factory
    from core.db.models import (
        JobORM,
        JobRunRecordORM,
        MCPConfigORM,
        MemoryORM,
        PageORM,
        SessionMessageORM,
        SessionORM,
        SettingsORM,
        SkillConfigORM,
        WorkspaceORM,
    )

    imported_any = False

    async with async_session_factory() as session:
        # --- settings.json ---
        try:
            imported_any |= await _import_settings(
                session, data_dir / "settings.json", SettingsORM
            )
        except Exception as exc:
            logger.exception("Failed to import settings.json", exc_info=exc)

        # --- sessions.json + sessions/{id}.json ---
        try:
            imported_any |= await _import_sessions(
                session, data_dir, SessionORM, SessionMessageORM
            )
        except Exception as exc:
            logger.exception("Failed to import sessions.json", exc_info=exc)

        # --- memories.json ---
        try:
            imported_any |= await _import_memories(
                session, data_dir / "memories.json", MemoryORM
            )
        except Exception as exc:
            logger.exception("Failed to import memories.json", exc_info=exc)

        # --- jobs.json ---
        try:
            imported_any |= await _import_jobs(
                session, data_dir / "jobs.json", JobORM, JobRunRecordORM
            )
        except Exception as exc:
            logger.exception("Failed to import jobs.json", exc_info=exc)

        # --- workspaces.json ---
        try:
            imported_any |= await _import_workspaces(
                session, data_dir / "workspaces.json", WorkspaceORM
            )
        except Exception as exc:
            logger.exception("Failed to import workspaces.json", exc_info=exc)

        # --- pages.json ---
        try:
            imported_any |= await _import_pages(
                session, data_dir / "pages.json", PageORM
            )
        except Exception as exc:
            logger.exception("Failed to import pages.json", exc_info=exc)

        # --- skills.json ---
        try:
            imported_any |= await _import_skills(
                session, data_dir / "skills.json", SkillConfigORM
            )
        except Exception as exc:
            logger.exception("Failed to import skills.json", exc_info=exc)

        # --- mcp.json ---
        try:
            imported_any |= await _import_mcp(
                session, data_dir / "mcp.json", MCPConfigORM
            )
        except Exception as exc:
            logger.exception("Failed to import mcp.json", exc_info=exc)

        await session.commit()

    marker.touch()
    if imported_any:
        logger.info("JSON to DB migration complete")
    else:
        logger.debug("No JSON data to migrate")


def _read_json(path: Path) -> dict[str, Any] | None:
    """Read and parse a JSON file, returning None if missing or invalid."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Cannot read %s: %s", path.name, exc)
        return None


async def _table_is_empty(session: Any, orm_class: type) -> bool:
    """Return True if the table has zero rows."""
    result = await session.execute(select(func.count()).select_from(orm_class))
    return result.scalar_one() == 0


# ── Individual importers ─────────────────────────────────────────────


async def _import_settings(session: Any, path: Path, orm_class: type) -> bool:
    data = _read_json(path)
    if data is None:
        return False
    if not await _table_is_empty(session, orm_class):
        logger.debug("settings table already has data, skipping")
        return False

    session.add(orm_class(id=1, data=data))
    logger.info("Imported settings.json")
    return True


async def _import_sessions(
    session: Any,
    data_dir: Path,
    session_orm: type,
    message_orm: type,
) -> bool:
    data = _read_json(data_dir / "sessions.json")
    if data is None:
        return False
    sessions_dict: dict = data.get("sessions", {})
    if not sessions_dict:
        return False
    if not await _table_is_empty(session, session_orm):
        logger.debug("sessions table already has data, skipping")
        return False

    sessions_dir = data_dir / "sessions"
    imported_count = 0

    for sid, info in sessions_dict.items():
        orm = session_orm(
            id=sid,
            title=info.get("title", "New Session"),
            created_at=info.get("created_at", ""),
            updated_at=info.get("updated_at", ""),
            message_count=info.get("message_count", 0),
            preview=info.get("preview", ""),
        )
        session.add(orm)

        # Load messages from sessions/{id}.json
        msg_file = sessions_dir / f"{sid}.json"
        msg_data = _read_json(msg_file)
        if msg_data and isinstance(msg_data, list):
            messages = msg_data
        elif msg_data and isinstance(msg_data, dict):
            messages = msg_data.get("messages", [])
        else:
            messages = []

        for seq, msg in enumerate(messages):
            content = msg.get("content", "")
            if isinstance(content, (list, dict)):
                content = json.dumps(content, ensure_ascii=False)

            extra: dict[str, Any] = {}
            for key in ("thinking_steps", "display_text", "attached_files"):
                if msg.get(key) is not None:
                    extra[key] = msg[key]

            session.add(
                message_orm(
                    session_id=sid,
                    seq=seq,
                    role=msg.get("role", "user"),
                    content=content,
                    name=msg.get("name"),
                    tool_call_id=msg.get("tool_call_id"),
                    timestamp=msg.get("timestamp"),
                    extra=extra or None,
                )
            )

        imported_count += 1

    logger.info("Imported %d sessions from sessions.json", imported_count)
    return imported_count > 0


async def _import_memories(session: Any, path: Path, orm_class: type) -> bool:
    data = _read_json(path)
    if data is None:
        return False
    memories: list = data.get("memories", [])
    if not memories:
        return False
    if not await _table_is_empty(session, orm_class):
        logger.debug("memories table already has data, skipping")
        return False

    for mem in memories:
        session.add(
            orm_class(
                id=mem["id"],
                content=mem.get("content", ""),
                category=mem.get("category", "fact"),
                confidence=mem.get("confidence", 0.7),
                source=mem.get("source", "llm_inference"),
                is_pinned=mem.get("is_pinned", False),
                access_count=mem.get("access_count", 0),
                created_at=mem.get("created_at", ""),
                updated_at=mem.get("updated_at", ""),
            )
        )

    logger.info("Imported %d memories from memories.json", len(memories))
    return True


async def _import_jobs(
    session: Any,
    path: Path,
    job_orm: type,
    run_record_orm: type,
) -> bool:
    data = _read_json(path)
    if data is None:
        return False
    jobs_dict: dict = data.get("jobs", {})
    if not jobs_dict:
        return False
    if not await _table_is_empty(session, job_orm):
        logger.debug("jobs table already has data, skipping")
        return False

    for jid, info in jobs_dict.items():
        session.add(
            job_orm(
                id=jid,
                name=info.get("name", ""),
                description=info.get("description", ""),
                prompt=info.get("prompt", ""),
                skill_names=info.get("skill_names", []),
                mcp_server_names=info.get("mcp_server_names", []),
                schedule_type=info.get("schedule_type", "once"),
                schedule_config=info.get("schedule_config", {}),
                enabled=info.get("enabled", True),
                created_at=info.get("created_at", ""),
                updated_at=info.get("updated_at", ""),
                next_run_at=info.get("next_run_at"),
                last_run_at=info.get("last_run_at"),
                last_run_status=info.get("last_run_status"),
                last_run_summary=info.get("last_run_summary"),
                run_count=info.get("run_count", 0),
                consecutive_failures=info.get("consecutive_failures", 0),
            )
        )

        for record in info.get("run_history", []):
            session.add(
                run_record_orm(
                    run_id=record["run_id"],
                    job_id=jid,
                    started_at=record.get("started_at", ""),
                    finished_at=record.get("finished_at"),
                    status=record.get("status", "failed"),
                    duration_seconds=record.get("duration_seconds"),
                    summary=record.get("summary"),
                )
            )

    logger.info("Imported %d jobs from jobs.json", len(jobs_dict))
    return True


async def _import_workspaces(session: Any, path: Path, orm_class: type) -> bool:
    data = _read_json(path)
    if data is None:
        return False
    workspaces: dict = data.get("workspaces", {})
    if not workspaces:
        return False
    if not await _table_is_empty(session, orm_class):
        logger.debug("workspaces table already has data, skipping")
        return False

    for wid, info in workspaces.items():
        session.add(
            orm_class(
                id=wid,
                name=info.get("name", ""),
                path=info.get("path", ""),
                description=info.get("description", ""),
                created_at=info.get("created_at", ""),
                is_active=info.get("is_active", False),
            )
        )

    logger.info("Imported %d workspaces from workspaces.json", len(workspaces))
    return True


async def _import_pages(session: Any, path: Path, orm_class: type) -> bool:
    data = _read_json(path)
    if data is None:
        return False
    pages: dict = data.get("pages", {})
    if not pages:
        return False
    if not await _table_is_empty(session, orm_class):
        logger.debug("pages table already has data, skipping")
        return False

    count = _collect_pages(pages, session, orm_class, parent_id=None, counter=0)

    logger.info("Imported %d pages from pages.json", count)
    return count > 0


def _collect_pages(
    pages_dict: dict,
    session: Any,
    orm_class: type,
    parent_id: str | None,
    counter: int,
) -> int:
    """Recursively flatten nested folder structure into flat ORM rows."""
    for pid, info in pages_dict.items():
        content_type = info.get("content_type", "html")

        session.add(
            orm_class(
                id=pid,
                name=info.get("name", ""),
                description=info.get("description", ""),
                content_type=content_type,
                parent_id=parent_id or info.get("parent_id"),
                filename=info.get("filename"),
                size_bytes=info.get("size_bytes", 0),
                entry_file=info.get("entry_file"),
                url=info.get("url"),
                frameable=info.get("frameable"),
                published=info.get("published", False),
                host_password_hash=info.get("host_password_hash"),
            )
        )
        counter += 1

        # Recurse into nested children if folder contains sub-pages
        children = info.get("children", {})
        if children and isinstance(children, dict):
            counter = _collect_pages(children, session, orm_class, parent_id=pid, counter=counter)

    return counter


async def _import_skills(session: Any, path: Path, orm_class: type) -> bool:
    data = _read_json(path)
    if data is None:
        return False
    disabled: list = data.get("disabled", [])
    if not disabled:
        return False
    if not await _table_is_empty(session, orm_class):
        logger.debug("skill_configs table already has data, skipping")
        return False

    for skill_name in disabled:
        session.add(
            orm_class(
                name=skill_name,
                description="",
                path="",
                enabled=False,
            )
        )

    logger.info("Imported %d disabled skills from skills.json", len(disabled))
    return True


async def _import_mcp(session: Any, path: Path, orm_class: type) -> bool:
    data = _read_json(path)
    if data is None:
        return False
    servers: dict = data.get("mcpServers", {})
    if not servers:
        return False
    if not await _table_is_empty(session, orm_class):
        logger.debug("mcp_configs table already has data, skipping")
        return False

    for name, config in servers.items():
        session.add(
            orm_class(
                name=name,
                transport=config.get("transport", "stdio"),
                command=config.get("command"),
                args=config.get("args"),
                env=config.get("env"),
                url=config.get("url"),
                headers=config.get("headers"),
                enabled=config.get("enabled", True),
            )
        )

    logger.info("Imported %d MCP servers from mcp.json", len(servers))
    return True
