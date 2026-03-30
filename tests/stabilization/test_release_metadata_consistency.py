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
