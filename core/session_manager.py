import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from open_agent.core.exceptions import NotInitializedError
from open_agent.models.session import SessionInfo, SessionMessage

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(self):
        self._sessions: Dict[str, SessionInfo] = {}
        self._sessions_dir: Optional[Path] = None
        self._config_path: Optional[Path] = None

    def load_config(self, config_path: str, sessions_dir: str) -> None:
        sessions_path = Path(sessions_dir)
        if not sessions_path.is_absolute():
            from open_agent.config import get_sessions_dir
            sessions_path = get_sessions_dir()
        self._sessions_dir = sessions_path
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

        path = Path(config_path)
        if not path.is_absolute():
            from open_agent.config import get_config_path
            path = get_config_path(config_path)
        self._config_path = path

        if not path.exists():
            path.write_text(json.dumps({"sessions": {}}, indent=2), encoding="utf-8")
            self._sessions = {}
            return

        data = json.loads(path.read_text(encoding="utf-8"))
        for sid, info in data.get("sessions", {}).items():
            self._sessions[sid] = SessionInfo(
                id=sid,
                title=info.get("title", ""),
                created_at=info.get("created_at", ""),
                updated_at=info.get("updated_at", ""),
                message_count=info.get("message_count", 0),
                preview=info.get("preview", ""),
            )

        logger.info(f"Loaded {len(self._sessions)} sessions from {path}")

    def _save_config(self) -> None:
        if not self._config_path:
            return
        data: dict = {"sessions": {}}
        for sid, s in self._sessions.items():
            data["sessions"][sid] = {
                "title": s.title,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
                "message_count": s.message_count,
                "preview": s.preview,
            }
        self._config_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _messages_path(self, session_id: str) -> Path:
        if not self._sessions_dir:
            raise NotInitializedError("SessionManager not initialized")
        return self._sessions_dir / f"{session_id}.json"

    def get_all(self) -> List[SessionInfo]:
        """전체 세션 목록 (updated_at 내림차순)"""
        sessions = list(self._sessions.values())
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    def get_session(self, session_id: str) -> Optional[SessionInfo]:
        return self._sessions.get(session_id)

    def create_session(self, title: str = "") -> SessionInfo:
        session_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        session = SessionInfo(
            id=session_id,
            title=title or "New Session",
            created_at=now,
            updated_at=now,
            message_count=0,
            preview="",
        )
        self._sessions[session_id] = session

        # 빈 메시지 파일 생성
        self._messages_path(session_id).write_text(
            json.dumps([], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        self._save_config()
        logger.info(f"Created session: {session.title} ({session_id})")
        return session

    def get_messages(self, session_id: str) -> Optional[List[SessionMessage]]:
        if session_id not in self._sessions:
            return None
        path = self._messages_path(session_id)
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [SessionMessage(**m) for m in data]

    def save_messages(self, session_id: str, messages: List[SessionMessage]) -> Optional[SessionInfo]:
        session = self._sessions.get(session_id)
        if not session:
            return None

        # 메시지 파일 저장
        msg_dicts = [m.model_dump(exclude_none=True) for m in messages]
        self._messages_path(session_id).write_text(
            json.dumps(msg_dicts, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        # 인덱스 업데이트
        now = datetime.now(timezone.utc).isoformat()
        session.updated_at = now
        session.message_count = len(messages)

        # preview: 마지막 assistant 메시지의 텍스트 100자
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

        # title 자동 생성: 아직 기본 타이틀이면 첫 user 메시지에서 추출
        # display_text 우선 사용 (파일 첨부 시 파일 내용 제외된 텍스트)
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

        self._sessions[session_id] = session
        self._save_config()
        return session

    def update_session(self, session_id: str, title: str) -> Optional[SessionInfo]:
        session = self._sessions.get(session_id)
        if not session:
            return None
        session.title = title
        session.updated_at = datetime.now(timezone.utc).isoformat()
        self._sessions[session_id] = session
        self._save_config()
        return session

    def delete_session(self, session_id: str) -> bool:
        if session_id not in self._sessions:
            return False
        self._sessions.pop(session_id)

        # 메시지 파일 삭제
        path = self._messages_path(session_id)
        if path.exists():
            path.unlink()

        self._save_config()
        logger.info(f"Deleted session: {session_id}")
        return True


session_manager = SessionManager()
