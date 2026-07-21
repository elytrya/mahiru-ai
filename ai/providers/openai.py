"""Провайдер OpenAI и совместимых API."""
from __future__ import annotations
import base64
import json

from openai import AsyncOpenAI

from ai.providers.base import BaseProvider, ChatMessage, ChatResponse, ToolCall, ToolSpec

class OpenAIProvider(BaseProvider):
    name = "openai"

    def __init__(self, model: str, api_key: str | None = None,
                 base_url: str | None = None, **kw):
        super().__init__(model, api_key, **kw)
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    def _msgs(self, messages: list[ChatMessage]):
        out = []
        for m in messages:
            if m.role == "tool":
                out.append({"role": "tool", "content": m.content,
                            "tool_call_id": m.tool_call_id or m.name or "tool"})
            elif m.images:
                content = [{"type": "text", "text": m.content}]
                for img in m.images:
                    b64 = base64.b64encode(img).decode()
                    content.append({"type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
                out.append({"role": m.role, "content": content})
            else:
                out.append({"role": m.role, "content": m.content})
        return out

    def _tools(self, tools: list[ToolSpec] | None):
        if not tools:
            return None
        return [{"type": "function",
                 "function": {"name": t.name, "description": t.description,
                              "parameters": t.parameters}} for t in tools]

    async def chat(self, messages, tools=None, temperature=0.8, max_tokens=800) -> ChatResponse:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=self._msgs(messages),
            tools=self._tools(tools),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        msg = resp.choices[0].message
        tool_calls: list[ToolCall] = []
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        return ChatResponse(text=msg.content, tool_calls=tool_calls, raw=resp)

class DeepSeekProvider(OpenAIProvider):
    name = "deepseek"

    def __init__(self, model: str, api_key: str | None = None, **kw):
        super().__init__(model, api_key=api_key,
                         base_url="https://api.deepseek.com", **kw)
