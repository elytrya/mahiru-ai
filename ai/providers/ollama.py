from __future__ import annotations
import json
import httpx

from ai.providers.base import BaseProvider, ChatMessage, ChatResponse, ToolCall, ToolSpec

class OllamaProvider(BaseProvider):
    name = "ollama"

    def __init__(self, model: str, host: str = "http://localhost:11434", **kw):
        super().__init__(model, api_key=None, **kw)
        self.host = host.rstrip("/")

    def _msgs(self, messages: list[ChatMessage]):
        return [{"role": m.role if m.role != "tool" else "user",
                 "content": m.content if m.role != "tool" else f"[tool:{m.name}] {m.content}"}
                for m in messages]

    async def chat(self, messages, tools=None, temperature=0.8, max_tokens=800) -> ChatResponse:
        payload = {
            "model": self.model,
            "messages": self._msgs(messages),
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if tools:
            payload["tools"] = [{"type": "function",
                                 "function": {"name": t.name, "description": t.description,
                                              "parameters": t.parameters}} for t in tools]
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(f"{self.host}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()

        msg = data.get("message", {}) or {}
        text = msg.get("content") or None
        tool_calls: list[ToolCall] = []
        for tc in msg.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            tool_calls.append(ToolCall(id=fn.get("name", "tool"),
                                       name=fn.get("name", "tool"),
                                       arguments=args))
        return ChatResponse(text=text, tool_calls=tool_calls, raw=data)
