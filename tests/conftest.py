"""전역 테스트 fixture — 격리된 데이터 디렉토리 + 싱글톤 매니저 초기화."""

# ── open_agent 패키지 매핑 ──
# hatchling packages=["."] 빌드 시 프로젝트 루트가 open_agent 패키지로 매핑됨.
# editable install에서 디렉토리명(local-agent)과 패키지명(open_agent)이 달라
# import가 실패할 수 있으므로, 테스트 실행 전 sys.modules에 매핑을 추가한다.
import importlib
import sys
from pathlib import Path as _Path

_PROJECT_ROOT = _Path(__file__).resolve().parent.parent

if "open_agent" not in sys.modules:
    # 프로젝트 루트의 __init__.py를 open_agent로 로드
    _spec = importlib.util.spec_from_file_location(
        "open_agent",
        _PROJECT_ROOT / "__init__.py",
        submodule_search_locations=[str(_PROJECT_ROOT)],
    )
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules["open_agent"] = _mod
        _spec.loader.exec_module(_mod)

import json
import logging
from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest

logger = logging.getLogger(__name__)

# ── 기본 설정 템플릿 ──

_DEFAULT_SETTINGS = {
    "llm": {
        "model": "gemini/gemini-2.0-flash",
        "temperature": 0.7,
        "max_tokens": 16384,
        "system_prompt": "",
    },
    "memory": {
        "enabled": True,
        "max_memories": 50,
        "max_injection_tokens": 2000,
        "compression_threshold": 0.8,
        "extraction_interval": 3,
    },
    "profile": {
        "name": "",
        "avatar": "",
        "platform_name": "Open Agent",
        "platform_subtitle": "Open Agent System",
        "bot_name": "Open Agent Core",
        "bot_avatar": "",
    },
    "theme": {
        "accent_color": "amber",
        "mode": "dark",
        "tone": "default",
        "show_blobs": True,
        "chat_bg_image": "",
        "chat_bg_opacity": 0.3,
        "chat_bg_scale": 1.1,
        "chat_bg_position_x": 50,
        "chat_bg_position_y": 50,
        "font_scale": 1.0,
    },
}

_CONFIG_FILES = {
    "settings.json": _DEFAULT_SETTINGS,
    "sessions.json": {"sessions": {}},
    "memories.json": {"memories": []},
    "mcp.json": {"mcpServers": {}},
    "skills.json": {"disabled": []},
    "pages.json": {"pages": {}},
    "workspaces.json": {"workspaces": {}},
    "jobs.json": {"jobs": {}},
}


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


@pytest.fixture()
def tmp_data_dir(tmp_path: Path) -> Path:
    """격리된 데이터 디렉토리 생성 — 각 테스트마다 새 임시 경로."""
    data_dir = tmp_path / "open-agent-data"
    data_dir.mkdir()

    # sessions 하위 디렉토리
    (data_dir / "sessions").mkdir()

    # JSON 설정 파일 생성
    for filename, content in _CONFIG_FILES.items():
        _write_json(data_dir / filename, content)

    return data_dir


@pytest.fixture()
def session_manager(tmp_data_dir: Path) -> Generator:
    """격리된 SessionManager 인스턴스 — 테스트 후 싱글톤 복원."""
    from open_agent.core.session_manager import SessionManager
    from open_agent.core.session_manager import session_manager as _global

    # 테스트용 인스턴스 생성 + 초기화
    mgr = SessionManager()
    config_path = str(tmp_data_dir / "sessions.json")
    sessions_dir = str(tmp_data_dir / "sessions")
    mgr.load_config(config_path, sessions_dir)

    yield mgr

    # 싱글톤 상태 복원은 불필요 (새 인스턴스 사용)


@pytest.fixture()
def memory_manager(tmp_data_dir: Path) -> Generator:
    """격리된 MemoryManager 인스턴스 — 테스트 후 싱글톤 복원."""
    from open_agent.core.memory_manager import MemoryManager

    mgr = MemoryManager()
    config_path = str(tmp_data_dir / "memories.json")
    mgr.load_config(config_path)

    yield mgr


@pytest.fixture()
def settings_manager(tmp_data_dir: Path) -> Generator:
    """격리된 SettingsManager 인스턴스."""
    from open_agent.core.settings_manager import SettingsManager

    mgr = SettingsManager()
    config_path = str(tmp_data_dir / "settings.json")
    mgr.load_config(config_path)

    yield mgr


@pytest.fixture()
def mock_llm(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """litellm.acompletion을 mock — LLM 호출 없이 테스트 가능."""
    mock_message = MagicMock()
    mock_message.content = "mocked response"
    mock_message.reasoning_content = None

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    async_mock = AsyncMock(return_value=mock_response)

    # memory_manager가 litellm.acompletion을 직접 import하므로 해당 경로 패치
    monkeypatch.setattr("open_agent.core.memory_manager.acompletion", async_mock)

    return async_mock


@pytest.fixture()
async def async_client(tmp_data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """httpx.AsyncClient + ASGITransport로 FastAPI 통합 테스트.

    싱글톤 매니저를 격리된 인스턴스로 교체한 뒤 테스트 클라이언트를 생성합니다.
    """
    import httpx
    from httpx import ASGITransport

    # 싱글톤 매니저들의 원본 상태 보존
    from open_agent.core.session_manager import session_manager as _sm
    from open_agent.core.memory_manager import memory_manager as _mm
    from open_agent.core.settings_manager import settings_manager as _stm

    # 원래 내부 상태 백업
    orig_sm_sessions = _sm._sessions
    orig_sm_sessions_dir = _sm._sessions_dir
    orig_sm_config_path = _sm._config_path
    orig_mm_memories = _mm._memories
    orig_mm_config_path = _mm._config_path
    orig_stm_settings = _stm._settings
    orig_stm_config_path = _stm._config_path

    # 격리된 데이터로 싱글톤 초기화
    _stm.load_config(str(tmp_data_dir / "settings.json"))
    _sm.load_config(str(tmp_data_dir / "sessions.json"), str(tmp_data_dir / "sessions"))
    _mm.load_config(str(tmp_data_dir / "memories.json"))

    # lifespan 없이 경량 앱 사용 — 라우터만 등록
    from fastapi import FastAPI
    from open_agent.api.endpoints import sessions as sessions_router

    test_app = FastAPI()
    test_app.include_router(sessions_router.router, prefix="/api/sessions")

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    # 싱글톤 상태 복원
    _sm._sessions = orig_sm_sessions
    _sm._sessions_dir = orig_sm_sessions_dir
    _sm._config_path = orig_sm_config_path
    _mm._memories = orig_mm_memories
    _mm._config_path = orig_mm_config_path
    _stm._settings = orig_stm_settings
    _stm._config_path = orig_stm_config_path
