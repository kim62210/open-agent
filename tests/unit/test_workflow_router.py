"""Unit tests for core/workflow_router.py — workflow routing."""

from unittest.mock import AsyncMock, MagicMock, patch

from core.workflow_router import WorkflowRouter, workflow_router


# ── WorkflowRouter init ──────────────────────────────────────────────


class TestWorkflowRouterInit:
    def test_init_empty_skills(self):
        router = WorkflowRouter()
        assert router._skill_summaries == {}


# ── update_skills ─────────────────────────────────────────────────────


class TestUpdateSkills:
    def test_update(self):
        router = WorkflowRouter()
        router.update_skills({"impl": "implementation", "debug": "debugging"})
        assert "impl" in router._skill_summaries
        assert "debug" in router._skill_summaries

    def test_update_replaces_old(self):
        router = WorkflowRouter()
        router.update_skills({"old": "old skill"})
        router.update_skills({"new": "new skill"})
        assert "old" not in router._skill_summaries
        assert "new" in router._skill_summaries


# ── _extract_recent_context ──────────────────────────────────────────


class TestExtractRecentContext:
    def test_empty_messages(self):
        result = WorkflowRouter._extract_recent_context([])
        assert result == ""

    def test_single_user_message(self):
        messages = [{"role": "user", "content": "hello"}]
        result = WorkflowRouter._extract_recent_context(messages)
        assert "user: hello" in result

    def test_user_assistant_pair(self):
        messages = [
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "answer"},
        ]
        result = WorkflowRouter._extract_recent_context(messages)
        assert "user: question" in result
        assert "assistant: answer" in result

    def test_list_content_extraction(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hello from list"},
                    {"type": "image", "url": "http://example.com"},
                ],
            }
        ]
        result = WorkflowRouter._extract_recent_context(messages)
        assert "hello from list" in result

    def test_limits_to_4_entries(self):
        messages = [
            {"role": "user", "content": f"msg{i}"} for i in range(10)
        ]
        result = WorkflowRouter._extract_recent_context(messages)
        parts = result.split(" → ")
        assert len(parts) <= 4

    def test_skips_tool_role(self):
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "tool", "content": "tool result"},
            {"role": "assistant", "content": "reply"},
        ]
        result = WorkflowRouter._extract_recent_context(messages)
        assert "tool result" not in result

    def test_truncates_long_content(self):
        long_content = "x" * 200
        messages = [{"role": "user", "content": long_content}]
        result = WorkflowRouter._extract_recent_context(messages)
        assert len(result) < 200


# ── _build_routing_prompt ─────────────────────────────────────────────


class TestBuildRoutingPrompt:
    def test_empty_skills_returns_empty(self):
        router = WorkflowRouter()
        prompt = router._build_routing_prompt()
        assert prompt == ""

    def test_includes_skill_list(self):
        router = WorkflowRouter()
        router.update_skills({"impl": "implementation", "debug": "debugging"})
        prompt = router._build_routing_prompt()
        assert "impl: implementation" in prompt
        assert "debug: debugging" in prompt

    def test_includes_context_section(self):
        router = WorkflowRouter()
        router.update_skills({"impl": "implementation"})
        prompt = router._build_routing_prompt(
            prev_workflow="impl",
            turn_count=3,
            has_tool_results=True,
            recent_context="user: hi",
        )
        assert "impl" in prompt
        assert "3" in prompt

    def test_no_context_section_on_first_turn(self):
        router = WorkflowRouter()
        router.update_skills({"impl": "implementation"})
        prompt = router._build_routing_prompt(
            turn_count=0,
            prev_workflow=None,
            recent_context="",
        )
        # Should not contain the context section template markers
        assert "turn_count" not in prompt.lower() or "0" not in prompt


# ── route (async) ─────────────────────────────────────────────────────


class TestRoute:
    async def test_returns_none_for_empty_skills(self):
        router = WorkflowRouter()
        result = await router.route("implement a feature")
        assert result is None

    async def test_returns_none_for_empty_message(self):
        router = WorkflowRouter()
        router.update_skills({"impl": "implementation"})
        result = await router.route("")
        assert result is None

    async def test_returns_none_for_whitespace_message(self):
        router = WorkflowRouter()
        router.update_skills({"impl": "implementation"})
        result = await router.route("   ")
        assert result is None

    async def test_routes_to_skill(self):
        router = WorkflowRouter()
        router.update_skills({"impl": "implementation", "debug": "debugging"})

        mock_llm = MagicMock()
        mock_llm.classify = AsyncMock(return_value="impl")
        with patch("open_agent.core.llm.llm_client", mock_llm):
            result = await router.route("implement new feature")

        assert result == "impl"

    async def test_routes_none_when_llm_returns_none(self):
        router = WorkflowRouter()
        router.update_skills({"impl": "implementation"})

        mock_llm = MagicMock()
        mock_llm.classify = AsyncMock(return_value="none")
        with patch("open_agent.core.llm.llm_client", mock_llm):
            result = await router.route("hello how are you")

        assert result is None

    async def test_routes_with_messages_context(self):
        router = WorkflowRouter()
        router.update_skills({"impl": "implementation", "debug": "debugging"})

        messages = [
            {"role": "user", "content": "fix the bug"},
            {"role": "assistant", "content": "looking into it"},
        ]

        mock_llm = MagicMock()
        mock_llm.classify = AsyncMock(return_value="debug")
        with patch("open_agent.core.llm.llm_client", mock_llm):
            result = await router.route(
                "keep debugging",
                messages=messages,
                prev_workflow="debug",
            )

        assert result == "debug"


# ── singleton ─────────────────────────────────────────────────────────


class TestSingleton:
    def test_singleton_exists(self):
        assert isinstance(workflow_router, WorkflowRouter)
