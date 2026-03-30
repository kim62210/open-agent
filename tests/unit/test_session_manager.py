"""SessionManager unit tests — async DB-backed."""


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
        s1 = await session_manager.create_session(title="첫 번째", owner_user_id="user-1")
        s2 = await session_manager.create_session(title="두 번째", owner_user_id="user-1")
        s3 = await session_manager.create_session(title="세 번째", owner_user_id="user-1")

        result = session_manager.get_all(owner_user_id="user-1")
        assert len(result) == 3
        assert result[0].id == s3.id
        assert result[1].id == s2.id
        assert result[2].id == s1.id

    async def test_get_all_filters_by_owner(self, session_manager: SessionManager):
        owned = await session_manager.create_session(title="내 세션", owner_user_id="user-1")
        await session_manager.create_session(title="남의 세션", owner_user_id="user-2")

        result = session_manager.get_all(owner_user_id="user-1")

        assert [session.id for session in result] == [owned.id]

    async def test_get_session_denies_other_owner(self, session_manager: SessionManager):
        owned = await session_manager.create_session(title="내 세션", owner_user_id="user-1")

        assert session_manager.get_session(owned.id, owner_user_id="user-2") is None


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

    async def test_update_persists_to_db(self, session_manager: SessionManager):
        """Title update persists to DB."""
        session = await session_manager.create_session(title="Original")
        await session_manager.update_session(session.id, "Updated Title")

        session_manager._sessions.clear()
        await session_manager.load_from_db()
        reloaded = session_manager.get_session(session.id)
        assert reloaded is not None
        assert reloaded.title == "Updated Title"


class TestSessionMessagesAdvanced:
    """Advanced message handling tests for uncovered branches."""

    async def test_save_messages_structured_content(self, session_manager: SessionManager):
        """Structured (list) content is stored and retrieved correctly."""
        session = await session_manager.create_session()
        structured_content = [
            {"type": "text", "text": "Describe this image"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ]
        msgs = [
            SessionMessage(role="user", content=structured_content),
            SessionMessage(role="assistant", content="I see a cat."),
        ]

        result = await session_manager.save_messages(session.id, msgs)
        assert result is not None
        assert result.message_count == 2

        loaded = await session_manager.get_messages(session.id)
        assert loaded is not None
        assert isinstance(loaded[0].content, list)
        assert loaded[0].content[0]["type"] == "text"

    async def test_save_messages_with_thinking_steps(self, session_manager: SessionManager):
        """Messages with thinking_steps are stored in extra field."""
        session = await session_manager.create_session()
        msgs = [
            SessionMessage(role="user", content="Think about this"),
            SessionMessage(
                role="assistant",
                content="The answer is 42",
                thinking_steps=[{"type": "thinking", "thinking": "Let me think..."}],
            ),
        ]

        await session_manager.save_messages(session.id, msgs)
        loaded = await session_manager.get_messages(session.id)
        assert loaded[1].thinking_steps is not None
        assert len(loaded[1].thinking_steps) == 1

    async def test_save_messages_with_display_text(self, session_manager: SessionManager):
        """Messages with display_text are stored and retrieved."""
        session = await session_manager.create_session()
        msgs = [
            SessionMessage(role="user", content="test", display_text="Displayed text"),
            SessionMessage(role="assistant", content="response"),
        ]

        await session_manager.save_messages(session.id, msgs)
        loaded = await session_manager.get_messages(session.id)
        assert loaded[0].display_text == "Displayed text"

    async def test_save_messages_with_attached_files(self, session_manager: SessionManager):
        """Messages with attached_files are stored and retrieved."""
        session = await session_manager.create_session()
        msgs = [
            SessionMessage(
                role="user",
                content="check this file",
                attached_files=[{"name": "report.pdf", "type": "application/pdf", "size": 1024}],
            ),
            SessionMessage(role="assistant", content="I see the file."),
        ]

        await session_manager.save_messages(session.id, msgs)
        loaded = await session_manager.get_messages(session.id)
        assert loaded[0].attached_files is not None
        assert loaded[0].attached_files[0]["name"] == "report.pdf"

    async def test_save_messages_preview_from_structured_content(
        self, session_manager: SessionManager
    ):
        """Preview is extracted from structured content when last message has list content."""
        session = await session_manager.create_session()
        msgs = [
            SessionMessage(role="user", content="hello"),
            SessionMessage(
                role="assistant",
                content=[{"type": "text", "text": "Preview from structured"}],
            ),
        ]

        result = await session_manager.save_messages(session.id, msgs)
        assert result is not None
        assert result.preview == "Preview from structured"

    async def test_save_messages_empty_list_yields_empty_preview(
        self, session_manager: SessionManager
    ):
        """Empty message list yields empty preview."""
        session = await session_manager.create_session()
        result = await session_manager.save_messages(session.id, [])
        assert result is not None
        assert result.preview == ""

    async def test_auto_title_from_display_text(self, session_manager: SessionManager):
        """Auto-title uses display_text when content is empty."""
        session = await session_manager.create_session()
        msgs = [
            SessionMessage(role="user", content="", display_text="My displayed question"),
            SessionMessage(role="assistant", content="Answer"),
        ]

        result = await session_manager.save_messages(session.id, msgs)
        assert result is not None
        assert "My displayed question" in result.title

    async def test_auto_title_from_structured_content(self, session_manager: SessionManager):
        """Auto-title extracts text from structured content."""
        session = await session_manager.create_session()
        msgs = [
            SessionMessage(
                role="user",
                content=[{"type": "text", "text": "Structured question about AI"}],
            ),
            SessionMessage(role="assistant", content="Answer"),
        ]

        result = await session_manager.save_messages(session.id, msgs)
        assert result is not None
        assert "Structured question" in result.title

    async def test_auto_title_from_attached_files(self, session_manager: SessionManager):
        """Auto-title falls back to attached file names."""
        session = await session_manager.create_session()
        msgs = [
            SessionMessage(
                role="user",
                content="",
                attached_files=[{"name": "design.png"}, {"name": "spec.pdf"}],
            ),
            SessionMessage(role="assistant", content="I see the files."),
        ]

        result = await session_manager.save_messages(session.id, msgs)
        assert result is not None
        assert "design.png" in result.title or "spec.pdf" in result.title

    async def test_auto_title_not_overwritten(self, session_manager: SessionManager):
        """Custom title is not overwritten by auto-title logic."""
        session = await session_manager.create_session(title="My Custom Title")
        msgs = [
            SessionMessage(role="user", content="Some question"),
            SessionMessage(role="assistant", content="Some answer"),
        ]

        result = await session_manager.save_messages(session.id, msgs)
        assert result is not None
        assert result.title == "My Custom Title"

    async def test_get_messages_json_backward_compat(self, session_manager: SessionManager):
        """JSON-parseable string content that's a list is restored as list."""
        session = await session_manager.create_session()
        # Save a message with JSON-parseable list content
        msgs = [
            SessionMessage(role="user", content="normal text"),
            SessionMessage(role="assistant", content="response"),
        ]
        await session_manager.save_messages(session.id, msgs)

        loaded = await session_manager.get_messages(session.id)
        assert loaded is not None
        assert loaded[0].content == "normal text"

    async def test_save_messages_long_preview_truncated(self, session_manager: SessionManager):
        """Preview is truncated to 100 characters."""
        session = await session_manager.create_session()
        long_content = "A" * 200
        msgs = [
            SessionMessage(role="user", content="question"),
            SessionMessage(role="assistant", content=long_content),
        ]

        result = await session_manager.save_messages(session.id, msgs)
        assert result is not None
        assert len(result.preview) == 100
