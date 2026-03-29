import asyncio
import logging
import os
from typing import List, Dict, Any, AsyncGenerator, Optional
from pydantic import BaseModel
from litellm import acompletion

logger = logging.getLogger(__name__)

# LiteLLM token counting & context window lookup
try:
    from litellm import token_counter as _litellm_token_counter
except ImportError:
    _litellm_token_counter = None

try:
    from litellm import get_max_tokens as _litellm_get_max_tokens
except ImportError:
    _litellm_get_max_tokens = None

try:
    from litellm import get_model_info as _litellm_get_model_info
except ImportError:
    _litellm_get_model_info = None

_DEFAULT_CONTEXT_WINDOW = 131_072  # 128K fallback default
_MIN_OUTPUT_TOKENS = 8192  # max_tokens clamp floor: reasoning(1000+) + parallel tool_calls(300+) + content headroom

# Providers that support the reasoning_effort parameter
REASONING_EFFORT_PROVIDERS = (
    "openai/", "anthropic/", "gemini/", "google/", "o1", "o3", "o4",
)

# Provider prefix → environment variable name (None = keyless provider)
_PROVIDER_KEY_MAP: Dict[str, str | None] = {
    "gpt-": "OPENAI_API_KEY",
    "openai/": "OPENAI_API_KEY",
    "o1-": "OPENAI_API_KEY",
    "o3-": "OPENAI_API_KEY",
    "o4-": "OPENAI_API_KEY",
    "claude-": "ANTHROPIC_API_KEY",
    "anthropic/": "ANTHROPIC_API_KEY",
    "grok-": "XAI_API_KEY",
    "xai/": "XAI_API_KEY",
    "openrouter/": "OPENROUTER_API_KEY",
    "gemini/": "GOOGLE_API_KEY",
    "google/": "GOOGLE_API_KEY",
    "groq/": "GROQ_API_KEY",
    "deepseek/": "DEEPSEEK_API_KEY",
    "mistral/": "MISTRAL_API_KEY",
    "cohere/": "COHERE_API_KEY",
    "cohere_chat/": "COHERE_API_KEY",
    "together_ai/": "TOGETHERAI_API_KEY",
    "perplexity/": "PERPLEXITYAI_API_KEY",
    "fireworks_ai/": "FIREWORKS_AI_API_KEY",
    "azure/": "AZURE_API_KEY",
    "huggingface/": "HUGGINGFACE_API_KEY",
    "hosted_vllm/": None,
    "ollama/": None,
    "ollama_chat/": None,
}

# Retry configuration (inspired by ATLAS Ralph Loop)
_MAX_LLM_RETRIES = 3
_BASE_RETRY_DELAY = 1.0  # seconds
_TEMP_INCREMENT = 0.05   # temperature increase per retry

# Errors that should NOT be retried (immediate failure)
_UNRECOVERABLE_ERRORS = (
    "invalid_api_key", "authentication_error", "AuthenticationError",
    "model_not_found", "NotFoundError",
    "context_length_exceeded", "ContextWindowExceededError",
    "content_policy_violation", "ContentPolicyViolationError",
)


class Message(BaseModel):
    role: str
    content: str


