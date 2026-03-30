"""LLMClient unit tests — mocked LLM calls."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from open_agent.core.llm import LLMClient, _DEFAULT_CONTEXT_WINDOW, _MIN_OUTPUT_TOKENS


@pytest.fixture()
def llm_client() -> LLMClient:
    """Fresh LLMClient instance."""
    return LLMClient()


# --- _resolve_api_key ---


class TestResolveApiKey:
    """API key resolution from model name."""

    def test_openai_model(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        assert LLMClient._resolve_api_key("gpt-4") == "sk-openai"

    def test_openai_prefixed_model(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        assert LLMClient._resolve_api_key("openai/gpt-4o") == "sk-openai"

    def test_o1_model(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        assert LLMClient._resolve_api_key("o1-preview") == "sk-openai"

    def test_o3_model(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        assert LLMClient._resolve_api_key("o3-mini") == "sk-openai"

    def test_o4_model(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        assert LLMClient._resolve_api_key("o4-mini") == "sk-openai"

    def test_anthropic_model(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anthropic")
        assert LLMClient._resolve_api_key("claude-3-opus") == "sk-anthropic"

    def test_anthropic_prefixed_model(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anthropic")
        assert LLMClient._resolve_api_key("anthropic/claude-3") == "sk-anthropic"

    def test_xai_model(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "sk-xai")
        assert LLMClient._resolve_api_key("grok-2") == "sk-xai"

    def test_xai_prefixed_model(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "sk-xai")
        assert LLMClient._resolve_api_key("xai/grok-2") == "sk-xai"

    def test_openrouter_model(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        assert LLMClient._resolve_api_key("openrouter/meta/llama-3") == "sk-or"

    def test_gemini_model(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "sk-google")
        assert LLMClient._resolve_api_key("gemini/gemini-pro") == "sk-google"

    def test_google_prefixed_model(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "sk-google")
        assert LLMClient._resolve_api_key("google/gemini-pro") == "sk-google"

    def test_unknown_model_returns_none(self, monkeypatch):
        """Unknown model prefix returns None (no fallback)."""
        monkeypatch.setenv("GOOGLE_API_KEY", "sk-google-fallback")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert LLMClient._resolve_api_key("unknown-model") is None


# --- _safe_temperature ---


class TestSafeTemperature:
    """Temperature safety for Gemini 3+ models."""

    def test_gemini3_low_temp_clamped(self):
        assert LLMClient._safe_temperature("gemini-3.0-flash", 0.5) == 1.0

    def test_gemini3_high_temp_unchanged(self):
        assert LLMClient._safe_temperature("gemini-3.0-flash", 1.5) == 1.5

    def test_non_gemini3_low_temp_unchanged(self):
        assert LLMClient._safe_temperature("gpt-4", 0.2) == 0.2

    def test_gemini2_not_affected(self):
        assert LLMClient._safe_temperature("gemini/gemini-2.0-flash", 0.3) == 0.3

    def test_gemini3_exact_boundary(self):
        assert LLMClient._safe_temperature("gemini-3.0-pro", 1.0) == 1.0


# --- _extract_choice ---


class TestExtractChoice:
    """LLM response choice extraction."""

    def test_exact_match(self):
        assert LLMClient._extract_choice("yes", ["yes", "no"]) == "yes"

    def test_case_insensitive(self):
        assert LLMClient._extract_choice("YES", ["yes", "no"]) == "yes"

    def test_first_line_match(self):
        assert LLMClient._extract_choice("yes\nsome explanation", ["yes", "no"]) == "yes"

    def test_first_word_match(self):
        assert LLMClient._extract_choice("yes, I agree", ["yes", "no"]) == "yes"

    def test_substring_match(self):
        assert LLMClient._extract_choice(
            "I think the answer is search", ["search", "chat"]
        ) == "search"

    def test_no_match_returns_none(self):
        assert LLMClient._extract_choice("maybe", ["yes", "no"]) is None

    def test_longer_choice_preferred_in_substring(self):
        """Longer choices are matched first to avoid partial matches."""
        result = LLMClient._extract_choice(
            "use tool_call for this", ["tool_call", "tool"]
        )
        assert result == "tool_call"

    def test_empty_text(self):
        assert LLMClient._extract_choice("", ["yes", "no"]) is None


# --- _get_config ---


class TestGetConfig:
    """Config retrieval from settings_manager."""

    def test_get_config_basic(self, llm_client: LLMClient, settings_manager):
        """Config is constructed from settings_manager."""
        with patch(
            "open_agent.core.settings_manager.settings_manager", settings_manager
        ):
            config = llm_client._get_config()
            assert "model" in config
            assert "api_key" in config
            assert "temperature" in config
            assert "max_tokens" in config

    def test_get_config_with_api_base(self, llm_client: LLMClient, settings_manager):
        """api_base is included when set."""
        from open_agent.models.settings import LLMSettings

        settings_manager._settings.llm = LLMSettings(
            model="test", api_base="http://localhost:8000", api_key="key"
        )
        with patch(
            "open_agent.core.settings_manager.settings_manager", settings_manager
        ):
            config = llm_client._get_config()
            assert config["api_base"] == "http://localhost:8000"

    def test_get_config_without_api_base(self, llm_client: LLMClient, settings_manager):
        """api_base is omitted when None."""
        from open_agent.models.settings import LLMSettings

        settings_manager._settings.llm = LLMSettings(
            model="test", api_base=None, api_key="key"
        )
        with patch(
            "open_agent.core.settings_manager.settings_manager", settings_manager
        ):
            config = llm_client._get_config()
            assert "api_base" not in config

    def test_get_config_reasoning_effort_for_supported_provider(
        self, llm_client: LLMClient, settings_manager
    ):
        """reasoning_effort is included for supported providers."""
        from open_agent.models.settings import LLMSettings

        settings_manager._settings.llm = LLMSettings(
            model="openai/gpt-4", api_key="key", reasoning_effort="high"
        )
        with patch(
            "open_agent.core.settings_manager.settings_manager", settings_manager
        ):
            config = llm_client._get_config()
            assert config.get("reasoning_effort") == "high"

    def test_get_config_reasoning_effort_excluded_for_unsupported(
        self, llm_client: LLMClient, settings_manager
    ):
        """reasoning_effort is excluded for self-hosted models."""
        from open_agent.models.settings import LLMSettings

        settings_manager._settings.llm = LLMSettings(
            model="hosted_vllm/my-model", api_key="key", reasoning_effort="high"
        )
        with patch(
            "open_agent.core.settings_manager.settings_manager", settings_manager
        ):
            config = llm_client._get_config()
            assert "reasoning_effort" not in config


# --- get_context_window ---


class TestGetContextWindow:
    """Context window resolution with priority chain."""

    def test_user_setting_priority(self, llm_client: LLMClient, settings_manager):
        """User-configured context_window takes priority."""
        from open_agent.models.settings import LLMSettings

        settings_manager._settings.llm = LLMSettings(
            model="test", context_window=200000, api_key="key"
        )
        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            assert llm_client.get_context_window() == 200000

    def test_litellm_model_info_fallback(self, llm_client: LLMClient, settings_manager):
        """Falls back to LiteLLM get_model_info when user setting is 0."""
        from open_agent.models.settings import LLMSettings

        settings_manager._settings.llm = LLMSettings(
            model="gpt-4", context_window=0, api_key="key"
        )
        mock_info = {"max_input_tokens": 128000}
        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch("open_agent.core.llm._litellm_get_model_info", return_value=mock_info),
        ):
            assert llm_client.get_context_window() == 128000

    def test_litellm_model_info_returns_zero(self, llm_client: LLMClient, settings_manager):
        """Falls through to default when model_info returns 0."""
        from open_agent.models.settings import LLMSettings

        settings_manager._settings.llm = LLMSettings(
            model="gpt-4", context_window=0, api_key="key"
        )
        mock_info = {"max_input_tokens": 0}
        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch("open_agent.core.llm._litellm_get_model_info", return_value=mock_info),
        ):
            assert llm_client.get_context_window() == _DEFAULT_CONTEXT_WINDOW

    def test_litellm_model_info_exception(self, llm_client: LLMClient, settings_manager):
        """Falls through to default when model_info raises."""
        from open_agent.models.settings import LLMSettings

        settings_manager._settings.llm = LLMSettings(
            model="gpt-4", context_window=0, api_key="key"
        )
        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch(
                "open_agent.core.llm._litellm_get_model_info",
                side_effect=RuntimeError("fail"),
            ),
        ):
            assert llm_client.get_context_window() == _DEFAULT_CONTEXT_WINDOW

    def test_fallback_default(self, llm_client: LLMClient, settings_manager):
        """Falls back to default when no model_info available."""
        from open_agent.models.settings import LLMSettings

        settings_manager._settings.llm = LLMSettings(
            model="unknown", context_window=0, api_key="key"
        )
        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch("open_agent.core.llm._litellm_get_model_info", None),
        ):
            assert llm_client.get_context_window() == _DEFAULT_CONTEXT_WINDOW


# --- count_tokens ---


class TestCountTokens:
    """Token counting with LiteLLM fallback."""

    def test_litellm_counter_with_tools(self, llm_client: LLMClient, settings_manager):
        """Uses LiteLLM native counter when available (with tools)."""
        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch("open_agent.core.llm._litellm_token_counter", return_value=500),
        ):
            result = llm_client.count_tokens(
                [{"role": "user", "content": "hello"}],
                tools=[{"type": "function", "function": {"name": "test"}}],
            )
            assert result == 500

    def test_litellm_counter_fallback_messages_only(
        self, llm_client: LLMClient, settings_manager
    ):
        """Falls back to messages-only counter + manual tool estimation."""

        def counter_side_effect(model, messages, tools=None):
            if tools is not None:
                raise TypeError("tools not supported")
            return 100

        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch(
                "open_agent.core.llm._litellm_token_counter",
                side_effect=counter_side_effect,
            ),
        ):
            result = llm_client.count_tokens(
                [{"role": "user", "content": "hello"}],
                tools=[{"type": "function", "function": {"name": "test"}}],
            )
            # 100 base + tool schema estimation
            assert result > 100

    def test_char_estimation_fallback(self, llm_client: LLMClient, settings_manager):
        """Falls back to character-based estimation when LiteLLM unavailable."""
        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch("open_agent.core.llm._litellm_token_counter", None),
        ):
            result = llm_client.count_tokens(
                [{"role": "user", "content": "hello world test message"}]
            )
            assert result >= 1

    def test_char_estimation_with_list_content(self, llm_client: LLMClient, settings_manager):
        """Character estimation handles list-type content (multimodal)."""
        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch("open_agent.core.llm._litellm_token_counter", None),
        ):
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "describe this image"},
                        {"type": "image_url", "image_url": {"url": "data:..."}},
                    ],
                }
            ]
            result = llm_client.count_tokens(messages)
            assert result >= 1

    def test_char_estimation_with_tools(self, llm_client: LLMClient, settings_manager):
        """Character estimation includes tool schema size."""
        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch("open_agent.core.llm._litellm_token_counter", None),
        ):
            tools = [{"type": "function", "function": {"name": "search", "parameters": {}}}]
            result_with_tools = llm_client.count_tokens(
                [{"role": "user", "content": "hello"}], tools=tools
            )
            result_without = llm_client.count_tokens(
                [{"role": "user", "content": "hello"}]
            )
            assert result_with_tools > result_without

    def test_litellm_counter_both_calls_fail(self, llm_client: LLMClient, settings_manager):
        """Falls through to char estimation when both LiteLLM calls fail."""

        def always_fail(model, messages, tools=None):
            raise RuntimeError("counter broken")

        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch(
                "open_agent.core.llm._litellm_token_counter",
                side_effect=always_fail,
            ),
        ):
            result = llm_client.count_tokens(
                [{"role": "user", "content": "test message"}]
            )
            assert result >= 1


# --- _clamp_max_tokens ---


class TestClampMaxTokens:
    """Dynamic max_tokens clamping."""

    def test_clamp_when_context_nearly_full(self, llm_client: LLMClient, settings_manager):
        """Clamps to MIN_OUTPUT_TOKENS when context is nearly full."""
        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch.object(llm_client, "get_context_window", return_value=1000),
            patch.object(llm_client, "count_tokens", return_value=990),
        ):
            kwargs = {"messages": [], "max_tokens": 16384}
            result = llm_client._clamp_max_tokens(kwargs)
            assert result["max_tokens"] == _MIN_OUTPUT_TOKENS

    def test_clamp_when_available_less_than_configured(
        self, llm_client: LLMClient, settings_manager
    ):
        """Clamps max_tokens to available tokens when less than configured."""
        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch.object(llm_client, "get_context_window", return_value=50000),
            patch.object(llm_client, "count_tokens", return_value=40000),
        ):
            kwargs = {"messages": [], "max_tokens": 16384}
            result = llm_client._clamp_max_tokens(kwargs)
            # available = 50000 - 40000 - 256 = 9744, less than 16384
            assert result["max_tokens"] < 16384
            assert result["max_tokens"] > _MIN_OUTPUT_TOKENS

    def test_no_clamp_when_sufficient_space(self, llm_client: LLMClient, settings_manager):
        """max_tokens unchanged when there's plenty of context space."""
        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch.object(llm_client, "get_context_window", return_value=200000),
            patch.object(llm_client, "count_tokens", return_value=1000),
        ):
            kwargs = {"messages": [], "max_tokens": 16384}
            result = llm_client._clamp_max_tokens(kwargs)
            assert result["max_tokens"] == 16384

    def test_default_max_tokens_when_not_set(self, llm_client: LLMClient, settings_manager):
        """Uses 16384 default when max_tokens not in kwargs."""
        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch.object(llm_client, "get_context_window", return_value=200000),
            patch.object(llm_client, "count_tokens", return_value=1000),
        ):
            kwargs = {"messages": []}
            result = llm_client._clamp_max_tokens(kwargs)
            # No clamping needed, but configured fallback is 16384
            assert "max_tokens" not in result or result.get("max_tokens", 16384) == 16384


