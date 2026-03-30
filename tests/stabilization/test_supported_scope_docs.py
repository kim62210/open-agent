from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_supported_scope_docs_exist_and_are_linked():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    supported_scope = ROOT / "docs/supported-scope.md"
    stabilization_policy = ROOT / "docs/stabilization-policy.md"

    assert supported_scope.exists()
    assert stabilization_policy.exists()
    assert "docs/supported-scope.md" in readme
    assert "docs/stabilization-policy.md" in readme


def test_deployment_and_upgrade_guides_capture_current_release_contract():
    deployment = (ROOT / "docs/deployment.md").read_text(encoding="utf-8")
    upgrade = (ROOT / "docs/upgrade.md").read_text(encoding="utf-8")

    assert "single-process" in deployment
    assert "alembic upgrade head" in deployment
    assert "/api/settings/readiness" in deployment

    assert "uv run open-agent update" in upgrade
    assert "alembic upgrade head" in upgrade
    assert "/api/chat/async" in upgrade
