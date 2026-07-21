"""Провайдер Google Gemini."""
from __future__ import annotations
import asyncio
from typing import Any

import google.generativeai as genai

from ai.providers.base import BaseProvider, ChatMessage, ChatResponse, ToolCall, ToolSpec

_ALLOWED_SCHEMA_KEYS = {
    "type", "format", "description", "nullable", "enum",
    "items", "properties", "required",
}

def _sanitize_schema(schema: Any) -> Any:
    if isinstance(schema, list):
        return [_sanitize_schema(x) for x in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for k, v in schema.items():
        if k not in _ALLOWED_SCHEMA_KEYS:
            continue
        if k == "properties" and isinstance(v, dict):
            out[k] = {pk: _sanitize_schema(pv) for pk, pv in v.items()}
        elif k == "items":
            out[k] = _sanitize_schema(v)
        else:
            out[k] = v
    return out

class GeminiProvider(BaseProvider):
    name = "gemini"

    def __init__(self, model: str, api_key: str | None = None, **kwargs):
        super().__init__(model, api_key, **kwargs)
        if api_key:
            genai.configure(api_key=api_key)

    def _convert(self, messages: list[ChatMessage]) -> tuple[str, list[dict]]:
        system = ""
        history: list[dict] = []
        for m in messages:
            if m.role == "system":
                system += (m.content + "\n")
            elif m.role == "user":
                parts: list[dict] = [{"text": m.content}]
                for img in (m.images or []):
                    parts.append({"inline_data": {"mime_type": "image/jpeg", "data": img}})
                history.append({"role": "user", "parts": parts})
            elif m.role == "assistant":
                history.append({"role": "model", "parts": [{"text": m.content}]})
            elif m.role == "tool":
                history.append({"role": "user", "parts":
                                [{"text": f"[tool:{m.name}] {m.content}"}]})
        return system, history

    def _tools(self, tools: list[ToolSpec] | None):
        if not tools:
            return None
        return [{
            "function_declarations": [
                {
                    "name": t.name,
                    "description": t.description,
                    "parameters": _sanitize_schema(t.parameters or {"type": "object", "properties": {}}),
                }
                for t in tools
            ]
        }]

    async def chat(self, messages, tools=None, temperature=0.8, max_tokens=800) -> ChatResponse:
        system, history = self._convert(messages)
        model = genai.GenerativeModel(
            model_name=self.model,
            system_instruction=system or None,
            tools=self._tools(tools),
            generation_config={"temperature": temperature, "max_output_tokens": max_tokens},
        )

        def _run():
            return model.generate_content(history)

        resp = await asyncio.to_thread(_run)

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        try:
            for cand in resp.candidates or []:
                for part in cand.content.parts:
                    if getattr(part, "function_call", None):
                        fc = part.function_call
                        args = dict(fc.args) if fc.args else {}
                        tool_calls.append(ToolCall(id=fc.name, name=fc.name, arguments=args))
                    elif getattr(part, "text", None):
                        text_parts.append(part.text)
        except Exception:
            pass

        text = "".join(text_parts).strip() or None
        return ChatResponse(text=text, tool_calls=tool_calls, raw=resp)