# --- classify ---


class TestClassify:
    """Classify method tests."""

    async def test_classify_with_content(self, llm_client: LLMClient, settings_manager):
        """classify returns a matching choice from content."""
        mock_msg = MagicMock()
        mock_msg.content = "search"
        mock_msg.reasoning_content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch("open_agent.core.llm.acompletion", AsyncMock(return_value=mock_response)),
        ):
            result = await llm_client.classify(
                "Classify the intent", ["search", "chat", "code"], "find me some docs"
            )
            assert result == "search"

    async def test_classify_with_reasoning_content(
        self, llm_client: LLMClient, settings_manager
    ):
        """classify falls back to reasoning_content when content is empty."""
        mock_msg = MagicMock()
        mock_msg.content = None
        mock_msg.reasoning_content = "search"
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch("open_agent.core.llm.acompletion", AsyncMock(return_value=mock_response)),
        ):
            result = await llm_client.classify(
                "Classify the intent", ["search", "chat"], "find docs"
            )
            assert result == "search"

    async def test_classify_empty_content_no_reasoning(
        self, llm_client: LLMClient, settings_manager
    ):
        """classify returns None when both content and reasoning are empty."""
        mock_msg = MagicMock()
        mock_msg.content = None
        mock_msg.reasoning_content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch("open_agent.core.llm.acompletion", AsyncMock(return_value=mock_response)),
        ):
            result = await llm_client.classify(
                "Classify", ["search", "chat"], "test"
            )
            assert result is None

    async def test_classify_no_match(self, llm_client: LLMClient, settings_manager):
        """classify returns None when LLM response doesn't match any choice."""
        mock_msg = MagicMock()
        mock_msg.content = "definitely not a valid choice"
        mock_msg.reasoning_content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch("open_agent.core.llm.acompletion", AsyncMock(return_value=mock_response)),
        ):
            result = await llm_client.classify(
                "Classify", ["alpha", "beta"], "test"
            )
            assert result is None

    async def test_classify_exception_returns_none(
        self, llm_client: LLMClient, settings_manager
    ):
        """classify returns None when LLM call raises."""
        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch(
                "open_agent.core.llm.acompletion",
                AsyncMock(side_effect=RuntimeError("API down")),
            ),
        ):
            result = await llm_client.classify(
                "Classify", ["yes", "no"], "test"
            )
            assert result is None

    async def test_classify_with_api_base(self, llm_client: LLMClient, settings_manager):
        """classify passes api_base when configured."""
        from open_agent.models.settings import LLMSettings

        settings_manager._settings.llm = LLMSettings(
            model="test", api_base="http://localhost:8000", api_key="key"
        )
        mock_msg = MagicMock()
        mock_msg.content = "yes"
        mock_msg.reasoning_content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_acompletion = AsyncMock(return_value=mock_response)
        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch("open_agent.core.llm.acompletion", mock_acompletion),
        ):
            await llm_client.classify("Q", ["yes", "no"], "test")
            call_kwargs = mock_acompletion.call_args[1]
            assert call_kwargs["api_base"] == "http://localhost:8000"


