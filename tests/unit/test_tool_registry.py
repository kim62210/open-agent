"""Unit tests for core/tool_registry.py — tool registration, search, intent detection."""

from core.tool_registry import (
    FIND_TOOLS_TOOL,
    ToolEntry,
    ToolRegistry,
    detect_intent,
    tool_registry,
)


def _make_tool_def(name: str, description: str = "") -> dict:
    """Helper to create a minimal tool definition."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": {}},
        },
    }


# ── ToolRegistry basics ──────────────────────────────────────────────


class TestToolRegistryBasics:
    def test_register_and_search(self):
        reg = ToolRegistry()
        reg.register("read_file", _make_tool_def("read_file", "Read a file"), "workspace")
        results = reg.search("read")
        assert len(results) == 1
        assert results[0].name == "read_file"

    def test_register_always_on(self):
        reg = ToolRegistry()
        reg.register("respond_directly", _make_tool_def("respond_directly", "Direct response"), "meta", always_on=True)
        always_on = reg.get_always_on_tools()
        assert len(always_on) == 1

    def test_auto_always_on_by_name(self):
        reg = ToolRegistry()
        reg.register("read_skill", _make_tool_def("read_skill", "Read skill"), "skill", always_on=False)
        entry = reg._entries["read_skill"]
        assert entry.always_on is True

    def test_unregister(self):
        reg = ToolRegistry()
        reg.register("test_tool", _make_tool_def("test_tool"), "workspace")
        reg.unregister("test_tool")
        assert "test_tool" not in reg._entries

    def test_unregister_nonexistent(self):
        reg = ToolRegistry()
        reg.unregister("nonexistent")  # Should not raise

    def test_clear(self):
        reg = ToolRegistry()
        reg.register("a", _make_tool_def("a"), "workspace")
        reg.register("b", _make_tool_def("b"), "mcp")
        reg.clear()
        assert len(reg._entries) == 0


# ── search ────────────────────────────────────────────────────────────


class TestToolRegistrySearch:
    def test_empty_query_returns_all(self):
        reg = ToolRegistry()
        reg.register("a", _make_tool_def("a", "alpha tool"), "workspace")
        reg.register("b", _make_tool_def("b", "beta tool"), "mcp")
        results = reg.search("")
        assert len(results) == 2

    def test_empty_query_respects_limit(self):
        reg = ToolRegistry()
        for i in range(20):
            reg.register(f"tool_{i}", _make_tool_def(f"tool_{i}"), "workspace")
        results = reg.search("", max_results=5)
        assert len(results) == 5

    def test_name_match_weighted_higher(self):
        reg = ToolRegistry()
        reg.register("file_reader", _make_tool_def("file_reader", "reads files from disk"), "workspace")
        reg.register("data_processor", _make_tool_def("data_processor", "processes file data"), "workspace")
        results = reg.search("file")
        assert results[0].name == "file_reader"

    def test_category_match(self):
        reg = ToolRegistry()
        reg.register("tool_a", _make_tool_def("tool_a", "some tool"), "mcp")
        results = reg.search("mcp")
        assert len(results) == 1

    def test_no_results(self):
        reg = ToolRegistry()
        reg.register("tool_a", _make_tool_def("tool_a", "alpha"), "workspace")
        results = reg.search("zzzzzzz")
        assert len(results) == 0

    def test_underscore_split(self):
        reg = ToolRegistry()
        reg.register("read_file", _make_tool_def("read_file", "Read a file"), "workspace")
        results = reg.search("read_file")
        assert len(results) == 1


# ── get methods ───────────────────────────────────────────────────────


class TestGetMethods:
    def test_get_tools_by_names(self):
        reg = ToolRegistry()
        reg.register("a", _make_tool_def("a"), "workspace")
        reg.register("b", _make_tool_def("b"), "mcp")
        reg.register("c", _make_tool_def("c"), "skill")
        tools = reg.get_tools_by_names({"a", "c"})
        assert len(tools) == 2

    def test_get_tools_by_names_missing(self):
        reg = ToolRegistry()
        reg.register("a", _make_tool_def("a"), "workspace")
        tools = reg.get_tools_by_names({"a", "nonexistent"})
        assert len(tools) == 1

    def test_get_all_tool_defs(self):
        reg = ToolRegistry()
        reg.register("a", _make_tool_def("a"), "workspace")
        reg.register("b", _make_tool_def("b"), "mcp")
        all_tools = reg.get_all_tool_defs()
        assert len(all_tools) == 2

    def test_get_category_summary(self):
        reg = ToolRegistry()
        reg.register("a", _make_tool_def("a"), "workspace")
        reg.register("b", _make_tool_def("b"), "workspace")
        reg.register("c", _make_tool_def("c"), "mcp")
        summary = reg.get_category_summary()
        assert summary["workspace"] == 2
        assert summary["mcp"] == 1


# ── refresh_all ───────────────────────────────────────────────────────


class TestRefreshAll:
    def test_refresh_registers_all_categories(self):
        reg = ToolRegistry()
        reg.refresh_all(
            mcp_tools=[_make_tool_def("mcp_tool", "MCP tool")],
            skill_tools=[_make_tool_def("skill_tool", "Skill tool")],
            workspace_tools=[_make_tool_def("ws_tool", "Workspace tool")],
            job_tools=[_make_tool_def("job_tool", "Job tool")],
            extra_tools=[_make_tool_def("extra_tool", "Extra tool")],
        )
        assert len(reg._entries) == 5
        assert reg._entries["skill_tool"].always_on is True
        assert reg._entries["extra_tool"].always_on is True

    def test_refresh_clears_existing(self):
        reg = ToolRegistry()
        reg.register("old_tool", _make_tool_def("old_tool"), "workspace")
        reg.refresh_all(
            mcp_tools=[], skill_tools=[], workspace_tools=[], job_tools=[],
        )
        assert "old_tool" not in reg._entries


# ── format_search_result ──────────────────────────────────────────────


class TestFormatSearchResult:
    def test_format_with_results(self):
        reg = ToolRegistry()
        entries = [
            ToolEntry(name="tool_a", description="A tool", category="workspace", tool_def={}, always_on=False),
            ToolEntry(name="tool_b", description="B tool", category="mcp", tool_def={}, always_on=False),
        ]
        result = reg.format_search_result(entries)
        assert "2" in result
        assert "tool_a" in result
        assert "tool_b" in result

    def test_format_empty(self):
        reg = ToolRegistry()
        result = reg.format_search_result([])
        assert "없습니다" in result or "결과" in result

    def test_format_truncates_long_description(self):
        reg = ToolRegistry()
        long_desc = "x" * 200
        entries = [ToolEntry(name="t", description=long_desc, category="ws", tool_def={}, always_on=False)]
        result = reg.format_search_result(entries)
        assert "..." in result


# ── detect_intent ─────────────────────────────────────────────────────


class TestDetectIntent:
    def test_workspace_intent(self):
        categories = detect_intent("Read the file contents")
        assert "workspace" in categories

    def test_job_intent(self):
        categories = detect_intent("schedule a task every day")
        assert "job" in categories

    def test_mcp_intent(self):
        categories = detect_intent("search the web for news")
        assert "mcp" in categories

    def test_no_intent(self):
        categories = detect_intent("tell me a joke")
        assert len(categories) == 0

    def test_multiple_intents(self):
        categories = detect_intent("read the file and search the web")
        assert "workspace" in categories
        assert "mcp" in categories

    def test_korean_intents(self):
        categories = detect_intent("파일을 읽어줘")
        assert "workspace" in categories

    def test_case_insensitive(self):
        categories = detect_intent("BASH command execution")
        assert "workspace" in categories


# ── FIND_TOOLS_TOOL constant ─────────────────────────────────────────


class TestFindToolsTool:
    def test_structure(self):
        assert FIND_TOOLS_TOOL["type"] == "function"
        assert FIND_TOOLS_TOOL["function"]["name"] == "find_tools"
        assert "query" in FIND_TOOLS_TOOL["function"]["parameters"]["properties"]


# ── singleton ─────────────────────────────────────────────────────────


class TestSingleton:
    def test_singleton_exists(self):
        assert isinstance(tool_registry, ToolRegistry)
