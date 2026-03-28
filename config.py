import json
from pathlib import Path


def get_data_dir() -> Path:
    """~/.open-agent/ 데이터 디렉토리 반환, 없으면 생성"""
    data_dir = Path.home() / ".open-agent"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_config_path(filename: str) -> Path:
    return get_data_dir() / filename


def get_pages_dir() -> Path:
    d = get_data_dir() / "pages"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_skills_dir() -> Path:
    d = get_data_dir() / "skills"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_sessions_dir() -> Path:
    d = get_data_dir() / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_page_kv_dir() -> Path:
    d = get_data_dir() / "page_kv"
    d.mkdir(parents=True, exist_ok=True)
    return d


def init_data_dir() -> Path:
    """초기 설정 파일 생성. 이미 존재하는 파일은 건드리지 않음."""
    data_dir = get_data_dir()

    defaults = {
        "mcp.json": {"mcpServers": {}},
        "settings.json": {
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
        },
        "skills.json": {"disabled": []},
        "pages.json": {"pages": {}},
        "sessions.json": {"sessions": {}},
        "memories.json": {"memories": []},
        "workspaces.json": {"workspaces": {}},
        "jobs.json": {"jobs": {}},
    }

    for filename, content in defaults.items():
        path = data_dir / filename
        if not path.exists():
            path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # .env 템플릿
    env_path = data_dir / ".env"
    if not env_path.exists():
        env_path.write_text(
            "# 사용할 LLM 프로바이더의 API 키를 설정하세요\n"
            "# GOOGLE_API_KEY=your-google-api-key\n"
            "# OPENAI_API_KEY=your-openai-api-key\n"
            "# ANTHROPIC_API_KEY=your-anthropic-api-key\n"
            "# XAI_API_KEY=your-xai-api-key\n"
            "# OPENROUTER_API_KEY=your-openrouter-api-key\n",
            encoding="utf-8",
        )

    # 디렉토리 생성
    get_pages_dir()
    get_skills_dir()
    get_sessions_dir()

    return data_dir
