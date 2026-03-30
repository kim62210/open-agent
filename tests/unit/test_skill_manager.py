"""SkillManager unit tests — skill discovery, parsing, CRUD, search, activation."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from open_agent.core.exceptions import (
    AlreadyExistsError,
    ConfigError,
    InvalidPathError,
    NotFoundError,
    PermissionDeniedError,
    SkillValidationError,
)
from open_agent.core.skill_manager import SkillManager, _ordered_frontmatter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skill_md(
    skill_dir: Path,
    name: str = "test-skill",
    description: str = "A test skill",
    version: str = "1.0.0",
    extra_fm: dict | None = None,
    body: str = "# Instructions\n\nDo the thing.\n",
    allowed_tools: list | None = None,
) -> Path:
    """Create a SKILL.md file in *skill_dir* with YAML frontmatter."""
    skill_dir.mkdir(parents=True, exist_ok=True)
    fm: dict = {"name": name, "description": description, "version": version}
    if allowed_tools is not None:
        fm["allowed-tools"] = allowed_tools
    if extra_fm:
        fm.update(extra_fm)
    frontmatter = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False)
    content = f"---\n{frontmatter}---\n\n{body}"
    md_path = skill_dir / "SKILL.md"
    md_path.write_text(content, encoding="utf-8")
    return md_path


def _make_manager_with_skills(tmp_path: Path, skills: list[dict]) -> SkillManager:
    """Create a SkillManager with skills discovered from tmp_path."""
    base = tmp_path / "skills"
    base.mkdir(exist_ok=True)
    for s in skills:
        skill_dir = base / s.get("dir_name", s["name"])
        _make_skill_md(
            skill_dir,
            name=s["name"],
            description=s.get("description", "desc"),
            allowed_tools=s.get("allowed_tools"),
            body=s.get("body", "# Instructions\n"),
        )
        # Create scripts if requested
        if s.get("scripts"):
            scripts_dir = skill_dir / "scripts"
            scripts_dir.mkdir(exist_ok=True)
            for script_name, script_content in s["scripts"].items():
                (scripts_dir / script_name).write_text(script_content, encoding="utf-8")
        # Create references if requested
        if s.get("references"):
            refs_dir = skill_dir / "references"
            refs_dir.mkdir(exist_ok=True)
            for ref_name, ref_content in s["references"].items():
                (refs_dir / ref_name).write_text(ref_content, encoding="utf-8")
    mgr = SkillManager()
    # Patch workflow_router to avoid import side effects
    with patch("open_agent.core.workflow_router.workflow_router"):
        mgr.discover_skills([str(base)])
    return mgr


# ---------------------------------------------------------------------------
# _ordered_frontmatter
# ---------------------------------------------------------------------------


class TestOrderedFrontmatter:
    def test_name_description_first(self):
        fm = {"version": "1.0.0", "name": "test", "description": "desc", "license": "MIT"}
        result = _ordered_frontmatter(fm)
        keys = list(result.keys())
        assert keys[0] == "name"
        assert keys[1] == "description"
        assert keys[2] == "version"

    def test_preserves_all_keys(self):
        fm = {"custom": "value", "name": "a", "description": "b"}
        result = _ordered_frontmatter(fm)
        assert set(result.keys()) == {"custom", "name", "description"}


# ---------------------------------------------------------------------------
# Frontmatter Parsing
# ---------------------------------------------------------------------------


class TestFrontmatterParsing:
    def test_valid_frontmatter(self, tmp_path: Path):
        skill_dir = tmp_path / "my-skill"
        md_path = _make_skill_md(skill_dir, name="my-skill", description="My skill")
        mgr = SkillManager()
        fm = mgr._parse_frontmatter(md_path)
        assert fm["name"] == "my-skill"
        assert fm["description"] == "My skill"

    def test_no_frontmatter_raises(self, tmp_path: Path):
        skill_dir = tmp_path / "bad-skill"
        skill_dir.mkdir(parents=True)
        md = skill_dir / "SKILL.md"
        md.write_text("# No frontmatter\n", encoding="utf-8")
        mgr = SkillManager()
        with pytest.raises(SkillValidationError, match="No YAML frontmatter"):
            mgr._parse_frontmatter(md)

    def test_invalid_frontmatter_format(self, tmp_path: Path):
        skill_dir = tmp_path / "bad-skill"
        skill_dir.mkdir(parents=True)
        md = skill_dir / "SKILL.md"
        md.write_text("---\nname: test\n", encoding="utf-8")
        mgr = SkillManager()
        with pytest.raises(SkillValidationError, match="Invalid frontmatter"):
            mgr._parse_frontmatter(md)

    def test_allowed_tools_list(self, tmp_path: Path):
        skill_dir = tmp_path / "tools-skill"
        _make_skill_md(skill_dir, name="tools-skill", allowed_tools=["tool_a", "tool_b"])
        mgr = SkillManager()
        fm = mgr._parse_frontmatter(skill_dir / "SKILL.md")
        assert fm["allowed-tools"] == ["tool_a", "tool_b"]

    def test_allowed_tools_string(self, tmp_path: Path):
        """allowed-tools as comma-separated string should parse fine in discovery."""
        skill_dir = tmp_path / "tools-skill"
        skill_dir.mkdir(parents=True)
        content = "---\nname: tools-skill\ndescription: desc\nallowed-tools: tool_a, tool_b\n---\n\n# Body\n"
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        mgr = SkillManager()
        fm = mgr._parse_frontmatter(skill_dir / "SKILL.md")
        assert fm["allowed-tools"] == "tool_a, tool_b"


# ---------------------------------------------------------------------------
# Skill Discovery
# ---------------------------------------------------------------------------


class TestSkillDiscovery:
    def test_discover_single_skill(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [
            {"name": "alpha", "description": "Alpha skill"},
        ])
        skills = mgr.get_all_skills()
        assert len(skills) == 1
        assert skills[0].name == "alpha"
        assert skills[0].description == "Alpha skill"

    def test_discover_multiple_skills(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [
            {"name": "alpha"},
            {"name": "beta"},
            {"name": "gamma"},
        ])
        names = {s.name for s in mgr.get_all_skills()}
        assert names == {"alpha", "beta", "gamma"}

    def test_discover_skips_dir_without_skill_md(self, tmp_path: Path):
        base = tmp_path / "skills"
        base.mkdir()
        (base / "no-skill-dir").mkdir()
        (base / "no-skill-dir" / "readme.txt").write_text("not a skill", encoding="utf-8")
        _make_skill_md(base / "real-skill", name="real-skill")
        mgr = SkillManager()
        with patch("open_agent.core.workflow_router.workflow_router"):
            mgr.discover_skills([str(base)])
        assert len(mgr.get_all_skills()) == 1

    def test_discover_nonexistent_directory(self, tmp_path: Path):
        mgr = SkillManager()
        with patch("open_agent.core.workflow_router.workflow_router"):
            mgr.discover_skills([str(tmp_path / "nonexistent")])
        assert mgr.get_all_skills() == []

    def test_discover_with_scripts_and_references(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [
            {
                "name": "scripted",
                "scripts": {"run.py": "print('hello')"},
                "references": {"guide.md": "# Guide"},
            },
        ])
        skill = mgr.get_skill("scripted")
        assert skill is not None
        assert "run.py" in skill.scripts
        assert "guide.md" in skill.references

    def test_discover_allowed_tools_from_list(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [
            {"name": "with-tools", "allowed_tools": ["tool_a", "tool_b"]},
        ])
        skill = mgr.get_skill("with-tools")
        assert skill is not None
        assert skill.allowed_tools == ["tool_a", "tool_b"]

    def test_discover_allowed_tools_from_csv_string(self, tmp_path: Path):
        base = tmp_path / "skills"
        base.mkdir()
        skill_dir = base / "csv-tools"
        skill_dir.mkdir()
        content = "---\nname: csv-tools\ndescription: test\nallowed-tools: \"tool_x, tool_y\"\n---\n\n# Body\n"
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        mgr = SkillManager()
        with patch("open_agent.core.workflow_router.workflow_router"):
            mgr.discover_skills([str(base)])
        skill = mgr.get_skill("csv-tools")
        assert skill is not None
        assert "tool_x" in skill.allowed_tools
        assert "tool_y" in skill.allowed_tools

    def test_discover_disabled_state_preserved(self, tmp_path: Path):
        """Skills in _disabled set are discovered with enabled=False."""
        base = tmp_path / "skills"
        base.mkdir()
        _make_skill_md(base / "disabled-skill", name="disabled-skill")
        mgr = SkillManager()
        mgr._disabled = {"disabled-skill"}
        with patch("open_agent.core.workflow_router.workflow_router"):
            mgr.discover_skills([str(base)])
        skill = mgr.get_skill("disabled-skill")
        assert skill is not None
        assert skill.enabled is False

    def test_discover_first_occurrence_wins(self, tmp_path: Path):
        """When same skill name appears in multiple base dirs, first wins."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        _make_skill_md(dir1 / "dup", name="dup", description="from dir1")
        _make_skill_md(dir2 / "dup", name="dup", description="from dir2")
        mgr = SkillManager()
        with patch("open_agent.core.workflow_router.workflow_router"):
            mgr.discover_skills([str(dir1), str(dir2)])
        skill = mgr.get_skill("dup")
        assert skill is not None
        assert skill.description == "from dir1"

    def test_bundled_detection(self, tmp_path: Path):
        bundled = tmp_path / "bundled"
        _make_skill_md(bundled / "builtin", name="builtin")
        mgr = SkillManager()
        mgr.set_bundled_dir(str(bundled))
        with patch("open_agent.core.workflow_router.workflow_router"):
            mgr.discover_skills([str(bundled)])
        skill = mgr.get_skill("builtin")
        assert skill is not None
        assert skill.is_bundled is True

    def test_malformed_skill_skipped(self, tmp_path: Path):
        """A skill with broken YAML does not crash discover_skills."""
        base = tmp_path / "skills"
        base.mkdir()
        bad_dir = base / "broken"
        bad_dir.mkdir()
        (bad_dir / "SKILL.md").write_text("---\n: bad yaml :\n---\nBody\n", encoding="utf-8")
        _make_skill_md(base / "good", name="good")
        mgr = SkillManager()
        with patch("open_agent.core.workflow_router.workflow_router"):
            mgr.discover_skills([str(base)])
        assert len(mgr.get_all_skills()) == 1
        assert mgr.get_skill("good") is not None


