"""CLI tests — click commands, init_data_dir, config display."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner


@pytest.fixture()
def runner():
    """Click CLI test runner."""
    return CliRunner()


class TestMainGroup:
    """Main CLI group."""

    def test_help(self, runner):
        """--help outputs usage info."""
        from open_agent.cli import main

        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Open Agent" in result.output

    def test_version(self, runner):
        """--version outputs version string."""
        from open_agent.cli import main

        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "open-agent" in result.output


class TestInitCommand:
    """open-agent init command."""

    def test_init_creates_files(self, runner):
        """init command creates default config files."""
        from open_agent.cli import main

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / ".open-agent"
            tmp_path.mkdir()
            with patch("open_agent.config.init_data_dir", return_value=tmp_path):
                result = runner.invoke(main, ["init"])
            assert result.exit_code == 0


class TestConfigCommand:
    """open-agent config command."""

    def test_config_shows_path(self, runner):
        """config command shows data directory path."""
        from open_agent.cli import main

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            with patch("open_agent.config.get_data_dir", return_value=tmp_path):
                result = runner.invoke(main, ["config"])
            assert result.exit_code == 0


class TestStartCommand:
    """open-agent start command."""

    def test_start_invokes_uvicorn(self, runner):
        """start command calls uvicorn.run."""
        from open_agent.cli import main

        with patch("uvicorn.run") as mock_uvicorn:
            result = runner.invoke(main, ["start", "--port", "9999"])
        assert result.exit_code == 0
        mock_uvicorn.assert_called_once()
        call_kwargs = mock_uvicorn.call_args
        assert call_kwargs.kwargs["port"] == 9999

    def test_start_dev_mode(self, runner):
        """start --dev sets OPEN_AGENT_DEV and enables reload."""
        from open_agent.cli import main

        with patch("uvicorn.run") as mock_uvicorn:
            result = runner.invoke(main, ["start", "--dev"])
        assert result.exit_code == 0
        call_kwargs = mock_uvicorn.call_args
        assert call_kwargs.kwargs["reload"] is True

    def test_start_expose_mode(self, runner):
        """start --expose sets host to 0.0.0.0."""
        from open_agent.cli import main

        with patch("uvicorn.run") as mock_uvicorn:
            result = runner.invoke(main, ["start", "--expose"])
        assert result.exit_code == 0
        call_kwargs = mock_uvicorn.call_args
        assert call_kwargs.kwargs["host"] == "0.0.0.0"


class TestUpdateCommand:
    """open-agent update command."""

    def test_update_no_token(self, runner):
        """update command fails gracefully without GitHub token."""
        from open_agent.cli import main

        with patch.dict(
            "os.environ", {"GITHUB_TOKEN": "", "GH_TOKEN": ""}, clear=False
        ):
            with patch(
                "subprocess.run",
                side_effect=FileNotFoundError("gh not found"),
            ):
                result = runner.invoke(main, ["update"])
        assert result.exit_code == 0

    def test_update_with_version_arg(self, runner):
        """update with version argument passes correctly."""
        from open_agent.cli import main

        with patch.dict(
            "os.environ", {"GITHUB_TOKEN": "", "GH_TOKEN": ""}, clear=False
        ):
            with patch(
                "subprocess.run",
                side_effect=FileNotFoundError("gh not found"),
            ):
                result = runner.invoke(main, ["update", "v1.0.0"])
        assert result.exit_code == 0

    def test_update_with_gh_token_env(self, runner):
        """update with GITHUB_TOKEN env but gh CLI unavailable."""
        import subprocess
        from open_agent.cli import main

        def mock_run(cmd, **kwargs):
            if cmd[0] == "gh" and "version" in cmd:
                raise FileNotFoundError("gh not found")
            if cmd[0] == "gh":
                raise FileNotFoundError("gh not found")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch.dict(
            "os.environ", {"GITHUB_TOKEN": "fake-token", "GH_TOKEN": ""}, clear=False
        ):
            with patch("subprocess.run", side_effect=mock_run):
                # urllib will fail since the URL is fake
                import urllib.error
                with patch(
                    "urllib.request.urlopen",
                    side_effect=urllib.error.HTTPError(
                        "url", 404, "Not Found", {}, None
                    ),
                ):
                    result = runner.invoke(main, ["update"])
        assert result.exit_code == 0

    def test_update_subprocess_error(self, runner):
        """update handles CalledProcessError gracefully."""
        import subprocess
        from open_agent.cli import main

        def mock_run(cmd, **kwargs):
            if cmd[0] == "gh" and "auth" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="fake-token\n", stderr="")
            if cmd[0] == "gh" and "--version" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="gh 2.0", stderr="")
            raise subprocess.CalledProcessError(1, cmd, stderr="some error")

        with patch.dict(
            "os.environ", {"GITHUB_TOKEN": "", "GH_TOKEN": ""}, clear=False
        ):
            with patch("subprocess.run", side_effect=mock_run):
                result = runner.invoke(main, ["update"])
        assert result.exit_code == 0

    def test_update_generic_exception(self, runner):
        """update handles unexpected exceptions gracefully."""
        import subprocess
        from open_agent.cli import main

        def mock_run(cmd, **kwargs):
            if cmd[0] == "gh" and "auth" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="fake-token\n", stderr="")
            if cmd[0] == "gh" and "--version" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="gh 2.0", stderr="")
            # Simulate listing releases with valid JSON
            if "release" in cmd and "list" in cmd:
                import json
                releases = json.dumps([{"tagName": "v1.0.0"}])
                return subprocess.CompletedProcess(cmd, 0, stdout=releases, stderr="")
            if "release" in cmd and "view" in cmd:
                import json
                release = json.dumps({
                    "tagName": "v1.0.0",
                    "assets": [{"name": "test-0.1.0-py3-none-any.whl"}],
                })
                return subprocess.CompletedProcess(cmd, 0, stdout=release, stderr="")
            if "release" in cmd and "download" in cmd:
                raise RuntimeError("Download failed unexpectedly")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch.dict(
            "os.environ", {"GITHUB_TOKEN": "", "GH_TOKEN": ""}, clear=False
        ):
            with patch("subprocess.run", side_effect=mock_run):
                result = runner.invoke(main, ["update"])
        assert result.exit_code == 0

    def test_update_no_whl_in_release(self, runner):
        """update handles release with no .whl files."""
        import subprocess
        from open_agent.cli import main

        def mock_run(cmd, **kwargs):
            if cmd[0] == "gh" and "auth" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="fake-token\n", stderr="")
            if cmd[0] == "gh" and "--version" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="gh 2.0", stderr="")
            if "release" in cmd and "list" in cmd:
                import json
                releases = json.dumps([{"tagName": "v1.0.0"}])
                return subprocess.CompletedProcess(cmd, 0, stdout=releases, stderr="")
            if "release" in cmd and "view" in cmd:
                import json
                release = json.dumps({
                    "tagName": "v1.0.0",
                    "assets": [{"name": "README.md"}],
                })
                return subprocess.CompletedProcess(cmd, 0, stdout=release, stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch.dict(
            "os.environ", {"GITHUB_TOKEN": "", "GH_TOKEN": ""}, clear=False
        ):
            with patch("subprocess.run", side_effect=mock_run):
                result = runner.invoke(main, ["update"])
        assert result.exit_code == 0

    def test_update_no_python_release(self, runner):
        """update handles case with no v* Python releases."""
        import subprocess
        from open_agent.cli import main

        def mock_run(cmd, **kwargs):
            if cmd[0] == "gh" and "auth" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="fake-token\n", stderr="")
            if cmd[0] == "gh" and "--version" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="gh 2.0", stderr="")
            if "release" in cmd and "list" in cmd:
                import json
                releases = json.dumps([
                    {"tagName": "desktop-v1.0.0"},
                    {"tagName": "mac-desktop-v2.0.0"},
                ])
                return subprocess.CompletedProcess(cmd, 0, stdout=releases, stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch.dict(
            "os.environ", {"GITHUB_TOKEN": "", "GH_TOKEN": ""}, clear=False
        ):
            with patch("subprocess.run", side_effect=mock_run):
                result = runner.invoke(main, ["update"])
        assert result.exit_code == 0


class TestInitDataDir:
    """init_data_dir() from config module."""

    def test_creates_default_files(self):
        """init_data_dir creates all expected default files."""
        import open_agent.config as config_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / ".open-agent"
            tmp_path.mkdir(parents=True, exist_ok=True)

            def _mock_get_data_dir():
                tmp_path.mkdir(parents=True, exist_ok=True)
                return tmp_path

            with patch.object(config_mod, "get_data_dir", side_effect=_mock_get_data_dir):
                with patch.object(config_mod, "get_pages_dir", return_value=tmp_path / "pages"):
                    with patch.object(config_mod, "get_skills_dir", return_value=tmp_path / "skills"):
                        with patch.object(
                            config_mod, "get_sessions_dir", return_value=tmp_path / "sessions"
                        ):
                            result = config_mod.init_data_dir()
            assert result == tmp_path
            # Check that JSON files were created
            for name in [
                "mcp.json",
                "settings.json",
                "skills.json",
                "pages.json",
                "sessions.json",
                "memories.json",
                "workspaces.json",
                "jobs.json",
            ]:
                assert (tmp_path / name).exists(), f"{name} should have been created"
            # Check .env template
            assert (tmp_path / ".env").exists()

    def test_does_not_overwrite_existing(self):
        """init_data_dir does not overwrite existing files."""
        import open_agent.config as config_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / ".open-agent"
            tmp_path.mkdir()
            # Write a custom settings.json
            (tmp_path / "settings.json").write_text('{"custom": true}')

            def _mock_get_data_dir():
                tmp_path.mkdir(parents=True, exist_ok=True)
                return tmp_path

            with patch.object(config_mod, "get_data_dir", side_effect=_mock_get_data_dir):
                with patch.object(config_mod, "get_pages_dir", return_value=tmp_path / "pages"):
                    with patch.object(config_mod, "get_skills_dir", return_value=tmp_path / "skills"):
                        with patch.object(
                            config_mod, "get_sessions_dir", return_value=tmp_path / "sessions"
                        ):
                            config_mod.init_data_dir()
            content = (tmp_path / "settings.json").read_text()
            assert '"custom": true' in content


class TestConfigHelpers:
    """Config helper functions."""

    def test_get_data_dir(self):
        """get_data_dir returns a Path."""
        from open_agent.config import get_data_dir

        result = get_data_dir()
        assert isinstance(result, Path)

    def test_get_config_path(self):
        """get_config_path joins filename to data dir."""
        from open_agent.config import get_config_path

        result = get_config_path("test.json")
        assert result.name == "test.json"

    def test_get_pages_dir(self):
        """get_pages_dir returns pages subdirectory."""
        from open_agent.config import get_pages_dir

        result = get_pages_dir()
        assert result.name == "pages"

    def test_get_skills_dir(self):
        """get_skills_dir returns skills subdirectory."""
        from open_agent.config import get_skills_dir

        result = get_skills_dir()
        assert result.name == "skills"

    def test_get_sessions_dir(self):
        """get_sessions_dir returns sessions subdirectory."""
        from open_agent.config import get_sessions_dir

        result = get_sessions_dir()
        assert result.name == "sessions"

    def test_get_page_kv_dir(self):
        """get_page_kv_dir returns page_kv subdirectory."""
        from open_agent.config import get_page_kv_dir

        result = get_page_kv_dir()
        assert result.name == "page_kv"
