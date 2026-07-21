"""Провайдер YandexGPT через OpenAI-совместимый эндпоинт."""
from __future__ import annotations
import base64
import json
from typing import Any

from openai import AsyncOpenAI

from ai.providers.base import BaseProvider, ChatMessage, ChatResponse, ToolCall, ToolSpec
from utils.logger import log

YANDEX_BASE_URL = "https://ai.api.cloud.yandex.net/v1"

_MODEL_ALIASES = {
    "yandexgpt-lite": "yandexgpt-lite/latest",
    "yandexgpt":      "yandexgpt/latest",
    "yandexgpt-pro":  "yandexgpt/latest",
    "llama-8b":       "llama-lite/latest",
    "llama-70b":      "llama/latest",
}

class YandexProvider(BaseProvider):
    name = "yandex"

    def __init__(self, model: str, api_key: str | None = None,
                 folder: str | None = None, prompt_id: str | None = None, **kw):
        super().__init__(model, api_key, **kw)
        self.folder = (folder or "").strip() or None
        self.prompt_id = (prompt_id or "").strip() or None

        client_kwargs: dict[str, Any] = {
            "api_key": api_key or "",
            "base_url": YANDEX_BASE_URL,
            "default_headers": {
                **({"x-folder-id": self.folder} if self.folder else {}),
            },
        }
        if self.folder:
            try:
                self.client = AsyncOpenAI(project=self.folder, **client_kwargs)
            except TypeError:
                self.client = AsyncOpenAI(**client_kwargs)
        else:
            self.client = AsyncOpenAI(**client_kwargs)

    def _full_model(self) -> str:
        m = (self.model or "yandexgpt-lite").strip()
        if m.startswith("gpt://"):
            return m
        tail = _MODEL_ALIASES.get(m, m if "/" in m else f"{m}/latest")
        if not self.folder:
            raise RuntimeError(
                "Yandex: не задан YANDEX_FOLDER (folder id, начинается с b1g...). "
                "Задай через /setkey YANDEX_FOLDER <folder-id> или в .env."
            )
        return f"gpt://{self.folder}/{tail}"

    def _msgs(self, messages: list[ChatMessage]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            if m.role == "tool":
                out.append({"role": "tool", "content": m.content,
                            "tool_call_id": m.tool_call_id or m.name or "tool"})
            elif m.images:
                content: list[dict] = [{"type": "text", "text": m.content}]
                for img in m.images:
                    b64 = base64.b64encode(img).decode()
                    content.append({"type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
                out.append({"role": m.role, "content": content})
            else:
                out.append({"role": m.role, "content": m.content or ""})
        return out

    def _tools(self, tools: list[ToolSpec] | None):
        if not tools:
            return None
        return [{"type": "function",
                 "function": {"name": t.name, "description": t.description,
                              "parameters": t.parameters}} for t in tools]

    async def chat(self, messages, tools=None, temperature=0.8,
                   max_tokens=800) -> ChatResponse:
        if self.prompt_id:
            return await self._responses_call(messages, temperature, max_tokens)

        model = self._full_model()
        payload: dict[str, Any] = {
            "model": model,
            "messages": self._msgs(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        tool_specs = self._tools(tools)
        if tool_specs:
            payload["tools"] = tool_specs

        try:
            resp = await self.client.chat.completions.create(**payload)
        except TypeError:
            payload.pop("tools", None)
            resp = await self.client.chat.completions.create(**payload)

        msg = resp.choices[0].message
        tool_calls: list[ToolCall] = []
        for tc in (getattr(msg, "tool_calls", None) or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            tool_calls.append(ToolCall(id=getattr(tc, "id", tc.function.name),
                                       name=tc.function.name, arguments=args))
        return ChatResponse(text=getattr(msg, "content", "") or "",
                            tool_calls=tool_calls, raw=resp)

    async def _responses_call(self, messages, temperature: float,
                              max_tokens: int) -> ChatResponse:
        history: list[dict] = []
        for m in messages:
            if m.role == "system":
                continue
            if m.role not in ("user", "assistant"):
                continue
            history.append({"role": m.role, "content": m.content or ""})

        if not history:
            for m in reversed(messages):
                if m.role == "user":
                    history = [{"role": "user", "content": m.content or ""}]
                    break

        kw = {
            "prompt": {"id": self.prompt_id},
            "input": history if history else "",
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        try:
            resp = await self.client.responses.create(**kw)
        except TypeError:
            kw["input"] = "\n\n".join(f"{h['role']}: {h['content']}" for h in history)
            kw.pop("max_output_tokens", None)
            resp = await self.client.responses.create(**kw)
        except AttributeError as e:
            raise RuntimeError(
                "Yandex Responses API недоступен в твоей версии openai-sdk. "
                "pip install -U openai (>=1.55)"
            ) from e

        text = getattr(resp, "output_text", None) or ""
        if not text:
            parts: list[str] = []
            for item in (getattr(resp, "output", None) or []):
                for c in (getattr(item, "content", None) or []):
                    t = getattr(c, "text", None)
                    if isinstance(t, str):
                        parts.append(t)
                    elif t is not None and hasattr(t, "value"):
                        parts.append(t.value)
            text = "".join(parts)
        return ChatResponse(text=text or "", tool_calls=[], raw=resp)