class LLMClient:
    def _get_config(self) -> Dict[str, Any]:
        """Dynamically read current settings from settings_manager."""
        from open_agent.core.settings_manager import settings_manager

        llm = settings_manager.llm
        api_key = llm.api_key or self._resolve_api_key(llm.model)
        timeout = getattr(llm, "timeout", 120)

        config: Dict[str, Any] = {
            "model": llm.model,
            "api_key": api_key,
            "temperature": self._safe_temperature(llm.model, llm.temperature),
            "max_tokens": llm.max_tokens,
            "num_retries": 2,
            "timeout": timeout,
        }
        if llm.api_base:
            config["api_base"] = llm.api_base
        # reasoning_effort: low/medium/high — only for supported providers
        # Self-hosted models (vLLM/Ollama) don't support it — passing it causes hangs/errors
        if hasattr(llm, "reasoning_effort") and llm.reasoning_effort:
            model_lower = llm.model.lower()
            if any(model_lower.startswith(p) for p in REASONING_EFFORT_PROVIDERS):
                config["reasoning_effort"] = llm.reasoning_effort
        return config

    @staticmethod
    def _is_unrecoverable(exc: Exception) -> bool:
        """Check if an exception is unrecoverable and should not be retried."""
        exc_str = str(exc)
        exc_type = type(exc).__name__
        return any(
            err in exc_str or err in exc_type
            for err in _UNRECOVERABLE_ERRORS
        )

    @staticmethod
    def _resolve_api_key(model: str) -> str | None:
        """Auto-select API key from env vars based on model provider prefix."""
        model_lower = model.lower()
        for prefix, env_var in _PROVIDER_KEY_MAP.items():
            if model_lower.startswith(prefix):
                if env_var is None:
                    return None
                return os.getenv(env_var)
        return None

    def get_system_prompt(self) -> str:
        from open_agent.core.settings_manager import settings_manager
        return settings_manager.llm.system_prompt

    # -- Context window & token management ------------------------------------

    def get_context_window(self) -> int:
        """Return the context window size (tokens) for the current model.

        Priority: user setting > LiteLLM auto-detect > default (128K)
        """
        from open_agent.core.settings_manager import settings_manager
        llm = settings_manager.llm

        # 1. User-configured value
        if llm.context_window > 0:
            return llm.context_window

        # 2. LiteLLM auto-detect via get_model_info
        #    (get_max_tokens returns max output tokens, not context window)
        if _litellm_get_model_info:
            try:
                info = _litellm_get_model_info(llm.model)
                # max_tokens is output limit — use max_input_tokens for context window
                ctx = info.get("max_input_tokens", 0)
                if ctx and ctx > 0:
                    return ctx
            except Exception as exc:
                logger.debug("Model info lookup failed", exc_info=exc)

        # 3. Fallback
        return _DEFAULT_CONTEXT_WINDOW

    def count_tokens(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]] | None = None,
    ) -> int:
        """Estimate token count for a message list.

        Tries LiteLLM token_counter first, falls back to char-based estimation (~4 chars/token).
        """
        from open_agent.core.settings_manager import settings_manager
        model = settings_manager.llm.model

        if _litellm_token_counter:
            try:
                # LiteLLM native: pass tools param directly (no manual estimation needed)
                count = _litellm_token_counter(model=model, messages=messages, tools=tools)
                return count
            except Exception as exc:
                logger.debug("Token counter with tools failed", exc_info=exc)
            # tools param not supported — count messages only + manual tool estimation
            try:
                count = _litellm_token_counter(model=model, messages=messages)
                if tools:
                    import json
                    count += len(json.dumps(tools, ensure_ascii=False)) // 3
                return count
            except Exception as e:
                logger.debug(
                    "LiteLLM token_counter failed, falling back to char estimation: %s", e,
                )

        # Fallback: CJK-safe estimation (Korean ~1.0 char/token, English ~4 chars/token → //2)
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        total_chars += len(part.get("text", ""))
        if tools:
            import json
            total_chars += len(json.dumps(tools, ensure_ascii=False)) // 3 * 2
        return max(total_chars // 2, 1)

    # -- Lightweight classification call --------------------------------------

    @staticmethod
    def _extract_choice(text: str, choices: List[str]) -> Optional[str]:
        """Extract a choice from LLM response. Exact match first, substring fallback."""
        cleaned = text.strip().lower()
        # 1st pass: entire response matches a choice exactly
        for choice in choices:
            if cleaned == choice.lower():
                return choice
        # 2nd pass: first line or first word matches
        first_line = cleaned.split("\n")[0].strip()
        first_word = first_line.split()[0] if first_line.split() else ""
        for choice in choices:
            cl = choice.lower()
            if first_line == cl or first_word == cl:
                return choice
        # 3rd pass: substring match (last resort, longest choice first to avoid partial matches)
        for choice in sorted(choices, key=len, reverse=True):
            if choice.lower() in cleaned:
                return choice
        return None

    @staticmethod
    def _safe_temperature(model: str, requested: float) -> float:
        """Gemini 3+ models degrade at temperature < 1.0 — return safe value."""
        if "gemini-3" in model.lower() and requested < 1.0:
            return 1.0
        return requested

    async def classify(
        self,
        prompt: str,
        choices: List[str],
        user_message: str,
    ) -> Optional[str]:
        """Lightweight LLM call for classification. Returns one of choices or None."""
        config = self._get_config()
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_message},
        ]
        try:
            temp = self._safe_temperature(config["model"], 0.0)
            kwargs = {
                "model": config["model"],
                "api_key": config["api_key"],
                "messages": messages,
                "temperature": temp,
                "max_tokens": 256,
                "num_retries": config.get("num_retries", 2),
                "timeout": config.get("timeout", 120),
            }
            # Classification uses low reasoning — only for supported providers
            model_lower = config["model"].lower()
            if any(model_lower.startswith(p) for p in REASONING_EFFORT_PROVIDERS):
                kwargs["reasoning_effort"] = "low"
            if config.get("api_base"):
                kwargs["api_base"] = config["api_base"]
            response = await acompletion(**kwargs)
            msg = response.choices[0].message
            # Reasoning models may put content in reasoning_content instead of content
            raw = msg.content
            if not raw:
                reasoning = getattr(msg, "reasoning_content", None) or ""
                if reasoning:
                    return self._extract_choice(reasoning, choices)
                return None
            return self._extract_choice(raw, choices)
        except Exception as e:
            logger.warning("classify() failed: %s", e)
            return None

    # -- Dynamic max_tokens clamping ------------------------------------------

    def _clamp_max_tokens(
        self, kwargs: Dict[str, Any], tools: list | None = None,
    ) -> Dict[str, Any]:
        """Dynamically adjust max_tokens based on context_window - input_tokens."""
        context_window = self.get_context_window()
        input_tokens = self.count_tokens(kwargs["messages"], tools)
        margin = 256
        available = context_window - input_tokens - margin
        configured = kwargs.get("max_tokens", 16384)

        if available < _MIN_OUTPUT_TOKENS:
            logger.warning(
                "Context nearly full: %d/%d tokens used, only %d available (clamping to %d)",
                input_tokens, context_window, max(available, 0), _MIN_OUTPUT_TOKENS,
            )
            kwargs["max_tokens"] = _MIN_OUTPUT_TOKENS
        elif available < configured:
            logger.info("Clamping max_tokens: %d -> %d", configured, available)
            kwargs["max_tokens"] = available
        return kwargs

    # -- LLM calls ------------------------------------------------------------

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]] = None,
        tool_choice: str | Dict[str, Any] | None = None,
        reasoning_effort: str | None = None,
    ) -> Dict[str, Any]:
        config = self._get_config()
        kwargs = {
            **config,
            "messages": messages,
        }
        # Dynamic reasoning_effort override — only for supported providers
        if reasoning_effort:
            model_lower = kwargs.get("model", "").lower()
            if any(model_lower.startswith(p) for p in REASONING_EFFORT_PROVIDERS):
                kwargs["reasoning_effort"] = reasoning_effort
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"
            # Parallel tool_calls: only enable when model actually supports it
            # gpt-oss models always generate only 1 — disable to prevent empty responses
            model_lower = kwargs.get("model", "").lower()
            if "gpt-oss" not in model_lower:
                kwargs["parallel_tool_calls"] = True

        self._clamp_max_tokens(kwargs, tools)

        base_temp = kwargs.get("temperature", 0.7)
        last_exc: Exception | None = None

        for attempt in range(_MAX_LLM_RETRIES):
            try:
                if attempt > 0:
                    kwargs["temperature"] = min(
                        base_temp + attempt * _TEMP_INCREMENT, 1.5
                    )
                response = await acompletion(**kwargs)
                result = response.model_dump()

                # reasoning model compat: use reasoning_content when
                # content/tool_calls are both empty
                try:
                    msg = result.get("choices", [{}])[0].get("message", {})
                    if not msg.get("content") and not msg.get("tool_calls"):
                        reasoning = getattr(
                            response.choices[0].message,
                            "reasoning_content",
                            None,
                        )
                        if reasoning:
                            if not tools:
                                msg["content"] = reasoning
                            else:
                                msg["_reasoning_content"] = reasoning
                                logger.debug(
                                    "Reasoning model returned empty with tools, "
                                    "reasoning_content preserved as hint (%d chars)",
                                    len(reasoning),
                                )
                except (IndexError, AttributeError):
                    pass

                return result
            except Exception as exc:
                if self._is_unrecoverable(exc):
                    raise
                last_exc = exc
                delay = _BASE_RETRY_DELAY * (2 ** attempt)
                logger.warning(
                    "LLM chat_completion failed (attempt %d/%d), "
                    "retrying in %.1fs: %s",
                    attempt + 1, _MAX_LLM_RETRIES, delay, exc,
                )
                await asyncio.sleep(delay)

        raise RuntimeError(
            f"LLM chat_completion failed after {_MAX_LLM_RETRIES} retries"
        ) from last_exc

    async def simple_completion(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str | None:
        """Simple non-tool LLM call that returns the content string directly.

        Handles reasoning_content fallback like chat_completion.
        Returns None if the response content is empty.
        """
        config = self._get_config()
        kwargs = {
            **config,
            "messages": messages,
        }
        kwargs["temperature"] = self._safe_temperature(kwargs["model"], temperature)
        kwargs["max_tokens"] = max_tokens
        self._clamp_max_tokens(kwargs)
        response = await acompletion(**kwargs)
        msg = response.choices[0].message

        content = msg.content
        if not content:
            # Reasoning models may return content via reasoning_content
            content = getattr(msg, "reasoning_content", None) or ""
        return content if content else None

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]] | None = None,
        tool_choice: str | Dict[str, Any] | None = None,
        parallel_tool_calls: bool = True,
        reasoning_effort: str | None = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream LLM response, yielding typed event dicts.

        Events:
          {"type": "content_delta", "content": "chunk"}  — text chunk
          {"type": "tool_calls", "tool_calls": [...]}     — accumulated tool calls
          {"type": "done", "content": "full text"}        — stream complete (text only)
        """
        config = self._get_config()
        kwargs = {
            **config,
            "messages": messages,
            "stream": True,
        }

        # Apply reasoning_effort override for supported providers
        if reasoning_effort:
            model_lower = kwargs.get("model", "").lower()
            if any(model_lower.startswith(p) for p in REASONING_EFFORT_PROVIDERS):
                kwargs["reasoning_effort"] = reasoning_effort

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"
            model_lower = kwargs.get("model", "").lower()
            if "gpt-oss" not in model_lower and parallel_tool_calls:
                kwargs["parallel_tool_calls"] = True

        self._clamp_max_tokens(kwargs, tools)

        # Retry on initial stream connection (inspired by ATLAS Ralph Loop)
        base_temp = kwargs.get("temperature", 0.7)
        last_exc: Exception | None = None

        try:
            for attempt in range(_MAX_LLM_RETRIES):
                try:
                    if attempt > 0:
                        kwargs["temperature"] = min(
                            base_temp + attempt * _TEMP_INCREMENT, 1.5
                        )
                    response = await acompletion(**kwargs)
                    break
                except Exception as exc:
                    if self._is_unrecoverable(exc):
                        raise
                    last_exc = exc
                    delay = _BASE_RETRY_DELAY * (2 ** attempt)
                    logger.warning(
                        "LLM chat_stream connection failed (attempt %d/%d), "
                        "retrying in %.1fs: %s",
                        attempt + 1, _MAX_LLM_RETRIES, delay, exc,
                    )
                    await asyncio.sleep(delay)
            else:
                raise RuntimeError(
                    f"LLM chat_stream failed after {_MAX_LLM_RETRIES} retries"
                ) from last_exc

            full_content = ""
            # Accumulate tool call deltas by index
            tool_call_acc: Dict[int, Dict[str, Any]] = {}

            async for chunk in response:
                delta = chunk.choices[0].delta

                # Text content delta
                if delta.content:
                    full_content += delta.content
                    yield {"type": "content_delta", "content": delta.content}

                # Tool call deltas
                if hasattr(delta, "tool_calls") and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_call_acc:
                            tool_call_acc[idx] = {
                                "id": getattr(tc_delta, "id", None) or "",
                                "type": "function",
                                "function": {
                                    "name": "",
                                    "arguments": "",
                                },
                            }
                        acc = tool_call_acc[idx]
                        if getattr(tc_delta, "id", None):
                            acc["id"] = tc_delta.id
                        if hasattr(tc_delta, "function") and tc_delta.function:
                            if getattr(tc_delta.function, "name", None):
                                acc["function"]["name"] = tc_delta.function.name
                            if getattr(tc_delta.function, "arguments", None):
                                acc["function"]["arguments"] += (
                                    tc_delta.function.arguments
                                )

            # Yield accumulated tool calls if any
            if tool_call_acc:
                sorted_calls = [
                    tool_call_acc[i] for i in sorted(tool_call_acc.keys())
                ]
                yield {"type": "tool_calls", "tool_calls": sorted_calls}
            else:
                yield {"type": "done", "content": full_content}

        except Exception as e:
            if not tools:
                raise
            # Fallback: streaming with tools failed — use non-streaming chat_completion
            logger.warning(
                "Streaming with tools failed, falling back to chat_completion: %s", e,
            )
            result = await self.chat_completion(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                reasoning_effort=reasoning_effort,
            )
            msg = result.get("choices", [{}])[0].get("message", {})
            if msg.get("tool_calls"):
                yield {"type": "tool_calls", "tool_calls": msg["tool_calls"]}
            elif msg.get("content"):
                yield {"type": "content_delta", "content": msg["content"]}
                yield {"type": "done", "content": msg["content"]}
            else:
                yield {"type": "done", "content": ""}


llm_client = LLMClient()
