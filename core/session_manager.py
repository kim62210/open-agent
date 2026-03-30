import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from open_agent.models.session import SessionInfo, SessionMessage

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._sessions: dict[str, SessionInfo] = {}
        self._owners: dict[str, str | None] = {}

    async def load_from_db(self) -> None:
        """Load all sessions from database into in-memory cache."""
        async with self._lock:
            from core.db.engine import async_session_factory
            from core.db.repositories.session_repo import SessionRepository

            async with async_session_factory() as session:
                repo = SessionRepository(session)
                rows = await repo.get_all_ordered()
                self._sessions.clear()
                self._owners.clear()
                for row in rows:
                    self._sessions[row.id] = SessionInfo(
                        id=row.id,
                        title=row.title,
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                        message_count=row.message_count,
                        preview=row.preview,
                    )
                    self._owners[row.id] = row.owner_user_id
                logger.info(f"Loaded {len(self._sessions)} sessions from database")

    def get_all(self, owner_user_id: str | None = None) -> list[SessionInfo]:
        """All sessions ordered by updated_at descending."""
        sessions = [
            session
            for session_id, session in self._sessions.items()
            if owner_user_id is None or self._owners.get(session_id) == owner_user_id
        ]
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    def get_session(
        self, session_id: str, owner_user_id: str | None = None
    ) -> SessionInfo | None:
        if owner_user_id is not None and self._owners.get(session_id) != owner_user_id:
            return None
        return self._sessions.get(session_id)

    async def create_session(
        self, title: str = "", owner_user_id: str | None = None
    ) -> SessionInfo:
        async with self._lock:
            from core.db.engine import async_session_factory
            from core.db.models.session import SessionORM
            from core.db.repositories.session_repo import SessionRepository

            session_id = uuid.uuid4().hex[:12]
            now = datetime.now(UTC).isoformat()
            info = SessionInfo(
                id=session_id,
                title=title or "New Session",
                created_at=now,
                updated_at=now,
                message_count=0,
                preview="",
            )

            async with async_session_factory() as db:
                repo = SessionRepository(db)
                orm = SessionORM(
                    id=session_id,
                    owner_user_id=owner_user_id,
                    title=info.title,
                    created_at=now,
                    updated_at=now,
                    message_count=0,
                    preview="",
                )
                await repo.create(orm)
                await db.commit()

            self._sessions[session_id] = info
            self._owners[session_id] = owner_user_id
            logger.info(f"Created session: {info.title} ({session_id})")
            return info

    async def get_messages(
        self, session_id: str, owner_user_id: str | None = None
    ) -> list[SessionMessage] | None:
        if session_id not in self._sessions:
            return None
        if owner_user_id is not None and self._owners.get(session_id) != owner_user_id:
            return None

        from core.db.engine import async_session_factory
        from core.db.repositories.session_repo import SessionRepository

        async with async_session_factory() as db:
            repo = SessionRepository(db)
            orm = await repo.get_with_messages(session_id)
            if not orm:
                return []
            messages = []
            for msg_orm in orm.messages:
                extra = msg_orm.extra or {}
                content = msg_orm.content
                # Restore structured content from extra
                if "structured_content" in extra:
                    content = extra.pop("structured_content")
                else:
                    # Try JSON parse for backward compat
                    try:
                        parsed = json.loads(content)
                        if isinstance(parsed, list):
                            content = parsed
                    except (json.JSONDecodeError, TypeError):
                        pass

                msg = SessionMessage(
                    role=msg_orm.role,
                    content=content,
                    name=msg_orm.name,
                    tool_call_id=msg_orm.tool_call_id,
                    timestamp=msg_orm.timestamp,
                    thinking_steps=extra.get("thinking_steps"),
                    display_text=extra.get("display_text"),
                    attached_files=extra.get("attached_files"),
                )
                messages.append(msg)
            return messages

    async def save_messages(
        self, session_id: str, messages: list[SessionMessage], owner_user_id: str | None = None
    ) -> SessionInfo | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            if owner_user_id is not None and self._owners.get(session_id) != owner_user_id:
                return None

            from core.db.engine import async_session_factory
            from core.db.models.session import SessionMessageORM
            from core.db.repositories.session_repo import SessionRepository

            # Build ORM message list
            orm_messages = []
            for m in messages:
                extra: dict = {}
                if m.thinking_steps:
                    extra["thinking_steps"] = m.thinking_steps
                if m.display_text:
                    extra["display_text"] = m.display_text
                if m.attached_files:
                    extra["attached_files"] = m.attached_files

                # Handle structured content (list of dicts)
                if isinstance(m.content, list):
                    content_str = ""
                    extra["structured_content"] = m.content
                else:
                    content_str = m.content

                orm_messages.append(
                    SessionMessageORM(
                        role=m.role if isinstance(m.role, str) else m.role.value,
                        content=content_str,
                        name=m.name,
                        tool_call_id=m.tool_call_id,
                        timestamp=m.timestamp,
                        extra=extra or None,
                    )
                )

            # Update session metadata
            now = datetime.now(UTC).isoformat()
            session.updated_at = now
            session.message_count = len(messages)

            # preview: last assistant message text (up to 100 chars)
            if messages:
                last = messages[-1]
                text = last.content if isinstance(last.content, str) else ""
                if not text and isinstance(last.content, list):
                    for part in last.content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text = part.get("text", "")
                            break
                session.preview = text[:100]
            else:
                session.preview = ""

            # Auto-generate title from first user message
            if session.title == "New Session":
                for m in messages:
                    if m.role == "user":
                        text = m.display_text or ""
                        if not text:
                            text = m.content if isinstance(m.content, str) else ""
                            if not text and isinstance(m.content, list):
                                for part in m.content:
                                    if isinstance(part, dict) and part.get("type") == "text":
                                        text = part.get("text", "")
                                        break
                        if text:
                            session.title = text[:50]
                        elif m.attached_files:
                            names = [f["name"] for f in m.attached_files if isinstance(f, dict)]
                            session.title = f"[첨부] {', '.join(names)}"[:50]
                        break

            # Persist to database
            async with async_session_factory() as db:
                repo = SessionRepository(db)
                await repo.save_messages(session_id, orm_messages)
                await repo.update_preview(
                    session_id,
                    preview=session.preview,
                    message_count=session.message_count,
                    updated_at=now,
                )
                # Also update title if changed
                orm = await repo.get_by_id(session_id)
                if orm:
                    orm.title = session.title
                await db.commit()

            self._sessions[session_id] = session
            return session

    async def update_session(
        self, session_id: str, title: str, owner_user_id: str | None = None
    ) -> SessionInfo | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            if owner_user_id is not None and self._owners.get(session_id) != owner_user_id:
                return None

            from core.db.engine import async_session_factory
            from core.db.repositories.session_repo import SessionRepository

            now = datetime.now(UTC).isoformat()
            session.title = title
            session.updated_at = now

            async with async_session_factory() as db:
                repo = SessionRepository(db)
                orm = await repo.get_by_id(session_id)
                if orm:
                    orm.title = title
                    orm.updated_at = now
                await db.commit()

            self._sessions[session_id] = session
            return session

    async def delete_session(self, session_id: str, owner_user_id: str | None = None) -> bool:
        async with self._lock:
            if session_id not in self._sessions:
                return False
            if owner_user_id is not None and self._owners.get(session_id) != owner_user_id:
                return False

            from core.db.engine import async_session_factory
            from core.db.repositories.session_repo import SessionRepository

            async with async_session_factory() as db:
                repo = SessionRepository(db)
                await repo.delete_by_id(session_id)
                await db.commit()

            self._sessions.pop(session_id)
            self._owners.pop(session_id, None)
            logger.info(f"Deleted session: {session_id}")
            return True


session_manager = SessionManager()
