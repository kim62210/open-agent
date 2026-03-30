"""Pydantic model validation tests — auth, error, page, skill, workspace, memory, settings."""

import pytest
from pydantic import ValidationError


class TestAuthModels:
    """models/auth.py"""

    def test_register_request_valid(self):
        """Valid registration request."""
        from models.auth import RegisterRequest
        req = RegisterRequest(email="test@test.com", username="testuser", password="password123")
        assert req.email == "test@test.com"
        assert req.username == "testuser"

    def test_register_request_strips_whitespace(self):
        """Whitespace is stripped from fields."""
        from models.auth import RegisterRequest
        req = RegisterRequest(email="  test@test.com  ", username="  user  ", password="password123")
        assert req.email == "test@test.com"
        assert req.username == "user"

    def test_register_request_email_too_short(self):
        """Email under 3 chars is rejected."""
        from models.auth import RegisterRequest
        with pytest.raises(ValidationError):
            RegisterRequest(email="ab", username="user", password="password123")

    def test_register_request_username_too_short(self):
        """Username under 2 chars is rejected."""
        from models.auth import RegisterRequest
        with pytest.raises(ValidationError):
            RegisterRequest(email="test@test.com", username="a", password="password123")

    def test_register_request_password_too_short(self):
        """Password under 8 chars is rejected."""
        from models.auth import RegisterRequest
        with pytest.raises(ValidationError):
            RegisterRequest(email="test@test.com", username="user", password="short")

    def test_login_request_valid(self):
        """Valid login request."""
        from models.auth import LoginRequest
        req = LoginRequest(email="test@test.com", password="password123")
        assert req.email == "test@test.com"

    def test_token_response(self):
        """Token response defaults to bearer."""
        from models.auth import TokenResponse
        resp = TokenResponse(access_token="at", refresh_token="rt")
        assert resp.token_type == "bearer"

    def test_user_response_from_attributes(self):
        """UserResponse can be created from dict with from_attributes."""
        from models.auth import UserResponse
        data = {"id": "1", "email": "a@b.com", "username": "u", "role": "user",
                "is_active": True, "created_at": "2024-01-01"}
        resp = UserResponse(**data)
        assert resp.id == "1"

    def test_api_key_create_request_default_name(self):
        """Default name is empty string."""
        from models.auth import APIKeyCreateRequest
        req = APIKeyCreateRequest()
        assert req.name == ""


class TestErrorModels:
    """models/error.py"""

    def test_error_response(self):
        """ErrorResponse with all fields."""
        from models.error import ErrorResponse
        resp = ErrorResponse(error="Something went wrong", code="ERR_001")
        assert resp.error == "Something went wrong"
        assert resp.code == "ERR_001"
        assert resp.details is None
        assert resp.request_id is None

    def test_error_detail(self):
        """ErrorDetail with optional fields."""
        from models.error import ErrorDetail
        detail = ErrorDetail(message="Field invalid", field="email", code="INVALID")
        assert detail.field == "email"

    def test_error_response_with_details(self):
        """ErrorResponse with details list."""
        from models.error import ErrorDetail, ErrorResponse
        details = [ErrorDetail(message="bad field")]
        resp = ErrorResponse(error="Validation", code="VALIDATION", details=details)
        assert len(resp.details) == 1


class TestPageModels:
    """models/page.py"""

    def test_page_info_defaults(self):
        """PageInfo has correct defaults."""
        from models.page import PageInfo
        page = PageInfo(id="p1", name="Test Page")
        assert page.content_type == "html"
        assert page.published is False
        assert page.size_bytes == 0
        assert page.parent_id is None

    def test_create_folder_request(self):
        """CreateFolderRequest validation."""
        from models.page import CreateFolderRequest
        req = CreateFolderRequest(name="My Folder")
        assert req.description == ""
        assert req.parent_id is None

    def test_create_bookmark_request(self):
        """CreateBookmarkRequest requires name and url."""
        from models.page import CreateBookmarkRequest
        req = CreateBookmarkRequest(name="Google", url="https://google.com")
        assert req.url == "https://google.com"

    def test_update_page_request_optional(self):
        """UpdatePageRequest fields are all optional."""
        from models.page import UpdatePageRequest
        req = UpdatePageRequest()
        assert req.name is None
        assert req.description is None