# ---------------------------------------------------------------------------
# CRUD Operations
# ---------------------------------------------------------------------------


class TestSkillCRUD:
    def test_get_skill_existing(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [{"name": "existing"}])
        assert mgr.get_skill("existing") is not None

    def test_get_skill_nonexistent(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [])
        assert mgr.get_skill("nonexistent") is None

    def test_get_all_skills(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [
            {"name": "a"},
            {"name": "b"},
        ])
        assert len(mgr.get_all_skills()) == 2

    def test_load_skill_content(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [
            {"name": "content-skill", "body": "# Full content\n\nDetails here.\n"},
        ])
        detail = mgr.load_skill_content("content-skill")
        assert detail is not None
        assert "Full content" in detail.content
        assert detail.name == "content-skill"

    def test_load_skill_content_nonexistent(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [])
        assert mgr.load_skill_content("nope") is None

    def test_load_skill_reference(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [
            {
                "name": "ref-skill",
                "references": {"api-guide.md": "# API Guide\nEndpoint details."},
            },
        ])
        content = mgr.load_skill_reference("ref-skill", "api-guide.md")
        assert content is not None
        assert "API Guide" in content

    def test_load_skill_reference_nonexistent_skill(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [])
        assert mgr.load_skill_reference("nope", "guide.md") is None

    def test_load_skill_reference_nonexistent_file(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [{"name": "no-refs"}])
        assert mgr.load_skill_reference("no-refs", "missing.md") is None

    def test_create_skill(self, tmp_path: Path):
        base = tmp_path / "skills"
        base.mkdir()
        mgr = SkillManager()
        with patch("open_agent.core.workflow_router.workflow_router"):
            mgr.discover_skills([str(base)])
            skill = mgr.create_skill("new-skill", "A new skill", "# Do stuff\n")
        assert skill.name == "new-skill"
        assert skill.description == "A new skill"
        assert (base / "new-skill" / "SKILL.md").exists()

    def test_create_skill_no_base_dirs_raises(self):
        mgr = SkillManager()
        with pytest.raises(ConfigError, match="No skill directories"):
            mgr.create_skill("fail", "desc")

    def test_create_skill_with_frontmatter_instructions(self, tmp_path: Path):
        base = tmp_path / "skills"
        base.mkdir()
        mgr = SkillManager()
        # The frontmatter name matches the skill name so discovery finds it
        instructions = "---\nname: new-skill\ndescription: custom desc\n---\n\n# Custom body\n"
        with patch("open_agent.core.workflow_router.workflow_router"):
            mgr.discover_skills([str(base)])
            skill = mgr.create_skill("new-skill", "initial desc", instructions)
        assert skill.name == "new-skill"
        # Verify the SKILL.md was created with custom body
        skill_md = Path(skill.path) / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")
        assert "Custom body" in content

    async def test_delete_skill(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [{"name": "deleteme"}])
        skill = mgr.get_skill("deleteme")
        assert skill is not None

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)
        mock_repo = AsyncMock()
        with (
            patch("core.db.engine.async_session_factory", mock_factory),
            patch("core.db.repositories.skill_config_repo.SkillConfigRepository", return_value=mock_repo),
        ):
            result = await mgr.delete_skill("deleteme")
        assert result is True
        assert mgr.get_skill("deleteme") is None

    async def test_delete_skill_nonexistent(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [])
        result = await mgr.delete_skill("nope")
        assert result is False

    async def test_delete_bundled_skill_raises(self, tmp_path: Path):
        bundled = tmp_path / "bundled"
        _make_skill_md(bundled / "builtin", name="builtin")
        mgr = SkillManager()
        mgr.set_bundled_dir(str(bundled))
        with patch("open_agent.core.workflow_router.workflow_router"):
            mgr.discover_skills([str(bundled)])
        with pytest.raises(PermissionDeniedError):
            await mgr.delete_skill("builtin")


