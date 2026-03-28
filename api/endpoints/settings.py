import asyncio
import json
import logging
import os
import time
import urllib.request

from fastapi import APIRouter
from litellm import acompletion

from open_agent import __version__
from open_agent.core.settings_manager import settings_manager
from open_agent.core.llm import LLMClient
from open_agent.models.memory import MemorySettings
from pydantic import BaseModel as PydanticBaseModel

from open_agent.models.settings import CustomModel, LLMSettings, ProfileSettings, ThemeSettings, UpdateLLMRequest, UpdateMemorySettingsRequest, UpdateProfileRequest, UpdateThemeRequest

logger = logging.getLogger(__name__)
router = APIRouter()

# --- Provider Model Discovery Cache ---
_model_cache: dict[str, tuple[float, list[dict]]] = {}  # provider → (timestamp, models)
_MODEL_CACHE_TTL = 300.0  # 5분


def _fetch_version_sync() -> dict:
    """동기 HTTP 호출 — asyncio.to_thread()에서 실행."""
    current = __version__
    latest = None

    gh_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if gh_token:
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/EJCHO-salary/track_platform/releases?per_page=20",
                headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {gh_token}"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                releases = json.loads(resp.read().decode())
                for rel in releases:
                    tag = rel.get("tag_name", "")
                    if tag.startswith("v") and not tag.startswith(("desktop-v", "mac-desktop-v")):
                        latest = tag.lstrip("v")
                        break
        except Exception:
            pass

    if not latest:
        try:
            req = urllib.request.Request(
                "https://pypi.org/pypi/open-agent-platform/json",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                latest = data.get("info", {}).get("version")
        except Exception:
            pass

    update_available = False
    if latest:
        try:
            cur = tuple(int(x) for x in current.split("."))
            lat = tuple(int(x) for x in latest.split("."))
            update_available = lat > cur
        except (ValueError, TypeError):
            update_available = latest != current

    return {"current": current, "latest": latest, "update_available": update_available}


@router.get("/version")
async def get_version():
    """현재 설치 버전과 GitHub Releases 최신 버전 비교 (폴백: PyPI)"""
    return await asyncio.to_thread(_fetch_version_sync)


@router.get("/health")
async def health_check():
    """백엔드 서버 상태 + 실제 LLM 연결 테스트"""
    llm = settings_manager.llm
    api_key = llm.api_key or LLMClient._resolve_api_key(llm.model)

    result = {
        "server": "ok",
        "llm_connected": False,
        "model": llm.model,
        "error": None,
    }

    if not api_key and not llm.api_base:
        result["error"] = "API 키가 설정되지 않았습니다"
        return result

    try:
        kwargs = {
            "model": llm.model,
            "api_key": api_key,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "timeout": 8,
            "num_retries": 0,
        }
        if llm.api_base:
            kwargs["api_base"] = llm.api_base

        await acompletion(**kwargs)
        result["llm_connected"] = True
    except Exception as e:
        error_msg = str(e)
        # 너무 긴 에러 메시지 자르기
        if len(error_msg) > 200:
            error_msg = error_msg[:200] + "..."
        result["error"] = error_msg
        logger.warning(f"LLM connection test failed: {error_msg}")

    return result


@router.get("/llm", response_model=LLMSettings)
async def get_llm_settings():
    # api_key를 응답에서 마스킹
    llm = settings_manager.llm.model_copy()
    if llm.api_key:
        llm.api_key = llm.api_key[:4] + "***" + llm.api_key[-4:]
    return llm


@router.patch("/llm", response_model=LLMSettings)
async def update_llm_settings(req: UpdateLLMRequest):
    updated = settings_manager.update_llm(**req.model_dump(exclude_unset=True))
    # api_key를 응답에서 마스킹
    result = updated.model_copy()
    if result.api_key:
        result.api_key = result.api_key[:4] + "***" + result.api_key[-4:]
    return result


@router.get("/memory", response_model=MemorySettings)
async def get_memory_settings():
    return settings_manager.memory


@router.patch("/memory", response_model=MemorySettings)
async def update_memory_settings(req: UpdateMemorySettingsRequest):
    return settings_manager.update_memory(**req.model_dump(exclude_unset=True))


@router.get("/profile", response_model=ProfileSettings)
async def get_profile():
    return settings_manager.profile


@router.patch("/profile", response_model=ProfileSettings)
async def update_profile(req: UpdateProfileRequest):
    return settings_manager.update_profile(**req.model_dump(exclude_unset=True))


@router.get("/theme", response_model=ThemeSettings)
async def get_theme():
    return settings_manager.theme


@router.patch("/theme", response_model=ThemeSettings)
async def update_theme(req: UpdateThemeRequest):
    return settings_manager.update_theme(**req.model_dump(exclude_unset=True))


# --- Validate Model ---

class ValidateModelRequest(PydanticBaseModel):
    model: str
    api_base: str | None = None
    api_key: str | None = None


@router.post("/validate-model")
async def validate_model(req: ValidateModelRequest):
    """LiteLLM으로 모델 호출 가능 여부 검증"""
    api_key = req.api_key or LLMClient._resolve_api_key(req.model)

    try:
        kwargs = {
            "model": req.model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "timeout": 10,
            "num_retries": 0,
        }
        if api_key:
            kwargs["api_key"] = api_key
        if req.api_base:
            kwargs["api_base"] = req.api_base

        await acompletion(**kwargs)
        return {"valid": True, "model": req.model}
    except Exception as e:
        error_msg = str(e)
        if len(error_msg) > 300:
            error_msg = error_msg[:300] + "..."
        return {"valid": False, "model": req.model, "error": error_msg}


# --- Custom Models CRUD ---

@router.get("/custom-models", response_model=list[CustomModel])
async def get_custom_models():
    return settings_manager.custom_models


class AddCustomModelRequest(PydanticBaseModel):
    label: str
    model: str
    provider: str


@router.post("/custom-models", response_model=list[CustomModel])
async def add_custom_model(req: AddCustomModelRequest):
    return settings_manager.add_custom_model(req.label, req.model, req.provider)


@router.delete("/custom-models", response_model=list[CustomModel])
async def remove_custom_model(model: str):
    return settings_manager.remove_custom_model(model)


# --- Dynamic Model Discovery ---

# Provider API endpoints for listing models
_PROVIDER_APIS = {
    "openai": {
        "url": "https://api.openai.com/v1/models",
        "env_key": "OPENAI_API_KEY",
        "prefix": "openai/",
        "label_prefix": "",
    },
    "google": {
        "url": "https://generativelanguage.googleapis.com/v1beta/models",
        "env_key": "GOOGLE_API_KEY",
        "prefix": "gemini/",
        "label_prefix": "",
        "is_google": True,
    },
    "anthropic": {
        "url": "https://api.anthropic.com/v1/models",
        "env_key": "ANTHROPIC_API_KEY",
        "prefix": "anthropic/",
        "label_prefix": "",
    },
    "xai": {
        "url": "https://api.x.ai/v1/models",
        "env_key": "XAI_API_KEY",
        "prefix": "xai/",
        "label_prefix": "",
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/models",
        "env_key": "OPENROUTER_API_KEY",
        "prefix": "openrouter/",
        "label_prefix": "",
    },
}


def _fetch_openai_compatible(url: str, api_key: str, prefix: str) -> list[dict]:
    """Fetch models from OpenAI-compatible /v1/models endpoint."""
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    models = []
    for m in data.get("data", []):
        model_id = m.get("id", "")
        if not model_id:
            continue
        models.append({
            "id": f"{prefix}{model_id}",
            "name": model_id,
            "created": m.get("created"),
        })
    models.sort(key=lambda x: x.get("created") or 0, reverse=True)
    return models


def _fetch_google_models(api_key: str) -> list[dict]:
    """Fetch models from Google Generative AI API."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    models = []
    for m in data.get("models", []):
        name = m.get("name", "")  # e.g., "models/gemini-2.0-flash"
        display = m.get("displayName", name)
        model_id = name.replace("models/", "")
        if not model_id:
            continue
        # generateContent 지원 모델만
        methods = m.get("supportedGenerationMethods", [])
        if "generateContent" not in methods:
            continue
        models.append({
            "id": f"gemini/{model_id}",
            "name": display,
        })
    return models


def _fetch_anthropic_models(api_key: str) -> list[dict]:
    """Fetch models from Anthropic API."""
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/models",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    models = []
    for m in data.get("data", []):
        model_id = m.get("id", "")
        display = m.get("display_name", model_id)
        if not model_id:
            continue
        models.append({
            "id": f"anthropic/{model_id}",
            "name": display,
            "created": m.get("created_at"),
        })
    return models


def _discover_provider(provider: str) -> list[dict]:
    """Discover models for a single provider."""
    config = _PROVIDER_APIS.get(provider)
    if not config:
        return []

    api_key = os.getenv(config["env_key"])
    if not api_key:
        return []

    # Cache check
    now = time.monotonic()
    if provider in _model_cache:
        cached_at, cached = _model_cache[provider]
        if (now - cached_at) < _MODEL_CACHE_TTL:
            return cached

    try:
        if provider == "google":
            models = _fetch_google_models(api_key)
        elif provider == "anthropic":
            models = _fetch_anthropic_models(api_key)
        else:
            models = _fetch_openai_compatible(
                config["url"], api_key, config["prefix"]
            )

        _model_cache[provider] = (now, models)
        logger.info("Discovered %d models from %s", len(models), provider)
        return models
    except Exception as e:
        logger.warning("Model discovery failed for %s: %s", provider, e)
        # Return stale cache if available
        if provider in _model_cache:
            return _model_cache[provider][1]
        return []


@router.get("/models/discover")
async def discover_models(provider: str | None = None):
    """API 키가 설정된 프로바이더에서 사용 가능한 모델 목록을 동적으로 조회합니다.

    - provider 지정 시 해당 프로바이더만, 생략 시 전체 조회
    - 5분 TTL 캐시 적용
    """
    if provider:
        models = await asyncio.to_thread(_discover_provider, provider)
        return {"providers": {provider: models}}

    # 전체 프로바이더 병렬 조회
    providers = list(_PROVIDER_APIS.keys())
    results = await asyncio.gather(
        *(asyncio.to_thread(_discover_provider, p) for p in providers)
    )
    return {
        "providers": {p: models for p, models in zip(providers, results) if models}
    }