class TestSkillModels:
    """models/skill.py"""

    def test_skill_info_defaults(self):
        """SkillInfo has correct defaults."""
        from models.skill import SkillInfo
        skill = SkillInfo(name="test", description="desc", path="/x")
        assert skill.enabled is True
        assert skill.is_bundled is False
        assert skill.version == "1.0.0"
        assert skill.scripts == []
        assert skill.references == []

    def test_skill_detail_inherits(self):
        """SkillDetail extends SkillInfo with content."""
        from models.skill import SkillDetail
        detail = SkillDetail(name="test", description="desc", path="/x", content="# SKILL.md")
        assert detail.content == "# SKILL.md"

    def test_create_skill_request(self):
        """CreateSkillRequest defaults."""
        from models.skill import CreateSkillRequest
        req = CreateSkillRequest(name="test", description="desc")
        assert req.instructions == ""

    def test_update_skill_request_all_optional(self):
        """UpdateSkillRequest fields are all optional."""
        from models.skill import UpdateSkillRequest
        req = UpdateSkillRequest()
        assert req.enabled is None
        assert req.description is None


class TestWorkspaceModels:
    """models/workspace.py"""

    def test_workspace_info_defaults(self):
        """WorkspaceInfo has correct defaults."""
        from models.workspace import WorkspaceInfo
        ws = WorkspaceInfo(id="w1", name="WS", path="/tmp", created_at="2024-01-01")
        assert ws.is_active is False
        assert ws.description == ""

    def test_file_tree_node(self):
        """FileTreeNode basic creation."""
        from models.workspace import FileTreeNode
        node = FileTreeNode(name="src", path="src", type="dir")
        assert node.type == "dir"
        assert node.children is None

    def test_file_content(self):
        """FileContent model."""
        from models.workspace import FileContent
        fc = FileContent(path="main.py", content="print('hello')", total_lines=1)
        assert fc.offset == 0
        assert fc.limit is None

    def test_create_workspace_request(self):
        """CreateWorkspaceRequest defaults."""
        from models.workspace import CreateWorkspaceRequest
        req = CreateWorkspaceRequest(name="WS", path="/tmp")
        assert req.description == ""

    def test_edit_file_request(self):
        """EditFileRequest defaults."""
        from models.workspace import EditFileRequest
        req = EditFileRequest(path="file.py", old_string="old", new_string="new")
        assert req.replace_all is False


class TestMemoryModels:
    """models/memory.py"""

    def test_memory_item(self):
        """MemoryItem basic creation."""
        from models.memory import MemoryItem
        mem = MemoryItem(id="m1", content="test", created_at="2024-01-01", updated_at="2024-01-01")
        assert mem.category == "fact"
        assert mem.confidence == 0.7
        assert mem.is_pinned is False

    def test_create_memory_request_validation(self):
        """CreateMemoryRequest validates confidence range."""
        from models.memory import CreateMemoryRequest
        with pytest.raises(ValidationError):
            CreateMemoryRequest(content="x", confidence=1.5)

    def test_create_memory_request_empty_content(self):
        """CreateMemoryRequest rejects empty content."""
        from models.memory import CreateMemoryRequest
        with pytest.raises(ValidationError):
            CreateMemoryRequest(content="")

    def test_create_memory_request_valid(self):
        """Valid CreateMemoryRequest."""
        from models.memory import CreateMemoryRequest
        req = CreateMemoryRequest(content="Important fact", category="fact", confidence=0.9)
        assert req.content == "Important fact"

    def test_memory_settings_defaults(self):
        """MemorySettings has correct defaults."""
        from models.memory import MemorySettings
        settings = MemorySettings()
        assert settings.enabled is True
        assert settings.max_memories == 50

    def test_update_memory_request_optional(self):
        """UpdateMemoryRequest fields are all optional."""
        from models.memory import UpdateMemoryRequest
        req = UpdateMemoryRequest()
        assert req.content is None
        assert req.category is None

    def test_update_memory_confidence_range(self):
        """UpdateMemoryRequest validates confidence range."""
        from models.memory import UpdateMemoryRequest
        with pytest.raises(ValidationError):
            UpdateMemoryRequest(confidence=-0.1)