# ---------------------------------------------------------------------------
# Activation / Deactivation
# ---------------------------------------------------------------------------


class TestSkillToggle:
    async def test_toggle_enable(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [{"name": "toggler"}])
        # First disable
        with patch.object(mgr, "_save_disabled", new_callable=AsyncMock):
            result = await mgr.toggle_skill("toggler", False)
        assert result is not None
        assert result.enabled is False
        assert "toggler" in mgr._disabled

    async def test_toggle_disable_then_enable(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [{"name": "toggler"}])
        with patch.object(mgr, "_save_disabled", new_callable=AsyncMock):
            await mgr.toggle_skill("toggler", False)
            assert mgr.get_skill("toggler").enabled is False
            await mgr.toggle_skill("toggler", True)
            assert mgr.get_skill("toggler").enabled is True
            assert "toggler" not in mgr._disabled

    async def test_toggle_nonexistent(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [])
        with patch.object(mgr, "_save_disabled", new_callable=AsyncMock):
            result = await mgr.toggle_skill("nope", True)
        assert result is None


# ---------------------------------------------------------------------------
# Update Skill
# ---------------------------------------------------------------------------


class TestUpdateSkill:
    async def test_update_description(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [{"name": "updatable"}])
        with patch.object(mgr, "_save_disabled", new_callable=AsyncMock):
            result = await mgr.update_skill("updatable", description="New description")
        assert result is not None
        assert result.description == "New description"

    async def test_update_instructions(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [{"name": "updatable"}])
        with patch.object(mgr, "_save_disabled", new_callable=AsyncMock):
            result = await mgr.update_skill("updatable", instructions="# New instructions\n")
        assert result is not None
        # Verify SKILL.md was rewritten
        skill_md = Path(result.path) / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")
        assert "New instructions" in content

    async def test_update_nonexistent(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [])
        result = await mgr.update_skill("nope", description="x")
        assert result is None

    async def test_update_bundled_content_raises(self, tmp_path: Path):
        bundled = tmp_path / "bundled"
        _make_skill_md(bundled / "builtin", name="builtin")
        mgr = SkillManager()
        mgr.set_bundled_dir(str(bundled))
        with patch("open_agent.core.workflow_router.workflow_router"):
            mgr.discover_skills([str(bundled)])
        with pytest.raises(PermissionDeniedError):
            await mgr.update_skill("builtin", description="hacked")

    async def test_update_enabled_state(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [{"name": "toggleable"}])
        with patch.object(mgr, "_save_disabled", new_callable=AsyncMock):
            result = await mgr.update_skill("toggleable", enabled=False)
        assert result is not None
        assert result.enabled is False

    async def test_update_auto_bumps_version(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [{"name": "versioned"}])
        with patch.object(mgr, "_save_disabled", new_callable=AsyncMock):
            result = await mgr.update_skill("versioned", instructions="# Updated\n")
        assert result is not None
        assert result.version == "1.0.1"


