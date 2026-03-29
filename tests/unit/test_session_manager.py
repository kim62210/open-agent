"""SessionManager unit tests — async DB-backed."""

import pytest

from open_agent.core.session_manager import SessionManager
from open_agent.models.session import SessionMessage


class TestSessionCreate:
    """Session creation tests."""

    async def test_create_session_default_title(self, session_manager: SessionManager):
        """Creating without title defaults to 'New Session'."""
        session = await session_manager.create_session()

        assert session.id
        assert session.title == "New Session"
        assert session.message_count == 0
        assert session.preview == ""
        assert session.created_at
        assert session.updated_at

    async def test_create_session_custom_title(self, session_manager: SessionManager):
        """Custom title is stored correctly."""
        session = await session_manager.create_session(title="테스트 세션")

        assert session.title == "테스트 세션"

    async def test_create_session_persists_to_db(self, session_manager: SessionManager):
        """Session persists in DB and survives reload into cache."""
        session = await session_manager.create_session(title="DB 테스트")

        # Verify in-memory cache
        assert session_manager.get_session(session.id) is not None
        assert session_manager.get_session(session.id).title == "DB 테스트"

        # Verify DB persistence by reloading
        session_manager._sessions.clear()
        await session_manager.load_from_db()
        reloaded = session_manager.get_session(session.id)
        assert reloaded is not None
        assert reloaded.title == "DB 테스트"


class TestSessionGet:
    """Session retrieval tests."""

    async def test_get_existing_session(self, session_manager: SessionManager):
        """Retrieve an existing session by ID."""
        created = await session_manager.create_session(title="조회 테스트")
        result = session_manager.get_session(created.id)

        assert result is not None
        assert result.id == created.id
        assert result.title == "조회 테스트"

    async def test_get_nonexistent_session(self, session_manager: SessionManager):
        """Querying a non-existent ID returns None."""
        result = session_manager.get_session("nonexistent-id")
        assert result is None

    async def test_get_all_sessions_empty(self, session_manager: SessionManager):
        """Empty manager returns an empty list."""
        result = session_manager.get_all()
        assert result == []

    async def test_get_all_sessions_ordered(self, session_manager: SessionManager):
        """Sessions are returned ordered by updated_at descending."""
        s1 = await session_manager.create_session(title="첫 번째")
        s2 = await session_manager.create_session(title="두 번째")
        s3 = await session_manager.create_session(title="세 번째")

        result = session_manager.get_all()
        assert len(result) == 3
        assert result[0].id == s3.id
        assert result[1].id == s2.id
        assert result[2].id == s1.id


class TestSessionMessages:
    """Message save/get tests."""

    async def test_get_messages_empty_session(self, session_manager: SessionManager):
        """Empty session returns an empty message list."""
        session = await session_manager.create_session()
        messages = await session_manager.get_messages(session.id)

        assert messages == []

    async def test_get_messages_nonexistent_session(self, session_manager: SessionManager):
        """Non-existent session returns None for messages."""
        result = await session_manager.get_messages("nonexistent-id")
        assert result is None

    async def test_save_and_get_messages(self, session_manager: SessionManager):
        """Messages are saved and retrieved with correct content."""
        session = await session_manager.create_session()
        msgs = [
            SessionMessage(role="user", content="안녕하세요"),
            SessionMessage(role="assistant", content="반갑습니다!"),
        ]

        result = await session_manager.save_messages(session.id, msgs)
        assert result is not None
        assert result.message_count == 2
        assert result.preview == "반갑습니다!"

        loaded = await session_manager.get_messages(session.id)
        assert loaded is not None
        assert len(loaded) == 2
        assert loaded[0].role == "user"
        assert loaded[0].content == "안녕하세요"
        assert loaded[1].role == "assistant"

    async def test_save_messages_auto_title(self, session_manager: SessionManager):
        """Default-titled session auto-generates title from first user message."""
        session = await session_manager.create_session()
        assert session.title == "New Session"

        msgs = [
            SessionMessage(role="user", content="Python 3.13의 새로운 기능에 대해 알려주세요"),
            SessionMessage(role="assistant", content="Python 3.13에서는..."),
        ]
        result = await session_manager.save_messages(session.id, msgs)
        assert result is not None
        assert result.title != "New Session"
        assert "Python" in result.title

    async def test_save_messages_nonexistent_session(self, session_manager: SessionManager):
        """Saving messages to non-existent session returns None."""
        msgs = [SessionMessage(role="user", content="test")]
        result = await session_manager.save_messages("nonexistent-id", msgs)
        assert result is None


class TestSessionDelete:
    """Session deletion tests."""

    async def test_delete_existing_session(self, session_manager: SessionManager):
        """Deleting a session removes it from cache and DB."""
        session = await session_manager.create_session(title="삭제 대상")

        result = await session_manager.delete_session(session.id)
        assert result is True
        assert session_manager.get_session(session.id) is None

        # Verify not in DB either
        session_manager._sessions.clear()
        await session_manager.load_from_db()
        assert session_manager.get_session(session.id) is None

    async def test_delete_nonexistent_session(self, session_manager: SessionManager):
        """Deleting a non-existent session returns False."""
        result = await session_manager.delete_session("nonexistent-id")
        assert result is False


class TestSessionUpdate:
    """Session update tests."""

    async def test_update_title(self, session_manager: SessionManager):
        """Title update persists in cache."""
        session = await session_manager.create_session(title="원래 제목")

        result = await session_manager.update_session(session.id, "변경된 제목")
        assert result is not None
        assert result.title == "변경된 제목"

        reloaded = session_manager.get_session(session.id)
        assert reloaded is not None
        assert reloaded.title == "변경된 제목"

    async def test_update_nonexistent_session(self, session_manager: SessionManager):
        """Updating a non-existent session returns None."""
        result = await session_manager.update_session("nonexistent-id", "새 제목")
        assert result is None
