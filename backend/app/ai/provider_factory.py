"""Provider factory — selects and returns the active AI provider."""
from __future__ import annotations

from app.ai.base import AIProvider
from app.core.config import get_settings

_settings = get_settings()
_provider_cache: AIProvider | None = None


def get_provider() -> AIProvider:
    """Return the configured AI provider instance."""
    global _provider_cache
    if _provider_cache is not None:
        return _provider_cache

    name = _settings.llm_provider

    if name == "gemini":
        from app.ai.gemini_provider import GeminiProvider
        _provider_cache = GeminiProvider()
    elif name == "groq":
        from app.ai.groq_provider import GroqProvider
        _provider_cache = GroqProvider()
    elif name == "openrouter":
        from app.ai.openrouter_provider import OpenRouterProvider
        _provider_cache = OpenRouterProvider()
    elif name == "openai_compatible":
        from app.ai.openai_compatible_provider import OpenAICompatibleProvider
        _provider_cache = OpenAICompatibleProvider()
    elif name == "ollama":
        from app.ai.ollama_provider import OllamaProvider
        _provider_cache = OllamaProvider()
    else:
        from app.ai.demo_provider import DemoProvider
        _provider_cache = DemoProvider()

    return _provider_cache


def reset_provider_cache() -> None:
    """Force re-creation of provider (for testing)."""
    global _provider_cache
    _provider_cache = None