# ---------------------------------------------------------------------------
# XML Generation
# ---------------------------------------------------------------------------


class TestXmlGeneration:
    def test_empty_skills(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [])
        assert mgr.generate_skills_xml() == ""

    def test_all_disabled(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [{"name": "disabled"}])
        mgr._skills["disabled"].enabled = False
        assert mgr.generate_skills_xml() == ""

    def test_generates_xml_with_skills(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [
            {"name": "alpha", "description": "Alpha skill"},
        ])
        xml = mgr.generate_skills_xml()
        assert "<available_skills>" in xml
        assert "alpha" in xml
        assert "Alpha skill" in xml

    def test_xml_includes_scripts_and_refs(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [
            {
                "name": "full",
                "scripts": {"run.py": "pass"},
                "references": {"doc.md": "text"},
            },
        ])
        xml = mgr.generate_skills_xml()
        assert "run.py" in xml
        assert "doc.md" in xml


# ---------------------------------------------------------------------------
# Script Execution
# ---------------------------------------------------------------------------


class TestScriptExecution:
    async def test_execute_nonexistent_skill(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [])
        result = await mgr.execute_script("nope", "run.py")
        assert result["success"] is False
        assert "not found" in result["error"]

    async def test_execute_nonexistent_script(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [{"name": "no-scripts"}])
        result = await mgr.execute_script("no-scripts", "missing.py")
        assert result["success"] is False
        assert "not found" in result["error"]

    async def test_execute_unsupported_extension(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [
            {"name": "bad-ext", "scripts": {"run.rb": "puts 'hello'"}},
        ])
        result = await mgr.execute_script("bad-ext", "run.rb")
        assert result["success"] is False
        assert "Unsupported script type" in result["error"]

    async def test_execute_python_script(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [
            {"name": "py-skill", "scripts": {"hello.py": "print('hello from skill')"}},
        ])
        with patch("open_agent.core.workspace_tools.get_sanitized_env", return_value={}):
            result = await mgr.execute_script("py-skill", "hello.py")
        assert result["success"] is True
        assert "hello from skill" in result["stdout"]

    async def test_execute_script_timeout(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [
            {"name": "slow", "scripts": {"slow.py": "import time; time.sleep(120)"}},
        ])
        # Patch timeout to be very short
        with (
            patch("open_agent.core.workspace_tools.get_sanitized_env", return_value={}),
            patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()),
        ):
            # Need to mock subprocess to avoid actual process
            mock_proc = AsyncMock()
            mock_proc.kill = MagicMock()
            mock_proc.wait = AsyncMock()
            with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                result = await mgr.execute_script("slow", "slow.py")
        assert result["success"] is False
        assert "timed out" in result["error"]