# --- chat_completion ---


class TestChatCompletion:
    """chat_completion method tests."""

    async def test_basic_completion(self, llm_client: LLMClient, settings_manager):
        """Basic chat_completion returns result dict."""
        mock_msg = MagicMock()
        mock_msg.content = "Hello!"
        mock_msg.reasoning_content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.model_dump.return_value = {
            "choices": [{"message": {"content": "Hello!", "tool_calls": None}}]
        }

        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch("open_agent.core.llm.acompletion", AsyncMock(return_value=mock_response)),
            patch.object(llm_client, "_clamp_max_tokens", lambda k, t=None: k),
        ):
            result = await llm_client.chat_completion(
                [{"role": "user", "content": "Hi"}]
            )
            assert "choices" in result

    async def test_completion_with_tools(self, llm_client: LLMClient, settings_manager):
        """chat_completion sets tool_choice and parallel_tool_calls with tools."""
        from open_agent.models.settings import LLMSettings

        settings_manager._settings.llm = LLMSettings(
            model="openai/gpt-4", api_key="key"
        )
        mock_msg = MagicMock()
        mock_msg.content = "tool result"
        mock_msg.reasoning_content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.model_dump.return_value = {
            "choices": [{"message": {"content": "tool result", "tool_calls": None}}]
        }

        mock_acompletion = AsyncMock(return_value=mock_response)
        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch("open_agent.core.llm.acompletion", mock_acompletion),
            patch.object(llm_client, "_clamp_max_tokens", lambda k, t=None: k),
        ):
            tools = [{"type": "function", "function": {"name": "search"}}]
            await llm_client.chat_completion(
                [{"role": "user", "content": "search"}], tools=tools
            )
            call_kwargs = mock_acompletion.call_args[1]
            assert call_kwargs["tool_choice"] == "auto"
            assert call_kwargs["parallel_tool_calls"] is True

    async def test_completion_gpt_oss_no_parallel_tool_calls(
        self, llm_client: LLMClient, settings_manager
    ):
        """gpt-oss models skip parallel_tool_calls."""
        from open_agent.models.settings import LLMSettings

        settings_manager._settings.llm = LLMSettings(
            model="hosted_vllm/openai/gpt-oss-120b",
            api_key="key",
            api_base="http://localhost",
        )

        mock_msg = MagicMock()
        mock_msg.content = "result"
        mock_msg.reasoning_content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.model_dump.return_value = {
            "choices": [{"message": {"content": "result", "tool_calls": None}}]
        }

        mock_acompletion = AsyncMock(return_value=mock_response)
        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch("open_agent.core.llm.acompletion", mock_acompletion),
            patch.object(llm_client, "_clamp_max_tokens", lambda k, t=None: k),
        ):
            tools = [{"type": "function", "function": {"name": "test"}}]
            await llm_client.chat_completion(
                [{"role": "user", "content": "test"}], tools=tools
            )
            call_kwargs = mock_acompletion.call_args[1]
            assert "parallel_tool_calls" not in call_kwargs

    async def test_completion_reasoning_fallback_no_tools(
        self, llm_client: LLMClient, settings_manager
    ):
        """Reasoning model fallback: reasoning_content becomes content when no tools."""
        mock_msg = MagicMock()
        mock_msg.content = None
        mock_msg.reasoning_content = "I think the answer is..."
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.model_dump.return_value = {
            "choices": [{"message": {"content": None, "tool_calls": None}}]
        }

        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch("open_agent.core.llm.acompletion", AsyncMock(return_value=mock_response)),
            patch.object(llm_client, "_clamp_max_tokens", lambda k, t=None: k),
        ):
            result = await llm_client.chat_completion(
                [{"role": "user", "content": "think about this"}]
            )
            msg = result["choices"][0]["message"]
            assert msg["content"] == "I think the answer is..."

    async def test_completion_reasoning_fallback_with_tools(
        self, llm_client: LLMClient, settings_manager
    ):
        """Reasoning model fallback: reasoning stored as _reasoning_content with tools."""
        mock_msg = MagicMock()
        mock_msg.content = None
        mock_msg.reasoning_content = "thinking about tools..."
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.model_dump.return_value = {
            "choices": [{"message": {"content": None, "tool_calls": None}}]
        }

        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch("open_agent.core.llm.acompletion", AsyncMock(return_value=mock_response)),
            patch.object(llm_client, "_clamp_max_tokens", lambda k, t=None: k),
        ):
            tools = [{"type": "function", "function": {"name": "test"}}]
            result = await llm_client.chat_completion(
                [{"role": "user", "content": "use tools"}], tools=tools
            )
            msg = result["choices"][0]["message"]
            assert msg.get("_reasoning_content") == "thinking about tools..."

    async def test_completion_reasoning_effort_override(
        self, llm_client: LLMClient, settings_manager
    ):
        """Dynamic reasoning_effort override is applied for supported providers."""
        from open_agent.models.settings import LLMSettings

        settings_manager._settings.llm = LLMSettings(
            model="openai/gpt-4", api_key="key"
        )
        mock_msg = MagicMock()
        mock_msg.content = "done"
        mock_msg.reasoning_content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.model_dump.return_value = {
            "choices": [{"message": {"content": "done", "tool_calls": None}}]
        }

        mock_acompletion = AsyncMock(return_value=mock_response)
        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch("open_agent.core.llm.acompletion", mock_acompletion),
            patch.object(llm_client, "_clamp_max_tokens", lambda k, t=None: k),
        ):
            await llm_client.chat_completion(
                [{"role": "user", "content": "test"}], reasoning_effort="high"
            )
            call_kwargs = mock_acompletion.call_args[1]
            assert call_kwargs["reasoning_effort"] == "high"


