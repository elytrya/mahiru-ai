"""Базовый класс инструмента для LLM и общий интерфейс."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any

from ai.providers.base import ToolSpec

class Tool(ABC):
    name: str
    description: str
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description,
                        parameters=self.parameters)

    @abstractmethod
    async def run(self, args: dict[str, Any], *, session, user_id: int) -> Any: ...