# ---------------------------------------------------------------------------
# Path Traversal Protection
# ---------------------------------------------------------------------------


class TestPathTraversal:
    def test_resolve_subdir_blocks_traversal(self, tmp_path: Path):
        mgr = SkillManager()
        with pytest.raises(InvalidPathError, match="Path traversal"):
            mgr._resolve_subdir(tmp_path, ["references"], "../../etc/passwd")


# ---------------------------------------------------------------------------
# Workflow Body
# ---------------------------------------------------------------------------


class TestWorkflowBody:
    def test_get_workflow_body_existing(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [{"name": "wf-skill", "body": "workflow body"}])
        # Manually set bundled + body for test
        mgr._workflow_bodies["wf-skill"] = "workflow body"
        result = mgr.get_workflow_body("wf-skill")
        assert result is not None
        assert result["name"] == "wf-skill"
        assert result["body"] == "workflow body"

    def test_get_workflow_body_disabled(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [{"name": "disabled-wf"}])
        mgr._skills["disabled-wf"].enabled = False
        result = mgr.get_workflow_body("disabled-wf")
        assert result is None

    def test_get_workflow_body_no_body(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [{"name": "empty-wf"}])
        # No entry in _workflow_bodies
        result = mgr.get_workflow_body("empty-wf")
        assert result is None

    def test_get_workflow_body_nonexistent(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [])
        assert mgr.get_workflow_body("nope") is None


