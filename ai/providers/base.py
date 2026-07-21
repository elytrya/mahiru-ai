"""Базовые типы и абстрактный класс провайдера LLM (сообщения, ответы, вызовы инструментов)."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]

@dataclass
class ChatMessage:
    role: Role
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    images: list[bytes] | None = None

@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

@dataclass
class ChatResponse:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None

class BaseProvider(ABC):
    name: str = "base"

    def __init__(self, model: str, api_key: str | None = None, **kwargs):
        self.model = model
        self.api_key = api_key
        self.kwargs = kwargs

    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.8,
        max_tokens: int = 800,
    ) -> ChatResponse: ...

    async def close(self) -> None:
        pass
