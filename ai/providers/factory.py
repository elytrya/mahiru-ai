from __future__ import annotations
from typing import Type

from config import settings
from ai.providers.base import BaseProvider
from ai.providers.gemini import GeminiProvider
from ai.providers.openai import OpenAIProvider
from ai.providers.claude import ClaudeProvider
from ai.providers.deepseek import DeepSeekProvider
from ai.providers.ollama import OllamaProvider
from ai.providers.g4f_provider import G4FProvider
from ai.providers.yandex import YandexProvider

REGISTRY: dict[str, Type[BaseProvider]] = {
    "gemini":   GeminiProvider,
    "openai":   OpenAIProvider,
    "claude":   ClaudeProvider,
    "deepseek": DeepSeekProvider,
    "ollama":   OllamaProvider,
    "g4f":      G4FProvider,
    "yandex":   YandexProvider,
}

def build_provider(name: str | None = None) -> BaseProvider:
    name = (name or settings.DEFAULT_PROVIDER).lower()
    cls = REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown provider: {name}")

    if name == "gemini":
        return cls(settings.GEMINI_MODEL, api_key=settings.GEMINI_API_KEY)
    if name == "openai":
        return cls(settings.OPENAI_MODEL, api_key=settings.OPENAI_API_KEY)
    if name == "claude":
        return cls(settings.CLAUDE_MODEL, api_key=settings.ANTHROPIC_API_KEY)
    if name == "deepseek":
        return cls(settings.DEEPSEEK_MODEL, api_key=settings.DEEPSEEK_API_KEY)
    if name == "ollama":
        return cls(settings.OLLAMA_MODEL, host=settings.OLLAMA_HOST)
    if name == "g4f":
        return cls(settings.G4F_MODEL, g4f_provider=settings.G4F_PROVIDER or None)
    if name == "yandex":
        return cls(
            settings.YANDEX_MODEL,
            api_key=settings.YANDEX_API_KEY,
            folder=settings.YANDEX_FOLDER,
            prompt_id=settings.YANDEX_PROMPT_ID,
        )
    raise ValueError(name)
