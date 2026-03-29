"""LLMClient unit tests — provider resolution, simple_completion, chat_stream, constants."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from open_agent.core.llm import (
    _PROVIDER_KEY_MAP,
    REASONING_EFFORT_PROVIDERS,
    LLMClient,
)

# ---------------------------------------------------------------------------
# Task 6.1: _resolve_api_key() tests
# ---------------------------------------------------------------------------


class TestResolveApiKey:
    """Tests for LLMClient._resolve_api_key() provider prefix lookup."""

    @pytest.fixture(autouse=True)
    def _clear_env(self, monkeypatch: pytest.MonkeyPatch):
        """Clear all provider env vars so tests start from a clean state."""
        env_vars = {v for v in _PROVIDER_KEY_MAP.values() if v is not None}
        for var in env_vars:
            monkeypatch.delenv(var, raising=False)

    # -- OpenAI prefixes --

    def test_gpt_prefix_returns_openai_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
        assert LLMClient._resolve_api_key("gpt-4o") == "sk-openai-test"

    def test_openai_slash_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
        assert LLMClient._resolve_api_key("openai/gpt-4o-mini") == "sk-openai-test"

    def test_o1_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
        assert LLMClient._resolve_api_key("o1-preview") == "sk-openai-test"

    def test_o3_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
        assert LLMClient._resolve_api_key("o3-mini") == "sk-openai-test"

    def test_o4_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
        assert LLMClient._resolve_api_key("o4-mini") == "sk-openai-test"

    # -- Anthropic --

    def test_claude_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        assert LLMClient._resolve_api_key("claude-3-5-sonnet") == "sk-ant-test"

    def test_anthropic_slash_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        assert LLMClient._resolve_api_key("anthropic/claude-3-opus") == "sk-ant-test"

    # -- Google / Gemini --

    def test_gemini_slash_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "google-test")
        assert LLMClient._resolve_api_key("gemini/gemini-2.0-flash") == "google-test"

    def test_google_slash_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "google-test")
        assert LLMClient._resolve_api_key("google/gemini-pro") == "google-test"

    # -- xAI --

    def test_grok_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-test")
        assert LLMClient._resolve_api_key("grok-2") == "xai-test"

    def test_xai_slash_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-test")
        assert LLMClient._resolve_api_key("xai/grok-beta") == "xai-test"

    # -- OpenRouter --

    def test_openrouter_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
        assert LLMClient._resolve_api_key("openrouter/anthropic/claude-3") == "or-test"

    # -- Groq --

    def test_groq_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GROQ_API_KEY", "groq-test")
        assert LLMClient._resolve_api_key("groq/llama-3.1-70b") == "groq-test"

    # -- DeepSeek --

    def test_deepseek_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
        assert LLMClient._resolve_api_key("deepseek/deepseek-chat") == "ds-test"

    # -- Mistral --

    def test_mistral_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "mistral-test")
        assert LLMClient._resolve_api_key("mistral/mistral-large") == "mistral-test"

    # -- Cohere --

    def test_cohere_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("COHERE_API_KEY", "cohere-test")
        assert LLMClient._resolve_api_key("cohere/command-r-plus") == "cohere-test"

    def test_cohere_chat_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("COHERE_API_KEY", "cohere-test")
        assert LLMClient._resolve_api_key("cohere_chat/command-r") == "cohere-test"

    # -- Together AI --

    def test_together_ai_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("TOGETHERAI_API_KEY", "together-test")
        assert LLMClient._resolve_api_key("together_ai/meta-llama/Llama-3") == "together-test"

    # -- Perplexity --

    def test_perplexity_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PERPLEXITYAI_API_KEY", "pplx-test")
        assert LLMClient._resolve_api_key("perplexity/sonar-medium") == "pplx-test"

    # -- Fireworks AI --

    def test_fireworks_ai_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FIREWORKS_AI_API_KEY", "fw-test")
        assert LLMClient._resolve_api_key("fireworks_ai/llama-v3") == "fw-test"

    # -- Azure --

    def test_azure_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AZURE_API_KEY", "azure-test")
        assert LLMClient._resolve_api_key("azure/gpt-4") == "azure-test"

    # -- HuggingFace --

    def test_huggingface_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("HUGGINGFACE_API_KEY", "hf-test")
        assert LLMClient._resolve_api_key("huggingface/bigscience/bloom") == "hf-test"

    # -- Keyless providers --

    def test_ollama_returns_none(self):
        """Ollama is a keyless provider — should return None."""
        assert LLMClient._resolve_api_key("ollama/llama3") is None

    def test_ollama_chat_returns_none(self):
        assert LLMClient._resolve_api_key("ollama_chat/llama3") is None

    def test_hosted_vllm_returns_none(self):
        assert LLMClient._resolve_api_key("hosted_vllm/my-model") is None

    # -- Edge cases --

    def test_unknown_prefix_returns_none(self):
        """Unknown model prefix must return None, not a random key."""
        result = LLMClient._resolve_api_key("totally_unknown/model-name")
        assert result is None

    def test_case_insensitivity(self, monkeypatch: pytest.MonkeyPatch):
        """Model name lookup is case-insensitive."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
        assert LLMClient._resolve_api_key("GPT-4o") == "sk-openai-test"

    def test_case_insensitivity_anthropic(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        assert LLMClient._resolve_api_key("Claude-3.5-Sonnet") == "sk-ant-test"

    def test_case_insensitivity_gemini(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "google-test")
        assert LLMClient._resolve_api_key("Gemini/gemini-2.0-flash") == "google-test"

    def test_missing_env_var_returns_none(self, monkeypatch: pytest.MonkeyPatch):
        """When env var is not set, returns None (not an error)."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert LLMClient._resolve_api_key("gpt-4o") is None

    def test_empty_model_returns_none(self):
        """Empty model string returns None."""
        assert LLMClient._resolve_api_key("") is None

    # -- Regression tests: existing providers still work --

    @pytest.mark.parametrize(
        "model,env_var,expected_env",
        [
            ("gpt-4o", "OPENAI_API_KEY", "OPENAI_API_KEY"),
            ("claude-3-5-sonnet", "ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
            ("gemini/gemini-2.0-flash", "GOOGLE_API_KEY", "GOOGLE_API_KEY"),
            ("xai/grok-2", "XAI_API_KEY", "XAI_API_KEY"),
            ("openrouter/anthropic/claude-3", "OPENROUTER_API_KEY", "OPENROUTER_API_KEY"),
        ],
        ids=["openai", "anthropic", "google", "xai", "openrouter"],
    )
    def test_regression_core_providers(
        self, monkeypatch: pytest.MonkeyPatch, model: str, env_var: str, expected_env: str
    ):
        """Regression: core providers continue to resolve correctly."""
        monkeypatch.setenv(env_var, f"test-key-{env_var}")
        result = LLMClient._resolve_api_key(model)
        assert result == f"test-key-{env_var}"


# ---------------------------------------------------------------------------
# Task 6.2: simple_completion() tests
# ---------------------------------------------------------------------------


def _make_mock_response(content: str | None = "mocked response", reasoning: str | None = None):
    """Build a mock acompletion response with content and optional reasoning_content."""
    mock_message = MagicMock()
    mock_message.content = content
    mock_message.reasoning_content = reasoning

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


class TestSimpleCompletion:
    """Tests for LLMClient.simple_completion()."""

    @pytest.fixture(autouse=True)
    def _mock_config(self, monkeypatch: pytest.MonkeyPatch):
        """Patch _get_config and _clamp_max_tokens to avoid settings_manager dependency."""
        monkeypatch.setattr(
            LLMClient,
            "_get_config",
            lambda self: {
                "model": "gpt-4o",
                "api_key": "test-key",
                "temperature": 0.7,
                "max_tokens": 16384,
                "num_retries": 2,
                "timeout": 120,
            },
        )
        monkeypatch.setattr(
            LLMClient, "_clamp_max_tokens", lambda self, kwargs, tools=None: kwargs
        )

    async def test_returns_content_string(self, monkeypatch: pytest.MonkeyPatch):
        """Successful call returns the content string."""
        mock_acompletion = AsyncMock(return_value=_make_mock_response("Hello world"))
        monkeypatch.setattr("open_agent.core.llm.acompletion", mock_acompletion)

        client = LLMClient()
        result = await client.simple_completion(
            messages=[{"role": "user", "content": "test"}]
        )
        assert result == "Hello world"

    async def test_returns_none_on_empty_content(self, monkeypatch: pytest.MonkeyPatch):
        """Empty content with no reasoning_content returns None."""
        mock_acompletion = AsyncMock(return_value=_make_mock_response(content=""))
        monkeypatch.setattr("open_agent.core.llm.acompletion", mock_acompletion)

        client = LLMClient()
        result = await client.simple_completion(
            messages=[{"role": "user", "content": "test"}]
        )
        assert result is None

    async def test_returns_none_on_none_content(self, monkeypatch: pytest.MonkeyPatch):
        """None content with no reasoning_content returns None."""
        mock_acompletion = AsyncMock(return_value=_make_mock_response(content=None))
        monkeypatch.setattr("open_agent.core.llm.acompletion", mock_acompletion)

        client = LLMClient()
        result = await client.simple_completion(
            messages=[{"role": "user", "content": "test"}]
        )
        assert result is None

    async def test_reasoning_content_fallback(self, monkeypatch: pytest.MonkeyPatch):
        """When content is None, reasoning_content is used as fallback."""
        mock_acompletion = AsyncMock(
            return_value=_make_mock_response(content=None, reasoning="Reasoning output")
        )
        monkeypatch.setattr("open_agent.core.llm.acompletion", mock_acompletion)

        client = LLMClient()
        result = await client.simple_completion(
            messages=[{"role": "user", "content": "test"}]
        )
        assert result == "Reasoning output"

    async def test_reasoning_content_fallback_empty_string(self, monkeypatch: pytest.MonkeyPatch):
        """When content is empty string and reasoning is also empty, returns None."""
        mock_acompletion = AsyncMock(
            return_value=_make_mock_response(content="", reasoning="")
        )
        monkeypatch.setattr("open_agent.core.llm.acompletion", mock_acompletion)

        client = LLMClient()
        result = await client.simple_completion(
            messages=[{"role": "user", "content": "test"}]
        )
        assert result is None

    async def test_temperature_override(self, monkeypatch: pytest.MonkeyPatch):
        """Caller's temperature is used, not the global config value."""
        captured_kwargs = {}

        async def capture_acompletion(**kwargs):
            captured_kwargs.update(kwargs)
            return _make_mock_response("ok")

        monkeypatch.setattr("open_agent.core.llm.acompletion", capture_acompletion)

        client = LLMClient()
        await client.simple_completion(
            messages=[{"role": "user", "content": "test"}],
            temperature=0.2,
        )
        # The caller's temperature (0.2) should override the config default (0.7)
        assert captured_kwargs["temperature"] == 0.2

    async def test_max_tokens_override(self, monkeypatch: pytest.MonkeyPatch):
        """Caller's max_tokens is used, not the global config value."""
        captured_kwargs = {}

        async def capture_acompletion(**kwargs):
            captured_kwargs.update(kwargs)
            return _make_mock_response("ok")

        monkeypatch.setattr("open_agent.core.llm.acompletion", capture_acompletion)

        client = LLMClient()
        await client.simple_completion(
            messages=[{"role": "user", "content": "test"}],
            max_tokens=512,
        )
        assert captured_kwargs["max_tokens"] == 512

    async def test_default_temperature_and_max_tokens(self, monkeypatch: pytest.MonkeyPatch):
        """Default temperature=0.7 and max_tokens=4096 when not specified."""
        captured_kwargs = {}

        async def capture_acompletion(**kwargs):
            captured_kwargs.update(kwargs)
            return _make_mock_response("ok")

        monkeypatch.setattr("open_agent.core.llm.acompletion", capture_acompletion)

        client = LLMClient()
        await client.simple_completion(
            messages=[{"role": "user", "content": "test"}]
        )
        assert captured_kwargs["temperature"] == 0.7
        assert captured_kwargs["max_tokens"] == 4096


# ---------------------------------------------------------------------------
# Task 6.4: chat_stream() tool call accumulation tests
# ---------------------------------------------------------------------------


def _make_stream_chunk(
    content: str | None = None,
    tool_calls: list | None = None,
):
    """Build a single streaming chunk with delta."""
    delta = MagicMock()
    delta.content = content

    if tool_calls is not None:
        delta.tool_calls = tool_calls
    else:
        delta.tool_calls = None
        # hasattr check in chat_stream: make it return False when no tool_calls
        del delta.tool_calls

    choice = MagicMock()
    choice.delta = delta

    chunk = MagicMock()
    chunk.choices = [choice]
    return chunk


def _make_tool_call_delta(index: int, tc_id: str | None, name: str | None, args: str | None):
    """Build a tool_call delta object."""
    tc = MagicMock()
    tc.index = index
    tc.id = tc_id

    func = MagicMock()
    func.name = name
    func.arguments = args
    tc.function = func
    return tc


class TestChatStreamContentOnly:
    """Test chat_stream with content-only streaming."""

    @pytest.fixture(autouse=True)
    def _mock_config(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            LLMClient,
            "_get_config",
            lambda self: {
                "model": "gpt-4o",
                "api_key": "test-key",
                "temperature": 0.7,
                "max_tokens": 16384,
                "num_retries": 2,
                "timeout": 120,
            },
        )
        monkeypatch.setattr(
            LLMClient, "_clamp_max_tokens", lambda self, kwargs, tools=None: kwargs
        )

    async def test_content_only_stream(self, monkeypatch: pytest.MonkeyPatch):
        """Content-only streaming yields content_delta events + done event."""
        chunks = [
            _make_stream_chunk(content="Hello"),
            _make_stream_chunk(content=" world"),
        ]

        async def fake_stream(**kwargs):
            async def _gen():
                for c in chunks:
                    yield c
            return _gen()

        monkeypatch.setattr("open_agent.core.llm.acompletion", fake_stream)

        client = LLMClient()
        events = []
        async for event in client.chat_stream(
            messages=[{"role": "user", "content": "hi"}]
        ):
            events.append(event)

        assert len(events) == 3
        assert events[0] == {"type": "content_delta", "content": "Hello"}
        assert events[1] == {"type": "content_delta", "content": " world"}
        assert events[2] == {"type": "done", "content": "Hello world"}

    async def test_empty_content_stream(self, monkeypatch: pytest.MonkeyPatch):
        """Stream with no content yields done with empty string."""
        chunks = [_make_stream_chunk(content=None)]

        async def fake_stream(**kwargs):
            async def _gen():
                for c in chunks:
                    yield c
            return _gen()

        monkeypatch.setattr("open_agent.core.llm.acompletion", fake_stream)

        client = LLMClient()
        events = []
        async for event in client.chat_stream(
            messages=[{"role": "user", "content": "hi"}]
        ):
            events.append(event)

        assert len(events) == 1
        assert events[0] == {"type": "done", "content": ""}


class TestChatStreamToolCalls:
    """Test chat_stream with tool call delta accumulation."""

    @pytest.fixture(autouse=True)
    def _mock_config(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            LLMClient,
            "_get_config",
            lambda self: {
                "model": "gpt-4o",
                "api_key": "test-key",
                "temperature": 0.7,
                "max_tokens": 16384,
                "num_retries": 2,
                "timeout": 120,
            },
        )
        monkeypatch.setattr(
            LLMClient, "_clamp_max_tokens", lambda self, kwargs, tools=None: kwargs
        )

    async def test_tool_call_accumulation(self, monkeypatch: pytest.MonkeyPatch):
        """Tool call deltas are accumulated and yielded as a single tool_calls event."""
        tool_deltas_1 = [_make_tool_call_delta(0, "call_abc", "get_weather", '{"ci')]
        tool_deltas_2 = [_make_tool_call_delta(0, None, None, 'ty": "Seoul"}')]

        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta = MagicMock()
        chunk1.choices[0].delta.content = None
        chunk1.choices[0].delta.tool_calls = tool_deltas_1

        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta = MagicMock()
        chunk2.choices[0].delta.content = None
        chunk2.choices[0].delta.tool_calls = tool_deltas_2

        async def fake_stream(**kwargs):
            async def _gen():
                yield chunk1
                yield chunk2
            return _gen()

        monkeypatch.setattr("open_agent.core.llm.acompletion", fake_stream)

        tools = [{"type": "function", "function": {"name": "get_weather"}}]
        client = LLMClient()
        events = []
        async for event in client.chat_stream(
            messages=[{"role": "user", "content": "weather?"}],
            tools=tools,
        ):
            events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "tool_calls"
        assert len(events[0]["tool_calls"]) == 1
        tc = events[0]["tool_calls"][0]
        assert tc["id"] == "call_abc"
        assert tc["function"]["name"] == "get_weather"
        assert tc["function"]["arguments"] == '{"city": "Seoul"}'

    async def test_multiple_parallel_tool_calls(self, monkeypatch: pytest.MonkeyPatch):
        """Multiple parallel tool calls at different indices are accumulated correctly."""
        td_0_a = _make_tool_call_delta(0, "call_1", "search", '{"q": "a"')
        td_1_a = _make_tool_call_delta(1, "call_2", "fetch", '{"url": "b"')
        td_0_b = _make_tool_call_delta(0, None, None, "}")
        td_1_b = _make_tool_call_delta(1, None, None, "}")

        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta = MagicMock()
        chunk1.choices[0].delta.content = None
        chunk1.choices[0].delta.tool_calls = [td_0_a, td_1_a]

        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta = MagicMock()
        chunk2.choices[0].delta.content = None
        chunk2.choices[0].delta.tool_calls = [td_0_b, td_1_b]

        async def fake_stream(**kwargs):
            async def _gen():
                yield chunk1
                yield chunk2
            return _gen()

        monkeypatch.setattr("open_agent.core.llm.acompletion", fake_stream)

        tools = [
            {"type": "function", "function": {"name": "search"}},
            {"type": "function", "function": {"name": "fetch"}},
        ]
        client = LLMClient()
        events = []
        async for event in client.chat_stream(
            messages=[{"role": "user", "content": "do both"}],
            tools=tools,
        ):
            events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "tool_calls"
        calls = events[0]["tool_calls"]
        assert len(calls) == 2
        # Sorted by index — 0 first, then 1
        assert calls[0]["id"] == "call_1"
        assert calls[0]["function"]["name"] == "search"
        assert calls[0]["function"]["arguments"] == '{"q": "a"}'
        assert calls[1]["id"] == "call_2"
        assert calls[1]["function"]["name"] == "fetch"
        assert calls[1]["function"]["arguments"] == '{"url": "b"}'


class TestChatStreamFallback:
    """Test chat_stream fallback when streaming with tools fails."""

    @pytest.fixture(autouse=True)
    def _mock_config(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            LLMClient,
            "_get_config",
            lambda self: {
                "model": "gpt-4o",
                "api_key": "test-key",
                "temperature": 0.7,
                "max_tokens": 16384,
                "num_retries": 2,
                "timeout": 120,
            },
        )
        monkeypatch.setattr(
            LLMClient, "_clamp_max_tokens", lambda self, kwargs, tools=None: kwargs
        )

    async def test_fallback_to_chat_completion_tool_calls(self, monkeypatch: pytest.MonkeyPatch):
        """When streaming fails with tools, falls back to chat_completion and yields tool_calls."""
        monkeypatch.setattr(
            "open_agent.core.llm.acompletion",
            AsyncMock(side_effect=RuntimeError("stream failed")),
        )

        fallback_result = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [
                        {"id": "call_fb", "type": "function",
                         "function": {"name": "get_time", "arguments": "{}"}}
                    ],
                }
            }]
        }
        monkeypatch.setattr(
            LLMClient, "chat_completion", AsyncMock(return_value=fallback_result)
        )

        tools = [{"type": "function", "function": {"name": "get_time"}}]
        client = LLMClient()
        events = []
        async for event in client.chat_stream(
            messages=[{"role": "user", "content": "time?"}],
            tools=tools,
        ):
            events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "tool_calls"
        assert events[0]["tool_calls"][0]["function"]["name"] == "get_time"

    async def test_fallback_to_chat_completion_content(self, monkeypatch: pytest.MonkeyPatch):
        """When streaming fails with tools, falls back to content response."""
        monkeypatch.setattr(
            "open_agent.core.llm.acompletion",
            AsyncMock(side_effect=RuntimeError("stream failed")),
        )

        fallback_result = {
            "choices": [{
                "message": {
                    "content": "Fallback content",
                    "tool_calls": None,
                }
            }]
        }
        monkeypatch.setattr(
            LLMClient, "chat_completion", AsyncMock(return_value=fallback_result)
        )

        tools = [{"type": "function", "function": {"name": "dummy"}}]
        client = LLMClient()
        events = []
        async for event in client.chat_stream(
            messages=[{"role": "user", "content": "test"}],
            tools=tools,
        ):
            events.append(event)

        assert len(events) == 2
        assert events[0] == {"type": "content_delta", "content": "Fallback content"}
        assert events[1] == {"type": "done", "content": "Fallback content"}

    async def test_fallback_empty_response(self, monkeypatch: pytest.MonkeyPatch):
        """When fallback returns empty content and no tool_calls, yields done with empty."""
        monkeypatch.setattr(
            "open_agent.core.llm.acompletion",
            AsyncMock(side_effect=RuntimeError("stream failed")),
        )

        fallback_result = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": None,
                }
            }]
        }
        monkeypatch.setattr(
            LLMClient, "chat_completion", AsyncMock(return_value=fallback_result)
        )

        tools = [{"type": "function", "function": {"name": "dummy"}}]
        client = LLMClient()
        events = []
        async for event in client.chat_stream(
            messages=[{"role": "user", "content": "test"}],
            tools=tools,
        ):
            events.append(event)

        assert len(events) == 1
        assert events[0] == {"type": "done", "content": ""}

    async def test_no_fallback_without_tools(self, monkeypatch: pytest.MonkeyPatch):
        """Without tools, streaming error is raised (no fallback)."""
        monkeypatch.setattr(
            "open_agent.core.llm.acompletion",
            AsyncMock(side_effect=RuntimeError("stream failed")),
        )

        client = LLMClient()
        with pytest.raises(RuntimeError, match="stream failed"):
            async for _event in client.chat_stream(
                messages=[{"role": "user", "content": "test"}],
                tools=None,
            ):
                pass


