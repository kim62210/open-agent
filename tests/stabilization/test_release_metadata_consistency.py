from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_project_metadata_matches_open_agent_identity():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'name = "open-agent"' in pyproject
    assert 'Repository = "https://github.com/kim62210/open-agent"' in pyproject


def test_release_lookup_sources_target_open_agent():
    cli_source = (ROOT / "cli.py").read_text(encoding="utf-8")
    settings_source = (ROOT / "api/endpoints/settings.py").read_text(encoding="utf-8")

    assert 'repo = "kim62210/open-agent"' in cli_source
    assert "repos/kim62210/open-agent/releases" in settings_source
    assert "pypi/open-agent/json" in settings_source


def test_open_source_release_excludes_prebuilt_frontend_and_native_binaries():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    static_dir = ROOT / "static"

    assert 'packages = [".", "nexus_rust"]' not in pyproject
    assert "static/**" not in pyproject
    assert "nexus_rust/**" not in pyproject
    assert not static_dir.exists() or not any(path.is_file() for path in static_dir.rglob("*"))
    assert not any(ROOT.glob("nexus_rust/*.so"))


def test_gitignore_blocks_regenerated_private_release_artifacts():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "static/" in gitignore
    assert "nexus_rust/*.so" in gitignore