# ---------------------------------------------------------------------------
# Tool Call Handler
# ---------------------------------------------------------------------------


class TestToolCallHandler:
    async def test_read_skill_tool(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [
            {"name": "readable", "body": "# Read me\n"},
        ])
        result = await mgr.handle_tool_call("read_skill", {"skill_name": "readable"})
        assert "Read me" in result

    async def test_read_skill_not_found(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [])
        result = await mgr.handle_tool_call("read_skill", {"skill_name": "nope"})
        assert "Error" in result

    async def test_read_skill_reference_tool(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [
            {
                "name": "with-ref",
                "references": {"api.md": "# API Reference"},
            },
        ])
        result = await mgr.handle_tool_call(
            "read_skill_reference",
            {"skill_name": "with-ref", "reference_path": "api.md"},
        )
        assert "API Reference" in result

    async def test_read_skill_reference_not_found(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [{"name": "no-ref"}])
        result = await mgr.handle_tool_call(
            "read_skill_reference",
            {"skill_name": "no-ref", "reference_path": "missing.md"},
        )
        assert "Error" in result

    async def test_create_skill_tool(self, tmp_path: Path):
        base = tmp_path / "skills"
        base.mkdir()
        mgr = SkillManager()
        with patch("open_agent.core.workflow_router.workflow_router"):
            mgr.discover_skills([str(base)])
        result = await mgr.handle_tool_call(
            "create_skill",
            {"name": "created", "description": "A created skill", "instructions": "# Do it\n"},
        )
        assert "created" in result
        assert mgr.get_skill("created") is not None

    async def test_unknown_tool(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [])
        result = await mgr.handle_tool_call("unknown_tool", {})
        assert "Unknown" in result

    async def test_add_skill_script_tool(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [{"name": "scripted"}])
        with patch("open_agent.core.workflow_router.workflow_router"):
            result = await mgr.handle_tool_call(
                "add_skill_script",
                {
                    "skill_name": "scripted",
                    "filename": "helper.py",
                    "content": "print('helper')",
                },
            )
        assert "helper.py" in result
        # Verify file was created
        skill = mgr.get_skill("scripted")
        script_path = Path(skill.path) / "scripts" / "helper.py"
        assert script_path.exists()

    async def test_add_skill_script_invalid_extension(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [{"name": "scripted"}])
        result = await mgr.handle_tool_call(
            "add_skill_script",
            {"skill_name": "scripted", "filename": "bad.rb", "content": "puts 'bad'"},
        )
        assert "Error" in result

    async def test_add_skill_script_path_traversal(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [{"name": "scripted"}])
        result = await mgr.handle_tool_call(
            "add_skill_script",
            {"skill_name": "scripted", "filename": "../evil.py", "content": "bad"},
        )
        assert "Error" in result

    async def test_add_skill_script_bundled_blocked(self, tmp_path: Path):
        bundled = tmp_path / "bundled"
        _make_skill_md(bundled / "builtin", name="builtin")
        mgr = SkillManager()
        mgr.set_bundled_dir(str(bundled))
        with patch("open_agent.core.workflow_router.workflow_router"):
            mgr.discover_skills([str(bundled)])
        result = await mgr.handle_tool_call(
            "add_skill_script",
            {"skill_name": "builtin", "filename": "hack.py", "content": "bad"},
        )
        assert "Error" in result


