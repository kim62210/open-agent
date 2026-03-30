"""Unit tests for config.py — data directory management."""

import json
from pathlib import Path
from unittest.mock import patch

from config import (
    get_config_path,
    get_data_dir,
    get_page_kv_dir,
    get_pages_dir,
    get_sessions_dir,
    get_skills_dir,
    init_data_dir,
)


class TestGetDataDir:
    def test_returns_path(self, tmp_path: Path):
        with patch("config.Path.home", return_value=tmp_path):
            result = get_data_dir()
        assert isinstance(result, Path)
        assert result == tmp_path / ".open-agent"

    def test_creates_dir(self, tmp_path: Path):
        with patch("config.Path.home", return_value=tmp_path):
            result = get_data_dir()
        assert result.exists()
        assert result.is_dir()


class TestGetConfigPath:
    def test_returns_path(self, tmp_path: Path):
        with patch("config.Path.home", return_value=tmp_path):
            result = get_config_path("settings.json")
        assert result == tmp_path / ".open-agent" / "settings.json"


class TestGetSubdirs:
    def test_pages_dir(self, tmp_path: Path):
        with patch("config.Path.home", return_value=tmp_path):
            result = get_pages_dir()
        assert result == tmp_path / ".open-agent" / "pages"
        assert result.exists()

    def test_skills_dir(self, tmp_path: Path):
        with patch("config.Path.home", return_value=tmp_path):
            result = get_skills_dir()
        assert result == tmp_path / ".open-agent" / "skills"
        assert result.exists()

    def test_sessions_dir(self, tmp_path: Path):
        with patch("config.Path.home", return_value=tmp_path):
            result = get_sessions_dir()
        assert result == tmp_path / ".open-agent" / "sessions"
        assert result.exists()

    def test_page_kv_dir(self, tmp_path: Path):
        with patch("config.Path.home", return_value=tmp_path):
            result = get_page_kv_dir()
        assert result == tmp_path / ".open-agent" / "page_kv"
        assert result.exists()


class TestInitDataDir:
    def test_creates_default_files(self, tmp_path: Path):
        with patch("config.Path.home", return_value=tmp_path):
            result = init_data_dir()

        assert result.exists()
        # Check JSON config files exist
        for filename in ["mcp.json", "settings.json", "skills.json", "pages.json",
                         "sessions.json", "memories.json", "workspaces.json", "jobs.json"]:
            path = result / filename
            assert path.exists(), f"{filename} should exist"
            content = json.loads(path.read_text())
            assert isinstance(content, dict)

    def test_creates_env_template(self, tmp_path: Path):
        with patch("config.Path.home", return_value=tmp_path):
            result = init_data_dir()

        env_path = result / ".env"
        assert env_path.exists()
        content = env_path.read_text()
        assert "API_KEY" in content

    def test_creates_subdirectories(self, tmp_path: Path):
        with patch("config.Path.home", return_value=tmp_path):
            init_data_dir()

        assert (tmp_path / ".open-agent" / "pages").exists()
        assert (tmp_path / ".open-agent" / "skills").exists()
        assert (tmp_path / ".open-agent" / "sessions").exists()

    def test_idempotent(self, tmp_path: Path):
        with patch("config.Path.home", return_value=tmp_path):
            init_data_dir()
            # Modify a file
            settings_path = tmp_path / ".open-agent" / "settings.json"
            original = settings_path.read_text()
            settings_path.write_text('{"custom": true}')
            # Re-init should not overwrite
            init_data_dir()
            assert settings_path.read_text() == '{"custom": true}'

    def test_settings_structure(self, tmp_path: Path):
        with patch("config.Path.home", return_value=tmp_path):
            result = init_data_dir()

        settings = json.loads((result / "settings.json").read_text())
        assert "llm" in settings
        assert "memory" in settings
        assert "profile" in settings
        assert "theme" in settings
        assert settings["llm"]["model"] == "gemini/gemini-2.0-flash"
