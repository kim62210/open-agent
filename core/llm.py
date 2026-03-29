import logging
import os
from typing import List, Dict, Any, AsyncGenerator, Optional
from pydantic import BaseModel
from litellm import acompletion

logger = logging.getLogger(__name__)

# LiteLLM 토큰 카운팅 & 컨텍스트 윈도우 조회
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

_DEFAULT_CONTEXT_WINDOW = 131_072  # 128K 폴백 기본값
_MIN_OUTPUT_TOKENS = 8192  # max_tokens 클램핑 최소값: reasoning 사고(1000+) + 병렬 tool_calls(300+) + content 여유


class Message(BaseModel):
    role: str
    content: str


class LLMClient:
    def _get_config(self) -> Dict[str, Any]:
        """settings_manager에서 현재 설정을 동적으로 읽음"""
        from open_agent.core.settings_manager import settings_manager

        llm = settings_manager.llm
        api_key = llm.api_key or self._resolve_api_key(llm.model)

        config: Dict[str, Any] = {
            "model": llm.model,
            "api_key": api_key,
            "temperature": self._safe_temperature(llm.model, llm.temperature),
            "max_tokens": llm.max_tokens,
        }
        if llm.api_base:
            config["api_base"] = llm.api_base
        # reasoning_effort: low/medium/high — 지원 프로바이더만 적용
        # vLLM/Ollama 등 셀프호스팅 모델은 미지원 → 전달하면 행/에러
        if hasattr(llm, "reasoning_effort") and llm.reasoning_effort:
            model_lower = llm.model.lower()
            _REASONING_EFFORT_PROVIDERS = ("openai/", "anthropic/", "gemini/", "google/", "o1", "o3", "o4")
            if any(model_lower.startswith(p) for p in _REASONING_EFFORT_PROVIDERS):
                config["reasoning_effort"] = llm.reasoning_effort
        return config

    @staticmethod
    def _resolve_api_key(model: str) -> str | None:
        """모델 프로바이더에 따라 환경변수에서 API 키 자동 선택"""
        model_lower = model.lower()
        if model_lower.startswith(("gpt-", "openai/", "o1-", "o3-", "o4-")):
            return os.getenv("OPENAI_API_KEY")
        elif model_lower.startswith(("claude-", "anthropic/")):
            return os.getenv("ANTHROPIC_API_KEY")
        elif model_lower.startswith(("grok-", "xai/")):
            return os.getenv("XAI_API_KEY")
        elif model_lower.startswith("openrouter/"):
            return os.getenv("OPENROUTER_API_KEY")
        elif model_lower.startswith(("gemini/", "google/")):
            return os.getenv("GOOGLE_API_KEY")
        # hosted_vllm, ollama 등은 키 불필요할 수 있음
        return os.getenv("GOOGLE_API_KEY") or os.getenv("OPENAI_API_KEY")

    def get_system_prompt(self) -> str:
        from open_agent.core.settings_manager import settings_manager
        return settings_manager.llm.system_prompt

    # ── 컨텍스트 윈도우 & 토큰 관리 ─────────────────────────────────

    def get_context_window(self) -> int:
        """현재 모델의 컨텍스트 윈도우 크기(토큰)를 반환합니다.

        우선순위: 사용자 설정값 > LiteLLM 자동 감지 > 기본값(128K)
        """
        from open_agent.core.settings_manager import settings_manager
        llm = settings_manager.llm

        # 1. 사용자가 직접 설정한 값
        if llm.context_window > 0:
            return llm.context_window

        # 2. LiteLLM 자동 감지 — get_model_info로 컨텍스트 윈도우 조회
        #    (get_max_tokens는 최대 출력 토큰을 반환하므로 사용 불가)
        if _litellm_get_model_info:
            try:
                info = _litellm_get_model_info(llm.model)
                # max_tokens는 출력 한도이므로 컨텍스트 윈도우로 사용하지 않음
                ctx = info.get("max_input_tokens", 0)
                if ctx and ctx > 0:
                    return ctx
            except Exception as exc:
                logger.debug("API key resolution failed", exc_info=exc)

        # 3. 폴백
        return _DEFAULT_CONTEXT_WINDOW

    def count_tokens(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]] | None = None) -> int:
        """메시지 목록의 토큰 수를 추정합니다.

        LiteLLM token_counter 사용 시도 → 실패 시 문자수 기반 추정(~4 chars/token)
        """
        from open_agent.core.settings_manager import settings_manager
        model = settings_manager.llm.model

        if _litellm_token_counter:
            try:
                # LiteLLM 네이티브: tools 파라미터 직접 전달 (수동 추정 불필요)
                count = _litellm_token_counter(model=model, messages=messages, tools=tools)
                return count
            except Exception as exc:
                logger.debug("API key resolution failed", exc_info=exc)
            # tools 파라미터 미지원 시 messages만 카운트 + 수동 도구 추정
            try:
                count = _litellm_token_counter(model=model, messages=messages)
                if tools:
                    import json
                    count += len(json.dumps(tools, ensure_ascii=False)) // 3
                return count
            except Exception as e:
                logger.debug("LiteLLM token_counter failed, falling back to char estimation: %s", e)

        # 폴백: CJK 안전 범용 추정 (한글 ~1.0 char/token, 영문 ~4 chars/token → 절충 //2)
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
            total_chars += len(json.dumps(tools, ensure_ascii=False)) // 3 * 2  # 도구 스키마는 주로 ASCII
        return max(total_chars // 2, 1)

    # ── 경량 분류 호출 ─────────────────────────────────────────────

    @staticmethod
    def _extract_choice(text: str, choices: List[str]) -> Optional[str]:
        """LLM 응답에서 choice를 추출. exact match 우선, fallback으로 substring."""
        cleaned = text.strip().lower()
        # 1차: 응답 전체가 choice와 정확히 일치
        for choice in choices:
            if cleaned == choice.lower():
                return choice
        # 2차: 첫 줄(또는 첫 단어)이 choice와 일치
        first_line = cleaned.split("\n")[0].strip()
        first_word = first_line.split()[0] if first_line.split() else ""
        for choice in choices:
            cl = choice.lower()
            if first_line == cl or first_word == cl:
                return choice
        # 3차: substring 매칭 (최후 수단, 가장 긴 choice부터 매칭하여 부분 매칭 방지)
        for choice in sorted(choices, key=len, reverse=True):
            if choice.lower() in cleaned:
                return choice
        return None

    @staticmethod
    def _safe_temperature(model: str, requested: float) -> float:
        """Gemini 3+ 모델은 temperature < 1.0에서 성능 저하 — 안전값 반환."""
        if "gemini-3" in model.lower() and requested < 1.0:
            return 1.0
        return requested

    async def classify(
        self,
        prompt: str,
        choices: List[str],
        user_message: str,
    ) -> Optional[str]:
        """경량 LLM 호출로 분류. choices 중 하나 또는 None 반환."""
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
            }
            # 분류는 경량 추론 — 지원 프로바이더만
            model_lower = config["model"].lower()
            _RE_PROVIDERS = ("openai/", "anthropic/", "gemini/", "google/", "o1", "o3", "o4")
            if any(model_lower.startswith(p) for p in _RE_PROVIDERS):
                kwargs["reasoning_effort"] = "low"
            if config.get("api_base"):
                kwargs["api_base"] = config["api_base"]
            response = await acompletion(**kwargs)
            msg = response.choices[0].message
            # reasoning 모델은 content가 None이고 reasoning_content에 사고 과정이 들어감
            raw = msg.content
            if not raw:
                # reasoning_content에서 답변 추출 시도
                reasoning = getattr(msg, "reasoning_content", None) or ""
                if reasoning:
                    return self._extract_choice(reasoning, choices)
                return None
            return self._extract_choice(raw, choices)
        except Exception as e:
            logger.warning("classify() failed: %s", e)
            return None

    # ── 동적 max_tokens 클램핑 ──────────────────────────────────────

    def _clamp_max_tokens(self, kwargs: Dict[str, Any], tools: list | None = None) -> Dict[str, Any]:
        """context_window - input_tokens 기반으로 max_tokens를 동적 조정합니다."""
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
            logger.info("Clamping max_tokens: %d → %d", configured, available)
            kwargs["max_tokens"] = available
        return kwargs

    # ── LLM 호출 ──────────────────────────────────────────────────

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
        # 동적 reasoning_effort 오버라이드 — 지원 프로바이더만
        if reasoning_effort:
            model_lower = kwargs.get("model", "").lower()
            _REASONING_EFFORT_PROVIDERS = ("openai/", "anthropic/", "gemini/", "google/", "o1", "o3", "o4")
            if any(model_lower.startswith(p) for p in _REASONING_EFFORT_PROVIDERS):
                kwargs["reasoning_effort"] = reasoning_effort
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"
            # 병렬 tool_calls: 모델이 실제로 병렬 생성을 지원하는 경우만 활성화
            # gpt-oss 모델은 항상 1개만 생성하므로 비활성화 (빈 응답 유발 방지)
            model_lower = kwargs.get("model", "").lower()
            if "gpt-oss" not in model_lower:
                kwargs["parallel_tool_calls"] = True

        self._clamp_max_tokens(kwargs, tools)
        response = await acompletion(**kwargs)
        result = response.model_dump()

        # reasoning 모델 호환: content/tool_calls 모두 빈 경우 reasoning_content 활용
        try:
            msg = result.get("choices", [{}])[0].get("message", {})
            if not msg.get("content") and not msg.get("tool_calls"):
                reasoning = getattr(response.choices[0].message, "reasoning_content", None)
                if reasoning:
                    if not tools:
                        # tools 없는 순수 대화: reasoning을 content로 직접 사용
                        msg["content"] = reasoning
                    else:
                        # tools 있는 호출: reasoning을 힌트로 전달 (agent 재시도 로직이 활용)
                        msg["_reasoning_content"] = reasoning
                        logger.debug("Reasoning model returned empty with tools, reasoning_content preserved as hint (%d chars)", len(reasoning))
        except (IndexError, AttributeError):
            pass

        return result

    async def chat_stream(self, messages: List[Dict[str, Any]]) -> AsyncGenerator[str, None]:
        config = self._get_config()
        kwargs = {
            **config,
            "messages": messages,
            "stream": True,
        }

        self._clamp_max_tokens(kwargs)
        response = await acompletion(**kwargs)
        async for chunk in response:
            content = chunk.choices[0].delta.content
            if content:
                yield content


llm_client = LLMClient()