# --- chat_stream ---


class TestChatStream:
    """chat_stream content-only path."""

    async def test_stream_yields_content(self, llm_client: LLMClient, settings_manager):
        """chat_stream yields typed event dicts for content chunks."""
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta.content = "Hello"
        chunk1.choices[0].delta.tool_calls = None

        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta.content = " World"
        chunk2.choices[0].delta.tool_calls = None

        chunk3 = MagicMock()
        chunk3.choices = [MagicMock()]
        chunk3.choices[0].delta.content = None  # end chunk
        chunk3.choices[0].delta.tool_calls = None

        async def mock_stream():
            for chunk in [chunk1, chunk2, chunk3]:
                yield chunk

        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch("open_agent.core.llm.acompletion", AsyncMock(return_value=mock_stream())),
            patch.object(llm_client, "_clamp_max_tokens", lambda k, t=None: k),
        ):
            events = []
            async for event in llm_client.chat_stream(
                [{"role": "user", "content": "hi"}]
            ):
                events.append(event)

            # Should have 2 content_delta events + 1 done event
            content_events = [e for e in events if e["type"] == "content_delta"]
            assert len(content_events) == 2
            assert content_events[0]["content"] == "Hello"
            assert content_events[1]["content"] == " World"
            done_events = [e for e in events if e["type"] == "done"]
            assert len(done_events) == 1
            assert done_events[0]["content"] == "Hello World"


# --- get_system_prompt ---


class TestGetSystemPrompt:
    """System prompt retrieval."""

    def test_returns_system_prompt(self, llm_client: LLMClient, settings_manager):
        """Returns system_prompt from settings_manager."""
        from open_agent.models.settings import LLMSettings

        settings_manager._settings.llm = LLMSettings(
            model="test", system_prompt="You are a helpful assistant.", api_key="key"
        )
        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            assert llm_client.get_system_prompt() == "You are a helpful assistant."

    def test_returns_empty_default(self, llm_client: LLMClient, settings_manager):
        """Returns empty string when no system prompt configured."""
        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            assert llm_client.get_system_prompt() == ""