class TestChatStreamMixedContentAndTools:
    """Test chat_stream with mixed content + tool call deltas."""

    @pytest.fixture(autouse=True)
    def _mock_config(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            LLMClient,
            "_get_config",
            lambda self: {
                "model": "gpt-4o",
                "api_key": "test-key",
                "temperature": 0.7,
                "max_tokens": 16384,
                "num_retries": 2,
                "timeout": 120,
            },
        )
        monkeypatch.setattr(
            LLMClient, "_clamp_max_tokens", lambda self, kwargs, tools=None: kwargs
        )

    async def test_content_then_tool_calls(self, monkeypatch: pytest.MonkeyPatch):
        """Some models emit content first, then tool calls in the same stream."""
        content_chunk = _make_stream_chunk(content="Let me check")

        tool_chunk = MagicMock()
        tool_chunk.choices = [MagicMock()]
        tool_chunk.choices[0].delta = MagicMock()
        tool_chunk.choices[0].delta.content = None
        tool_chunk.choices[0].delta.tool_calls = [
            _make_tool_call_delta(0, "call_mix", "search", '{"q": "test"}')
        ]

        async def fake_stream(**kwargs):
            async def _gen():
                yield content_chunk
                yield tool_chunk
            return _gen()

        monkeypatch.setattr("open_agent.core.llm.acompletion", fake_stream)

        tools = [{"type": "function", "function": {"name": "search"}}]
        client = LLMClient()
        events = []
        async for event in client.chat_stream(
            messages=[{"role": "user", "content": "test"}],
            tools=tools,
        ):
            events.append(event)

        # Should yield: content_delta for "Let me check", then tool_calls
        assert len(events) == 2
        assert events[0] == {"type": "content_delta", "content": "Let me check"}
        assert events[1]["type"] == "tool_calls"
        assert events[1]["tool_calls"][0]["function"]["name"] == "search"


