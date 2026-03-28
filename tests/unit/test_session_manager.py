"""SessionManager 단위 테스트."""

import json
from pathlib import Path

import pytest

from open_agent.core.session_manager import SessionManager
from open_agent.models.session import SessionMessage


class TestSessionCreate:
    """세션 생성 관련 테스트."""

    def test_create_session_default_title(self, session_manager: SessionManager):
        """타이틀 없이 생성하면 'New Session'이 기본값."""
        session = session_manager.create_session()

        assert session.id
        assert session.title == "New Session"
        assert session.message_count == 0
        assert session.preview == ""
        assert session.created_at
        assert session.updated_at

    def test_create_session_custom_title(self, session_manager: SessionManager):
        """커스텀 타이틀로 세션 생성."""
        session = session_manager.create_session(title="테스트 세션")

        assert session.title == "테스트 세션"

    def test_create_session_persists_to_disk(
        self, session_manager: SessionManager, tmp_data_dir: Path
    ):
        """세션 생성 시 sessions.json과 메시지 파일이 디스크에 저장됨."""
        session = session_manager.create_session(title="디스크 테스트")

        # sessions.json 검증
        config = json.loads((tmp_data_dir / "sessions.json").read_text(encoding="utf-8"))
        assert session.id in config["sessions"]
        assert config["sessions"][session.id]["title"] == "디스크 테스트"

        # 메시지 파일 검증
        msg_file = tmp_data_dir / "sessions" / f"{session.id}.json"
        assert msg_file.exists()
        assert json.loads(msg_file.read_text(encoding="utf-8")) == []


class TestSessionGet:
    """세션 조회 관련 테스트."""

    def test_get_existing_session(self, session_manager: SessionManager):
        """존재하는 세션 조회."""
        created = session_manager.create_session(title="조회 테스트")
        result = session_manager.get_session(created.id)

        assert result is not None
        assert result.id == created.id
        assert result.title == "조회 테스트"

    def test_get_nonexistent_session(self, session_manager: SessionManager):
        """존재하지 않는 세션 조회 시 None 반환."""
        result = session_manager.get_session("nonexistent-id")
        assert result is None

    def test_get_all_sessions_empty(self, session_manager: SessionManager):
        """초기 상태에서 빈 리스트 반환."""
        result = session_manager.get_all()
        assert result == []

    def test_get_all_sessions_ordered(self, session_manager: SessionManager):
        """세션 목록은 updated_at 내림차순으로 정렬."""
        s1 = session_manager.create_session(title="첫 번째")
        s2 = session_manager.create_session(title="두 번째")
        s3 = session_manager.create_session(title="세 번째")

        result = session_manager.get_all()
        assert len(result) == 3
        # 가장 최근 생성된 세션이 먼저
        assert result[0].id == s3.id
        assert result[1].id == s2.id
        assert result[2].id == s1.id


class TestSessionMessages:
    """메시지 저장/조회 테스트."""

    def test_get_messages_empty_session(self, session_manager: SessionManager):
        """빈 세션의 메시지 조회 시 빈 리스트."""
        session = session_manager.create_session()
        messages = session_manager.get_messages(session.id)

        assert messages == []

    def test_get_messages_nonexistent_session(self, session_manager: SessionManager):
        """존재하지 않는 세션의 메시지 조회 시 None."""
        result = session_manager.get_messages("nonexistent-id")
        assert result is None

    def test_save_and_get_messages(self, session_manager: SessionManager):
        """메시지 저장 후 조회 — 내용과 메타데이터 검증."""
        session = session_manager.create_session()
        msgs = [
            SessionMessage(role="user", content="안녕하세요"),
            SessionMessage(role="assistant", content="반갑습니다!"),
        ]

        result = session_manager.save_messages(session.id, msgs)
        assert result is not None
        assert result.message_count == 2
        assert result.preview == "반갑습니다!"

        loaded = session_manager.get_messages(session.id)
        assert loaded is not None
        assert len(loaded) == 2
        assert loaded[0].role == "user"
        assert loaded[0].content == "안녕하세요"
        assert loaded[1].role == "assistant"

    def test_save_messages_auto_title(self, session_manager: SessionManager):
        """기본 타이틀 세션에 메시지 저장 시 첫 user 메시지에서 타이틀 자동 생성."""
        session = session_manager.create_session()
        assert session.title == "New Session"

        msgs = [
            SessionMessage(role="user", content="Python 3.13의 새로운 기능에 대해 알려주세요"),
            SessionMessage(role="assistant", content="Python 3.13에서는..."),
        ]
        result = session_manager.save_messages(session.id, msgs)
        assert result is not None
        assert result.title != "New Session"
        assert "Python" in result.title

    def test_save_messages_nonexistent_session(self, session_manager: SessionManager):
        """존재하지 않는 세션에 메시지 저장 시 None."""
        msgs = [SessionMessage(role="user", content="test")]
        result = session_manager.save_messages("nonexistent-id", msgs)
        assert result is None


class TestSessionDelete:
    """세션 삭제 테스트."""

    def test_delete_existing_session(
        self, session_manager: SessionManager, tmp_data_dir: Path
    ):
        """세션 삭제 시 인덱스와 메시지 파일 모두 제거."""
        session = session_manager.create_session(title="삭제 대상")
        msg_file = tmp_data_dir / "sessions" / f"{session.id}.json"
        assert msg_file.exists()

        result = session_manager.delete_session(session.id)
        assert result is True
        assert session_manager.get_session(session.id) is None
        assert not msg_file.exists()

    def test_delete_nonexistent_session(self, session_manager: SessionManager):
        """존재하지 않는 세션 삭제 시 False."""
        result = session_manager.delete_session("nonexistent-id")
        assert result is False


class TestSessionUpdate:
    """세션 수정 테스트."""

    def test_update_title(self, session_manager: SessionManager):
        """세션 타이틀 변경."""
        session = session_manager.create_session(title="원래 제목")

        result = session_manager.update_session(session.id, "변경된 제목")
        assert result is not None
        assert result.title == "변경된 제목"

        # 재조회 확인
        reloaded = session_manager.get_session(session.id)
        assert reloaded is not None
        assert reloaded.title == "변경된 제목"

    def test_update_nonexistent_session(self, session_manager: SessionManager):
        """존재하지 않는 세션 수정 시 None."""
        result = session_manager.update_session("nonexistent-id", "새 제목")
        assert result is None
