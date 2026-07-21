"""Провайдер локальных моделей через Ollama."""
from __future__ import annotations
import json
import re
import httpx

from ai.providers.base import BaseProvider, ChatMessage, ChatResponse, ToolCall, ToolSpec
from ai.providers import ollama_bootstrap

_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)
_FENCED_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _coerce_toolcalls(d) -> list[ToolCall]:
    """Привести разные JSON-формы tool-вызова к списку ToolCall."""
    out: list[ToolCall] = []
    if not isinstance(d, dict):
        return out
    if isinstance(d.get("tool_calls"), list):
        for item in d["tool_calls"]:
            out.extend(_coerce_toolcalls(item))
        return out
    fn = d.get("function")
    if isinstance(fn, dict):
        name = fn.get("name")
        args = fn.get("arguments") or fn.get("parameters") or {}
    else:
        name = d.get("name")
        args = d.get("arguments") or d.get("parameters") or {}
    if not name:
        return out
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}
    if not isinstance(args, dict):
        args = {}
    out.append(ToolCall(id=str(name), name=str(name), arguments=args))
    return out


def _extract_toolcalls_from_text(text: str):
    """Мелкие модели (llama3.1 и др.) часто пишут tool-call JSON'ом прямо в content.
    Вытаскиваем его в настоящие tool_calls и вырезаем из текста."""
    if not text or "{" not in text:
        return [], text
    t = text.strip()
    candidates = list(_FENCED_RE.findall(t))
    m = _JSON_OBJ_RE.search(t)
    if m:
        candidates.append(m.group(0))
    for cand in candidates:
        try:
            d = json.loads(cand)
        except Exception:
            continue
        calls = _coerce_toolcalls(d)
        if calls:
            cleaned = t.replace(cand, "").strip()
            return calls, (cleaned or None)
    return [], text


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

        await ollama_bootstrap.ensure_ollama_ready(self.host, self.model)
        data = await self._post_chat(payload)

        return self._parse(data)

    async def _post_chat(self, payload: dict):
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(f"{self.host}/api/chat", json=payload)
            if r.status_code == 404:
                ollama_bootstrap.invalidate(self.host, self.model)
                await ollama_bootstrap.ensure_ollama_ready(self.host, self.model)
                r = await c.post(f"{self.host}/api/chat", json=payload)
            r.raise_for_status()
            return r.json()

    def _parse(self, data) -> ChatResponse:
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
        if not tool_calls and text:
            extracted, text = _extract_toolcalls_from_text(text)
            tool_calls.extend(extracted)
        return ChatResponse(text=text, tool_calls=tool_calls, raw=data)
