"""Провайдер Anthropic Claude."""
from __future__ import annotations
import base64

from anthropic import AsyncAnthropic

from ai.providers.base import BaseProvider, ChatMessage, ChatResponse, ToolCall, ToolSpec

class ClaudeProvider(BaseProvider):
    name = "claude"

    def __init__(self, model: str, api_key: str | None = None, **kw):
        super().__init__(model, api_key, **kw)
        self.client = AsyncAnthropic(api_key=api_key)

    def _split(self, messages: list[ChatMessage]) -> tuple[str, list[dict]]:
        system_parts: list[str] = []
        out: list[dict] = []
        for m in messages:
            if m.role == "system":
                system_parts.append(m.content)
                continue
            role = "user" if m.role in ("user", "tool") else "assistant"
            content: list[dict] = []
            text = m.content if m.role != "tool" else f"[tool:{m.name}] {m.content}"
            content.append({"type": "text", "text": text})
            for img in (m.images or []):
                b64 = base64.b64encode(img).decode()
                content.append({"type": "image", "source": {
                    "type": "base64", "media_type": "image/jpeg", "data": b64}})
            out.append({"role": role, "content": content})
        return "\n".join(system_parts), out

    def _tools(self, tools: list[ToolSpec] | None):
        if not tools:
            return None
        return [{"name": t.name, "description": t.description,
                 "input_schema": t.parameters} for t in tools]

    async def chat(self, messages, tools=None, temperature=0.8, max_tokens=800) -> ChatResponse:
        system, msgs = self._split(messages)
        resp = await self.client.messages.create(
            model=self.model, system=system, messages=msgs,
            tools=self._tools(tools), temperature=temperature, max_tokens=max_tokens,
        )
        text_parts, tool_calls = [], []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name,
                                           arguments=block.input or {}))
        return ChatResponse(text="".join(text_parts).strip() or None,
                            tool_calls=tool_calls, raw=resp)