# ---------------------------------------------------------------------------
# Skill Tools Definition
# ---------------------------------------------------------------------------


class TestSkillTools:
    def test_get_skill_tools_no_skills(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [])
        tools = mgr.get_skill_tools()
        # Base tools always present (create, add_script, edit_script, patch_script)
        tool_names = {t["function"]["name"] for t in tools}
        assert "create_skill" in tool_names

    def test_get_skill_tools_with_skills(self, tmp_path: Path):
        mgr = _make_manager_with_skills(tmp_path, [{"name": "active"}])
        tools = mgr.get_skill_tools()
        tool_names = {t["function"]["name"] for t in tools}
        assert "read_skill" in tool_names
        assert "run_skill_script" in tool_names
        assert "read_skill_reference" in tool_names
        assert "update_skill" in tool_names


# ---------------------------------------------------------------------------
# Import from path
# ---------------------------------------------------------------------------


class TestImportFromPath:
    def test_import_from_path_success(self, tmp_path: Path):
        source = tmp_path / "external" / "my-skill"
        _make_skill_md(source, name="imported-skill")
        dest_base = tmp_path / "skills"
        dest_base.mkdir()
        mgr = SkillManager()
        with patch("open_agent.core.workflow_router.workflow_router"):
            mgr.discover_skills([str(dest_base)])
            skill = mgr.import_from_path(str(source))
        assert skill.name == "imported-skill"

    def test_import_from_path_not_directory(self, tmp_path: Path):
        dest_base = tmp_path / "skills"
        dest_base.mkdir()
        mgr = SkillManager()
        with patch("open_agent.core.workflow_router.workflow_router"):
            mgr.discover_skills([str(dest_base)])
        with pytest.raises(NotFoundError, match="not a directory"):
            mgr.import_from_path(str(tmp_path / "nonexistent"))

    def test_import_from_path_no_skill_md(self, tmp_path: Path):
        source = tmp_path / "no-skill"
        source.mkdir()
        dest_base = tmp_path / "skills"
        dest_base.mkdir()
        mgr = SkillManager()
        with patch("open_agent.core.workflow_router.workflow_router"):
            mgr.discover_skills([str(dest_base)])
        with pytest.raises(NotFoundError, match="SKILL.md not found"):
            mgr.import_from_path(str(source))

    def test_import_from_path_already_exists(self, tmp_path: Path):
        source = tmp_path / "external" / "existing"
        _make_skill_md(source, name="existing")
        dest_base = tmp_path / "skills"
        _make_skill_md(dest_base / "existing", name="existing")
        mgr = SkillManager()
        with patch("open_agent.core.workflow_router.workflow_router"):
            mgr.discover_skills([str(dest_base)])
        with pytest.raises(AlreadyExistsError):
            mgr.import_from_path(str(source))

    def test_import_no_base_dirs_raises(self):
        mgr = SkillManager()
        with pytest.raises(ConfigError, match="No skill directories"):
            mgr.import_from_path("/some/path")


# ---------------------------------------------------------------------------
# _find_skill_root helper
# ---------------------------------------------------------------------------


class TestFindSkillRoot:
    def test_skill_md_at_root(self, tmp_path: Path):
        (tmp_path / "SKILL.md").write_text("---\nname: test\n---\n", encoding="utf-8")
        mgr = SkillManager()
        assert mgr._find_skill_root(tmp_path) == tmp_path

    def test_skill_md_in_child(self, tmp_path: Path):
        child = tmp_path / "inner"
        child.mkdir()
        (child / "SKILL.md").write_text("---\nname: test\n---\n", encoding="utf-8")
        mgr = SkillManager()
        assert mgr._find_skill_root(tmp_path) == child

    def test_no_skill_md(self, tmp_path: Path):
        mgr = SkillManager()
        assert mgr._find_skill_root(tmp_path) is None
