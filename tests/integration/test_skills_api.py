"""Skills API integration tests — skill listing, CRUD, activation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from open_agent.models.skill import SkillDetail, SkillInfo


@pytest.fixture()
async def skills_client(_patch_db_factory, monkeypatch):
    """httpx.AsyncClient wired to skills router with mocked skill_manager."""
    import httpx
    from httpx import ASGITransport

    from fastapi import FastAPI
    from core.auth.dependencies import get_current_user
    from open_agent.api.endpoints import skills as skills_router

    test_app = FastAPI()
    test_app.include_router(skills_router.router, prefix="/api/skills")

    async def _fake_current_user() -> dict:
        return {"id": "test-user-id", "email": "test@example.com", "username": "testuser", "role": "admin"}

    test_app.dependency_overrides[get_current_user] = _fake_current_user

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _make_skill_info(name="test-skill", is_bundled=False, enabled=True):
    return SkillInfo(
        name=name, description="A test skill", path="/skills/test",
        scripts=[], references=[], enabled=enabled,
        is_bundled=is_bundled, version="1.0.0",
    )


class TestListSkills:
    """GET /api/skills/"""

    async def test_list_skills_empty(self, skills_client: AsyncClient):
        """Returns empty list when no user skills exist."""
        with patch("open_agent.api.endpoints.skills.skill_manager") as mock_sm:
            mock_sm.get_all_skills.return_value = []
            resp = await skills_client.get("/api/skills/")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_excludes_bundled(self, skills_client: AsyncClient):
        """Bundled skills are excluded from listing."""
        bundled = _make_skill_info("bundled", is_bundled=True)
        user_skill = _make_skill_info("my-skill", is_bundled=False)
        with patch("open_agent.api.endpoints.skills.skill_manager") as mock_sm:
            mock_sm.get_all_skills.return_value = [bundled, user_skill]
            resp = await skills_client.get("/api/skills/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1


class TestGetSkill:
    """GET /api/skills/{name}"""

    async def test_get_skill_found(self, skills_client: AsyncClient):
        """Returns skill detail for existing skill."""
        detail = SkillDetail(
            name="test", description="desc", path="/x", content="# SKILL.md",
        )
        with patch("open_agent.api.endpoints.skills.skill_manager") as mock_sm:
            mock_sm.load_skill_content.return_value = detail
            resp = await skills_client.get("/api/skills/test")
        assert resp.status_code == 200
        assert resp.json()["content"] == "# SKILL.md"

    async def test_get_skill_not_found(self, skills_client: AsyncClient):
        """Returns 404 for non-existent skill."""
        with patch("open_agent.api.endpoints.skills.skill_manager") as mock_sm:
            mock_sm.load_skill_content.return_value = None
            resp = await skills_client.get("/api/skills/nonexistent")
        assert resp.status_code == 404


class TestCreateSkill:
    """POST /api/skills/"""

    async def test_create_skill(self, skills_client: AsyncClient):
        """Creates a new skill."""
        skill = _make_skill_info()
        with patch("open_agent.api.endpoints.skills.skill_manager") as mock_sm:
            mock_sm.create_skill.return_value = skill
            resp = await skills_client.post(
                "/api/skills/",
                json={"name": "test-skill", "description": "A test skill"},
            )
        assert resp.status_code == 200

    async def test_create_skill_error(self, skills_client: AsyncClient):
        """Returns 400 when creation fails."""
        with patch("open_agent.api.endpoints.skills.skill_manager") as mock_sm:
            mock_sm.create_skill.side_effect = ValueError("Skill already exists")
            resp = await skills_client.post(
                "/api/skills/",
                json={"name": "dup", "description": "duplicate"},
            )
        assert resp.status_code == 400


class TestDeleteSkill:
    """DELETE /api/skills/{name}"""

    async def test_delete_user_skill(self, skills_client: AsyncClient):
        """Deletes a user skill."""
        skill = _make_skill_info(is_bundled=False)
        with patch("open_agent.api.endpoints.skills.skill_manager") as mock_sm:
            mock_sm.get_skill.return_value = skill
            mock_sm.delete_skill = AsyncMock(return_value=True)
            resp = await skills_client.delete("/api/skills/test-skill")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    async def test_delete_bundled_skill_forbidden(self, skills_client: AsyncClient):
        """Cannot delete a bundled skill — returns 403."""
        bundled = _make_skill_info(is_bundled=True)
        with patch("open_agent.api.endpoints.skills.skill_manager") as mock_sm:
            mock_sm.get_skill.return_value = bundled
            resp = await skills_client.delete("/api/skills/bundled-skill")
        assert resp.status_code == 403

    async def test_delete_nonexistent_skill(self, skills_client: AsyncClient):
        """Returns 404 for non-existent skill."""
        with patch("open_agent.api.endpoints.skills.skill_manager") as mock_sm:
            mock_sm.get_skill.return_value = None
            resp = await skills_client.delete("/api/skills/nonexistent")
        assert resp.status_code == 404


class TestUpdateSkill:
    """PATCH /api/skills/{name}"""

    async def test_update_skill(self, skills_client: AsyncClient):
        """Updates skill description."""
        updated = _make_skill_info()
        with patch("open_agent.api.endpoints.skills.skill_manager") as mock_sm:
            mock_sm.update_skill = AsyncMock(return_value=updated)
            resp = await skills_client.patch(
                "/api/skills/test-skill",
                json={"description": "Updated description"},
            )
        assert resp.status_code == 200

    async def test_update_nonexistent_skill(self, skills_client: AsyncClient):
        """Returns 404 for non-existent skill."""
        with patch("open_agent.api.endpoints.skills.skill_manager") as mock_sm:
            mock_sm.update_skill = AsyncMock(return_value=None)
            resp = await skills_client.patch(
                "/api/skills/nonexistent",
                json={"description": "Nope"},
            )
        assert resp.status_code == 404


class TestListWorkflows:
    """GET /api/skills/workflows"""

    async def test_list_workflows(self, skills_client: AsyncClient):
        """Returns workflow list from workflow_router."""
        with patch("open_agent.api.endpoints.skills.workflow_router") as mock_wr:
            mock_wr._skill_summaries = {"coder": "Code generation", "reviewer": "Code review"}
            resp = await skills_client.get("/api/skills/workflows")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        names = [w["name"] for w in data]
        assert "coder" in names


class TestReloadSkills:
    """POST /api/skills/reload"""

    async def test_reload_skills(self, skills_client: AsyncClient):
        """Reload returns status and count."""
        with patch("open_agent.api.endpoints.skills.skill_manager") as mock_sm:
            mock_sm._base_dirs = ["/skills"]
            mock_sm.discover_skills = MagicMock()
            mock_sm.get_all_skills.return_value = [_make_skill_info()]
            resp = await skills_client.post("/api/skills/reload")
        assert resp.status_code == 200
        assert resp.json()["status"] == "reloaded"

    async def test_reload_skills_no_base_dirs(self, skills_client: AsyncClient):
        """Reload with no base_dirs still returns status."""
        with patch("open_agent.api.endpoints.skills.skill_manager") as mock_sm:
            mock_sm._base_dirs = []
            mock_sm.get_all_skills.return_value = []
            resp = await skills_client.post("/api/skills/reload")
        assert resp.status_code == 200
        assert resp.json()["status"] == "reloaded"
        assert resp.json()["count"] == 0


class TestUpdateSkillExtended:
    """Extended skill update tests."""

    async def test_update_skill_instructions(self, skills_client: AsyncClient):
        """Updates skill instructions."""
        updated = _make_skill_info()
        with patch("open_agent.api.endpoints.skills.skill_manager") as mock_sm:
            mock_sm.update_skill = AsyncMock(return_value=updated)
            resp = await skills_client.patch(
                "/api/skills/test-skill",
                json={"instructions": "New instructions"},
            )
        assert resp.status_code == 200

    async def test_update_skill_enabled_flag(self, skills_client: AsyncClient):
        """Updates skill enabled flag."""
        updated = _make_skill_info(enabled=False)
        with patch("open_agent.api.endpoints.skills.skill_manager") as mock_sm:
            mock_sm.update_skill = AsyncMock(return_value=updated)
            resp = await skills_client.patch(
                "/api/skills/test-skill",
                json={"enabled": False},
            )
        assert resp.status_code == 200


class TestExecuteScript:
    """POST /api/skills/{name}/execute"""

    async def test_execute_script(self, skills_client: AsyncClient):
        """Executes a skill script."""
        with patch("open_agent.api.endpoints.skills.skill_manager") as mock_sm:
            mock_sm.get_skill.return_value = _make_skill_info()
            mock_sm.execute_script = AsyncMock(return_value={"output": "done", "exit_code": 0})
            resp = await skills_client.post(
                "/api/skills/test-skill/execute",
                params={"script": "setup.sh"},
            )
        assert resp.status_code == 200

    async def test_execute_script_not_found(self, skills_client: AsyncClient):
        """Returns 404 for non-existent skill."""
        with patch("open_agent.api.endpoints.skills.skill_manager") as mock_sm:
            mock_sm.get_skill.return_value = None
            resp = await skills_client.post(
                "/api/skills/nonexistent/execute",
                params={"script": "setup.sh"},
            )
        assert resp.status_code == 404


class TestUploadSkill:
    """POST /api/skills/upload"""

    async def test_upload_non_zip_returns_400(self, skills_client: AsyncClient):
        """Returns 400 for non-zip file."""
        resp = await skills_client.post(
            "/api/skills/upload",
            files={"file": ("skill.txt", b"not a zip", "text/plain")},
        )
        assert resp.status_code == 400

    async def test_upload_zip_skill(self, skills_client: AsyncClient):
        """Uploads a zip skill successfully."""
        skill = _make_skill_info()
        with patch("open_agent.api.endpoints.skills.skill_manager") as mock_sm:
            mock_sm.import_from_zip_bytes.return_value = skill
            resp = await skills_client.post(
                "/api/skills/upload",
                files={"file": ("skill.zip", b"PK\x03\x04fakecontent", "application/zip")},
            )
        assert resp.status_code == 200


class TestImportSkillFromPath:
    """POST /api/skills/import"""

    async def test_import_skill(self, skills_client: AsyncClient):
        """Imports skill from local path."""
        skill = _make_skill_info()
        with patch("open_agent.api.endpoints.skills.skill_manager") as mock_sm:
            mock_sm.import_from_path.return_value = skill
            resp = await skills_client.post(
                "/api/skills/import",
                json={"path": "/skills/my-skill"},
            )
        assert resp.status_code == 200

    async def test_import_skill_failure(self, skills_client: AsyncClient):
        """Returns 400 when import fails."""
        with patch("open_agent.api.endpoints.skills.skill_manager") as mock_sm:
            mock_sm.import_from_path.side_effect = FileNotFoundError("Path not found")
            resp = await skills_client.post(
                "/api/skills/import",
                json={"path": "/nonexistent"},
            )
        assert resp.status_code == 400


class TestListWorkflowsEmpty:
    """Extended workflow tests."""

    async def test_list_workflows_empty(self, skills_client: AsyncClient):
        """Returns empty list when no workflows exist."""
        with patch("open_agent.api.endpoints.skills.workflow_router") as mock_wr:
            mock_wr._skill_summaries = {}
            resp = await skills_client.get("/api/skills/workflows")
        assert resp.status_code == 200
        assert resp.json() == []