class TestSettingsModels:
    """models/settings.py"""

    def test_llm_settings_defaults(self):
        """LLMSettings has correct defaults."""
        from models.settings import LLMSettings
        llm = LLMSettings()
        assert llm.temperature == 0.7
        assert llm.max_tool_rounds == 25

    def test_theme_settings_defaults(self):
        """ThemeSettings has correct defaults."""
        from models.settings import ThemeSettings
        theme = ThemeSettings()
        assert theme.mode == "dark"
        assert theme.accent_color == "amber"
        assert theme.font_scale == 1.0

    def test_app_settings_nested(self):
        """AppSettings contains nested settings."""
        from models.settings import AppSettings
        settings = AppSettings()
        assert settings.llm.temperature == 0.7
        assert settings.memory.enabled is True
        assert settings.profile.platform_name == "Open Agent"
        assert settings.theme.mode == "dark"
        assert settings.custom_models == []

    def test_custom_model(self):
        """CustomModel creation."""
        from models.settings import CustomModel
        cm = CustomModel(label="My Model", model="openai/gpt-4", provider="openai")
        assert cm.label == "My Model"

    def test_update_llm_request_all_optional(self):
        """UpdateLLMRequest fields are all optional."""
        from models.settings import UpdateLLMRequest
        req = UpdateLLMRequest()
        assert req.model is None
        assert req.temperature is None


class TestMCPModels:
    """models/mcp.py"""

    def test_mcp_server_config_defaults(self):
        """MCPServerConfig has correct defaults."""
        from models.mcp import MCPServerConfig
        config = MCPServerConfig()
        assert config.transport == "stdio"
        assert config.enabled is True

    def test_mcp_tool_info(self):
        """MCPToolInfo creation."""
        from models.mcp import MCPToolInfo
        tool = MCPToolInfo(name="read_file", server_name="filesystem")
        assert tool.description is None
        assert tool.input_schema == {}

    def test_mcp_server_info(self):
        """MCPServerInfo creation."""
        from models.mcp import MCPServerConfig, MCPServerInfo
        info = MCPServerInfo(
            name="test", config=MCPServerConfig(), status="disconnected"
        )
        assert info.tools == []
        assert info.error is None


class TestJobModels:
    """models/job.py"""

    def test_job_info_defaults(self):
        """JobInfo has correct defaults."""
        from models.job import JobInfo
        job = JobInfo(
            id="j1", name="Test", prompt="Do something",
            created_at="2024-01-01", updated_at="2024-01-01",
        )
        assert job.enabled is True
        assert job.schedule_type == "once"
        assert job.run_count == 0
        assert job.run_history == []

    def test_create_job_request(self):
        """CreateJobRequest defaults."""
        from models.job import CreateJobRequest
        req = CreateJobRequest(name="Job", prompt="Run")
        assert req.schedule_type == "once"
        assert req.skill_names == []

    def test_job_run_record(self):
        """JobRunRecord creation."""
        from models.job import JobRunRecord
        rec = JobRunRecord(run_id="r1", started_at="2024-01-01", status="success")
        assert rec.finished_at is None
        assert rec.duration_seconds is None


class TestBaseModel:
    """models/_base.py"""

    def test_open_agent_base_config(self):
        """OpenAgentBase has expected config options."""
        from models._base import OpenAgentBase
        config = OpenAgentBase.model_config
        assert config.get("from_attributes") is True
        assert config.get("populate_by_name") is True
        assert config.get("str_strip_whitespace") is True