# ---------------------------------------------------------------------------
# Task 6.5: REASONING_EFFORT_PROVIDERS constant tests
# ---------------------------------------------------------------------------


class TestReasoningEffortProviders:
    """Tests for the REASONING_EFFORT_PROVIDERS constant."""

    def test_is_tuple(self):
        """REASONING_EFFORT_PROVIDERS must be a tuple (immutable)."""
        assert isinstance(REASONING_EFFORT_PROVIDERS, tuple)

    def test_contains_expected_prefixes(self):
        """Must include key provider prefixes that support reasoning_effort."""
        expected = {"openai/", "anthropic/", "gemini/", "google/"}
        actual = set(REASONING_EFFORT_PROVIDERS)
        assert expected.issubset(actual)

    def test_contains_openai_reasoning_models(self):
        """Must include o1, o3, o4 model prefixes for OpenAI reasoning models."""
        for prefix in ("o1", "o3", "o4"):
            assert prefix in REASONING_EFFORT_PROVIDERS

    def test_all_elements_are_strings(self):
        for elem in REASONING_EFFORT_PROVIDERS:
            assert isinstance(elem, str)

    def test_no_self_hosted_prefixes(self):
        """Self-hosted providers must NOT be in REASONING_EFFORT_PROVIDERS."""
        for prefix in ("ollama/", "hosted_vllm/", "ollama_chat/"):
            assert prefix not in REASONING_EFFORT_PROVIDERS


# ---------------------------------------------------------------------------
# Additional: _safe_temperature tests
# ---------------------------------------------------------------------------


class TestSafeTemperature:
    """Tests for LLMClient._safe_temperature()."""

    def test_gemini3_below_1_clamped(self):
        """Gemini 3+ models should clamp temperature to 1.0 when below."""
        assert LLMClient._safe_temperature("gemini/gemini-3.0-flash", 0.5) == 1.0

    def test_gemini3_above_1_unchanged(self):
        assert LLMClient._safe_temperature("gemini/gemini-3.0-flash", 1.5) == 1.5

    def test_gemini3_exactly_1_unchanged(self):
        assert LLMClient._safe_temperature("gemini/gemini-3.0-flash", 1.0) == 1.0

    def test_non_gemini3_not_clamped(self):
        """Non-Gemini3 models should keep the requested temperature."""
        assert LLMClient._safe_temperature("gpt-4o", 0.2) == 0.2
        assert LLMClient._safe_temperature("claude-3-5-sonnet", 0.0) == 0.0
