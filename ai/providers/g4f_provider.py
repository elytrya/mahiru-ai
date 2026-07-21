"""Провайдер на базе g4f (бесплатный доступ к моделям)."""
from __future__ import annotations
import asyncio
import base64
import json
import re
from typing import Any

from ai.providers.base import BaseProvider, ChatMessage, ChatResponse, ToolCall, ToolSpec
from utils.logger import log

_NEEDS_AUTH = {
    "OpenaiChat", "PuterJS", "ApiAirforce", "OpenRouter", "CopilotAccount",
    "Gemini", "HuggingFace", "HuggingFaceAPI", "HuggingSpace",
    "MetaAI", "MetaAIAccount", "Poe", "BingCreateImages", "Cerebras",
    "GithubCopilot", "Groq", "MicrosoftDesigner", "nGPT", "Reka",
    "Replicate", "ReplicateHome", "DeepInfraChat",
}

_FREE_CANDIDATES = [
    "PollinationsAI", "Blackbox", "DDG", "Free2GPT", "ChatGptEs",
    "LiaobotsFree", "Pizzagpt", "AiChatOnline", "ChatGpt",
    "FreeChatgpt", "Chatgpt4Online", "OIVSCode", "TypeGPT", "Airforce",
    "Yqcloud",
]

_KEYABLE_PROVIDERS = _NEEDS_AUTH | {"HuggingChat", "Airforce", "ApiAirforce", "WeWordle"}

_MODEL_FALLBACKS = [
    "deepseek-v3", "deepseek-r1", "deepseek-chat",
    "gpt-4o-mini",
    "qwen-2.5-72b", "qwen-2.5-32b", "qwen-2.5-14b", "qwen-2.5-7b",
    "qwen-2-72b", "qwen-2-7b", "qwen-turbo", "qwen-plus", "qwen",
    "llama-3.3-70b", "llama-3.1-405b", "llama-3.1-70b", "llama-3.1-8b",
    "llama-3-70b", "llama-3-8b",
    "deepseek-coder",
    "gemma-2-27b", "gemma-2-9b", "gemma-3-27b",
    "mistral-large", "mistral-nemo", "mistral-7b", "mixtral-8x7b",
    "claude-3-5-sonnet", "claude-3-haiku", "claude-3-opus",
    "command-r-plus", "command-r",
    "phi-4", "phi-3.5",
    "grok-2", "sonar",
    "gpt-4o", "gpt-4", "gpt-4-turbo", "gpt-3.5-turbo",
    "openai", "openai-fast", "openai-large",
    "default", "",
]

_MODEL_ERROR_HINTS = ("model not found", "model_not_found", "modelnotfound",
                      "invalid model", "unknown model", "unknown_model",
                      "not supported", "model is not available",
                      "model not available", "unsupported model",
                      "model does not exist", "no such model", "no model",
                      "model not exist", "model unavailable", "is not a valid model",
                      "модель не найден", "модель недоступн")

_LENGTH_ERROR_HINTS = ("过长", "too long", "context length", "maximum context",
                       "token limit", "context_length", "length_exceeded",
                       "413", "payload too large", "maximum length",
                       "exceeds the model", "too many tokens")

_HARD_ERROR_HINTS = ("no .har", "missingrequirementserror", "curl_cffi",
                     "access to cloud provider blocked", "providernotworking",
                     "is not working", "cloudflare challenge",
                     "429", "too many requests", "rate limit", "quota",
                     "forbidden", "403")

_AUTH_REQUIRED_HINTS = ("api key is required", 'add a "api_key"', "api_key",
                        "missingauth", "authenticationrequired",
                        "unauthorized", "401 ", " 401",
                        "please sign in", "please log in", "login required",
                        "registration required", "no valid har")

_AUTH_HINT_URL = {
    "OpenaiChat":    "chat.openai.com → скачай .har-файл, .env: HAR_FILE=...",
    "PuterJS":       "puter.com → зарегайся и возьми токен",
    "HuggingChat":   "huggingface.co/chat → нужны cookies",
    "Cerebras":      "cloud.cerebras.ai → API key",
    "Groq":          "console.groq.com → API key",
    "OpenRouter":    "openrouter.ai → API key",
    "DeepInfraChat": "deepinfra.com → API key",
    "CopilotAccount":"github.com/features/copilot → cookies",
    "GithubCopilot": "github.com/features/copilot → token",
    "MetaAIAccount": "meta.ai → cookies",
    "Poe":           "poe.com → cookies",
    "Gemini":        "aistudio.google.com → API key",
    "HuggingFace":   "huggingface.co/settings/tokens → API token",
    "HuggingFaceAPI":"huggingface.co/settings/tokens → API token",
    "Reka":          "platform.reka.ai → API key",
    "Replicate":     "replicate.com → API token",
    "nGPT":          "nano-gpt.com → API key",
}

_MAX_LENGTH_FAILS_PER_PROVIDER = 2

_PER_ATTEMPT_TIMEOUT = 15.0
_OVERALL_DEADLINE    = 75.0
_RACE_WIDTH          = 4
_RACE_TIMEOUT        = 18.0
_SHRINK_TARGET_CHARS = 6000

_ERROR_CONTENT_MARKERS = (
    "the model does not exist",
    "discord.gg/airforce",
    "discord.gg",
    "no valid har",
    "missingauth",
    "missing auth",
    "rate limit",
    "rate-limit",
    "too many requests",
    "invalid api key",
    "incorrect api key",
    "api key is invalid",
    "api key is required",
    "<!doctype html",
    "<html",
    "insufficient_quota",
    "you exceeded your current quota",
    "internal server error",
    "502 bad gateway",
    "503 service",
    "model_not_found",
    "model not found",
    "unauthorized",
    "access denied",
    "service temporarily unavailable",
    "service unavailable",
    "usage limit",
    "upgrade to",
)

def _resp_text_and_tools(resp) -> tuple[str, bool]:
    try:
        msg = resp.choices[0].message
    except Exception:
        return "", False
    text = getattr(msg, "content", None) or ""
    has_tools = bool(getattr(msg, "tool_calls", None))
    return text, has_tools

def _looks_like_error_content(text: str) -> bool:
    low = (text or "").strip().lower()
    if not low:
        return False
    if len(low) > 600:
        return False
    return any(m in low for m in _ERROR_CONTENT_MARKERS)

def _is_bad_response(resp) -> bool:
    """True — если ответ бесполезен: пустой без тулов или текст-ошибка провайдера."""
    text, has_tools = _resp_text_and_tools(resp)
    if has_tools:
        return False
    if not (text or "").strip():
        return True
    return _looks_like_error_content(text)

def _resolve(name: str):
    try:
        import g4f.Provider as gp
    except Exception:
        return None
    return getattr(gp, name, None)

def _msg_len(m: dict) -> int:
    c = m.get("content", "")
    if isinstance(c, str):
        return len(c)
    if isinstance(c, list):
        return sum(len(x.get("text", "")) if isinstance(x, dict) else 0 for x in c)
    return 0

def _shrink_messages(msgs: list[dict], target: int) -> list[dict]:
    if not msgs:
        return msgs
    system = msgs[0] if msgs[0].get("role") == "system" else None
    body = msgs[1:] if system else msgs[:]
    if not body:
        return msgs

    tail = body[-1]
    prev = body[:-1]

    budget = max(target - _msg_len(tail) - (_msg_len(system) if system else 0), 500)
    kept: list[dict] = []
    total = 0
    for m in reversed(prev):
        length = _msg_len(m)
        if length > 1500:
            new_m = dict(m)
            content = m.get("content", "")
            if isinstance(content, str):
                new_m["content"] = content[:1500] + " ...[обрезано]"
            m = new_m
            length = _msg_len(m)
        if total + length > budget and kept:
            break
        kept.insert(0, m)
        total += length

    result: list[dict] = []
    if system:
        result.append(system)
    result.extend(kept)
    result.append(tail)
    return result

_FENCE_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)

def _iter_toplevel_json_objects(text: str):
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    yield start, i + 1, text[start:i + 1]
                    start = -1

def _try_parse_tool_json(blob: str) -> list[ToolCall]:
    try:
        data = json.loads(blob)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    out: list[ToolCall] = []
    if isinstance(data.get("tool_calls"), list):
        for i, call in enumerate(data["tool_calls"]):
            if not isinstance(call, dict):
                continue
            name = call.get("name") or (call.get("function") or {}).get("name")
            args = call.get("arguments") or (call.get("function") or {}).get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {"_raw": args}
            if not name:
                continue
            out.append(ToolCall(id=call.get("id") or f"{name}-{i}",
                                name=name, arguments=args or {}))
        return out
    if "name" in data and "arguments" in data:
        args = data["arguments"]
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {"_raw": args}
        out.append(ToolCall(id=data.get("id") or str(data["name"]),
                            name=str(data["name"]), arguments=args or {}))
    return out

def _extract_inline_tool_calls(text: str) -> tuple[str, list[ToolCall]]:
    if not text or ("tool_call" not in text.lower()):
        return text, []
    tool_calls: list[ToolCall] = []
    spans: list[tuple[int, int]] = []
    for m in _FENCE_JSON_RE.finditer(text):
        parsed = _try_parse_tool_json(m.group(1))
        if parsed:
            tool_calls.extend(parsed)
            spans.append((m.start(), m.end()))
    for start, end, blob in _iter_toplevel_json_objects(text):
        if any(s <= start < e for s, e in spans):
            continue
        parsed = _try_parse_tool_json(blob)
        if parsed:
            tool_calls.extend(parsed)
            spans.append((start, end))
    if not tool_calls:
        return text, []
    spans.sort()
    parts = []
    last = 0
    for s, e in spans:
        parts.append(text[last:s])
        last = e
    parts.append(text[last:])
    cleaned = re.sub(r"\n{3,}", "\n\n", "".join(parts).strip())
    return cleaned, tool_calls

class G4FProvider(BaseProvider):
    name = "g4f"

    def __init__(self, model: str, api_key: str | None = None,
                 g4f_provider: str | None = None, **kw):
        super().__init__(model, api_key, **kw)
        self.forced_provider_name = (g4f_provider or "").strip() or None
        if self.forced_provider_name and self.forced_provider_name.lower() == "auto":
            self.forced_provider_name = None

        self._last_ok: tuple[str, str] | None = None
        self._dead_pairs: set[tuple[str, str]] = set()
        self._dead_providers: set[str] = set()
        self._shrunk_pairs: set[tuple[str, str]] = set()
        self._auth_needed: dict[str, str] = {}
        self._authed_providers: set[str] = set()
        self._authed_loaded: bool = False

        try:
            from g4f.client import AsyncClient
        except ImportError as e:
            raise ImportError("Пакет g4f не установлен. pip install -U g4f") from e

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
                out.append({"role": m.role, "content": m.content})
        return out

    def _tools(self, tools: list[ToolSpec] | None):
        if not tools:
            return None
        return [{"type": "function", "function":
                 {"name": t.name, "description": t.description,
                  "parameters": t.parameters}} for t in tools]

    def _provider_plan(self) -> list[tuple[str, Any]]:
        plan: list[tuple[str, Any]] = []
        seen: set[str] = set()

        def _add(name: str | None):
            if not name or name in seen:
                return
            if name == "auto":
                plan.append(("auto", None))
                seen.add("auto")
                return
            if name in _NEEDS_AUTH and name not in self._authed_providers:
                return
            if name in self._dead_providers:
                return
            obj = _resolve(name)
            if obj is None:
                return
            plan.append((name, obj))
            seen.add(name)

        if self._last_ok:
            _add(self._last_ok[0])
        _add(self.forced_provider_name)
        for n in sorted(self._authed_providers):
            _add(n)
        for n in _FREE_CANDIDATES:
            _add(n)
        if "auto" not in seen:
            plan.append(("auto", None))
        return plan

    async def _ensure_authed_loaded(self) -> None:
        if self._authed_loaded:
            return
        self._authed_loaded = True
        try:
            from utils.settings_kv import get_key as _gk
        except Exception:
            return
        authed: set[str] = set()
        for name in _KEYABLE_PROVIDERS:
            try:
                if await _gk(f"G4F_KEY_{name.upper()}"):
                    authed.add(name)
            except Exception:
                pass
        self._authed_providers = authed
        if authed:
            log.info(f"🔑 g4f: есть пользовательские ключи для {', '.join(sorted(authed))}")

    def reset_provider_auth(self, name: str | None = None) -> None:
        """Сбросить 'dead'-пометки после того как юзер ввёл ключ, чтобы g4f снова попробовал провайдера."""
        self._authed_loaded = False
        self._last_ok = None
        if name:
            self._dead_providers.discard(name)
            self._auth_needed.pop(name, None)
            self._dead_pairs = {p for p in self._dead_pairs if p[0] != name}
        else:
            self._dead_providers.clear()
            self._auth_needed.clear()
            self._dead_pairs.clear()

    def _model_plan(self) -> list[str]:
        wanted = self.model
        ordered: list[str] = []
        if self._last_ok and self._last_ok[1]:
            ordered.append(self._last_ok[1])
        if wanted:
            ordered.append(wanted)
        for m in _MODEL_FALLBACKS:
            ordered.append(m)
        return list(dict.fromkeys(ordered))

    async def _race_first(self, provider_plan, model_plan, payload_common, base_messages):
        model = (model_plan[0] if model_plan else self.model) or ""
        cands: list[tuple[str, Any]] = []
        for prov_name, prov_obj in provider_plan:
            if prov_name in self._dead_providers:
                continue
            if (prov_name, model or "default") in self._dead_pairs:
                continue
            cands.append((prov_name, prov_obj))
            if len(cands) >= _RACE_WIDTH:
                break
        if not cands:
            return None

        async def _try(pname: str, pobj):
            payload = dict(payload_common)
            payload["messages"] = base_messages
            resp = await self._one_call(pobj, model, payload)
            if resp is None:
                raise RuntimeError("empty resp")
            if _is_bad_response(resp):
                self._dead_pairs.add((pname, model or "default"))
                raise RuntimeError("bad content")
            return pname, resp

        tasks = {asyncio.create_task(_try(n, o)): n for n, o in cands}
        log.info(f"⚡ g4f: параллельный забег {len(tasks)} провайдеров "
                 f"[{', '.join(tasks.values())}] на модели {model or 'default'}")
        winner: tuple[str, Any] | None = None
        loop = asyncio.get_event_loop()
        deadline = loop.time() + _RACE_TIMEOUT
        pending = set(tasks.keys())
        try:
            while pending:
                timeout = deadline - loop.time()
                if timeout <= 0:
                    break
                done, pending = await asyncio.wait(
                    pending, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    break
                for t in done:
                    nm = tasks[t]
                    try:
                        pname, resp = t.result()
                    except Exception as e:
                        log.debug(f"⚡ забег: {nm} мимо — {type(e).__name__}: {str(e)[:80]}")
                        continue
                    winner = (pname, resp)
                    break
                if winner:
                    break
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
        if winner:
            pname, resp = winner
            self._last_ok = (pname, model)
            log.info(f"✅ g4f: забег выиграл {pname} / {model or 'default'} — ok")
            return self._pack(resp)
        log.info("⚡ g4f: забег никого не выявил, иду по одному")
        return None

    async def _one_call(self, provider_obj, model: str, payload: dict):
        from g4f.client import AsyncClient
        client = AsyncClient(provider=provider_obj) if provider_obj else AsyncClient()
        p = dict(payload)
        if model:
            p["model"] = model
        else:
            p.pop("model", None)

        try:
            if provider_obj is not None and "api_key" not in p:
                prov_name = getattr(provider_obj, "__name__", "") or str(provider_obj)
                if prov_name and prov_name != "auto":
                    from utils.settings_kv import get_key as _get_g4f_user_key
                    _uk = await _get_g4f_user_key(f"G4F_KEY_{prov_name.upper()}")
                    if _uk:
                        p["api_key"] = _uk
        except Exception:
            pass

        async def _do():
            try:
                return await client.chat.completions.create(**p)
            except TypeError:
                p2 = {k: v for k, v in p.items() if k not in ("tools",)}
                try:
                    return await client.chat.completions.create(**p2)
                except TypeError:
                    p3 = {k: v for k, v in p2.items() if k not in ("api_key",)}
                    return await client.chat.completions.create(**p3)

        return await asyncio.wait_for(_do(), timeout=_PER_ATTEMPT_TIMEOUT)

    async def chat(self, messages, tools=None, temperature=0.8,
                   max_tokens=800) -> ChatResponse:
        await self._ensure_authed_loaded()
        base_messages = self._msgs(messages)
        payload_common: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        tool_specs = self._tools(tools)
        if tool_specs:
            payload_common["tools"] = tool_specs

        provider_plan = self._provider_plan()
        model_plan = self._model_plan()

        errors: list[str] = []

        try:
            raced = await self._race_first(provider_plan, model_plan,
                                           payload_common, base_messages)
        except Exception as e:
            log.debug(f"g4f: забег упал целиком — {e}")
            raced = None
        if raced is not None:
            return raced

        _t0 = asyncio.get_event_loop().time()

        current_target = None

        for prov_name, prov_obj in provider_plan:
            if asyncio.get_event_loop().time() - _t0 > _OVERALL_DEADLINE:
                log.info("⏱ g4f: общий дедлайн исчерпан, прекращаю перебор")
                break
            if prov_name in self._dead_providers:
                continue
            model_pool = list(model_plan)
            provider_failed_hard = False
            length_fails_here = 0
            while model_pool:
                model = model_pool.pop(0)
                pair = (prov_name, model or "default")
                if pair in self._dead_pairs:
                    continue

                payload = dict(payload_common)
                payload["messages"] = (
                    _shrink_messages(base_messages, current_target)
                    if current_target else base_messages
                )

                try:
                    resp = await self._one_call(prov_obj, model, payload)
                except asyncio.TimeoutError:
                    errors.append(f"{prov_name}/{model or 'default'}: timeout")
                    log.debug(f"g4f: {pair} timeout")
                    self._dead_pairs.add(pair)
                    break
                except Exception as e:
                    msg = f"{type(e).__name__}: {e}"
                    errors.append(f"{prov_name}/{model or 'default'}: {msg[:200]}")
                    low = msg.lower()

                    if any(h in low for h in _AUTH_REQUIRED_HINTS):
                        found_any = False
                        for m_sub in re.finditer(
                            r"([A-Za-z][A-Za-z0-9_]+):\s*(MissingAuthError|NoValidHarFileError|MissingRequirementsError|AuthenticationRequiredError|Unauthorized|HTTPError: HTTP Error 401)",
                            msg,
                        ):
                            sub_name = m_sub.group(1)
                            if sub_name.lower() in ("retryprovidererror", "exception", "error"):
                                continue
                            self._auth_needed[sub_name] = _AUTH_HINT_URL.get(
                                sub_name, f"провайдер {sub_name} — нужен API key/cookies"
                            )
                            self._dead_providers.add(sub_name)
                            found_any = True
                        if not found_any and prov_name != "auto":
                            self._auth_needed[prov_name] = _AUTH_HINT_URL.get(
                                prov_name, f"провайдер {prov_name} — нужен API key/cookies"
                            )
                        self._dead_providers.add(prov_name)
                        provider_failed_hard = True
                        log.info(f"🔐 g4f: {prov_name} требует авторизацию — {msg[:80]}")
                        break

                    if any(h in low for h in _LENGTH_ERROR_HINTS):
                        if pair in self._shrunk_pairs:
                            self._dead_pairs.add(pair)
                            current_target = None
                            length_fails_here += 1
                            if length_fails_here >= _MAX_LENGTH_FAILS_PER_PROVIDER:
                                self._dead_providers.add(prov_name)
                                provider_failed_hard = True
                                log.info(f"🚫 g4f: {prov_name} — length на {length_fails_here} моделях, провайдер слишком мал, меняю провайдера")
                                break
                            log.info(f"g4f: {pair} — не тянет даже короткий контекст, меняю модель")
                            continue
                        self._shrunk_pairs.add(pair)
                        current_target = _SHRINK_TARGET_CHARS
                        model_pool.insert(0, model)
                        log.info(f"✂️ g4f: {pair} — контекст длинный, 1 попытка сжать до {current_target}")
                        continue

                    if any(h in low for h in _MODEL_ERROR_HINTS):
                        self._dead_pairs.add(pair)
                        current_target = None
                        log.debug(f"g4f: {pair} — модель не подходит, следующая")
                        continue

                    if any(h in low for h in _HARD_ERROR_HINTS):
                        self._dead_providers.add(prov_name)
                        provider_failed_hard = True
                        log.info(f"g4f: {prov_name} непригоден — {msg[:80]}")
                        break

                    current_target = None
                    log.debug(f"g4f: {pair} упал: {msg[:120]}")
                    continue

                if resp is None:
                    continue
                if _is_bad_response(resp):
                    self._dead_pairs.add(pair)
                    errors.append(f"{prov_name}/{model or 'default'}: bad content")
                    log.debug(f"g4f: {pair} — мусорный/ошибочный ответ, следующая")
                    current_target = None
                    continue
                self._last_ok = (prov_name, model)
                shrink_note = f" (контекст~{current_target})" if current_target else ""
                log.info(f"✅ g4f: {prov_name} / {model or 'default'}{shrink_note} — ok")
                return self._pack(resp)

            if provider_failed_hard:
                continue

        self._last_ok = None

        preview = "\n  ".join(errors[-20:])
        auth_marker = ""
        auth_lines = ""
        if self._auth_needed:
            names = "|".join(sorted(self._auth_needed.keys()))
            auth_marker = f"\n<!G4F_AUTH_NEEDED:{names}!>"
            items = "\n".join(f"  • {n} — {u}" for n, u in sorted(self._auth_needed.items()))
            auth_lines = (
                f"\n\n🔐 Провайдеры, которые просят API-ключ/регистрацию:\n{items}\n"
            )
        raise RuntimeError(
            f"g4f: не нашла ни одного рабочего бэкенда (перебрала {len(errors)} комбинаций).\n"
            f"Последние 20 ошибок:\n  {preview}\n"
            "Подсказки: pip install -U g4f curl_cffi; либо смени G4F_PROVIDER; "
            + auth_lines + auth_marker + "\n"
            "либо возьми DEFAULT_PROVIDER=gemini/openai/claude/deepseek/ollama."
        )

    def _pack(self, resp) -> ChatResponse:
        msg = resp.choices[0].message
        tool_calls: list[ToolCall] = []
        for tc in (getattr(msg, "tool_calls", None) or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            tool_calls.append(ToolCall(
                id=getattr(tc, "id", tc.function.name),
                name=tc.function.name,
                arguments=args,
            ))
        text = getattr(msg, "content", None) or ""
        cleaned, inline = _extract_inline_tool_calls(text)
        if inline:
            log.info(f"g4f: вытащила {len(inline)} tool_call(s) из JSON в тексте")
            tool_calls.extend(inline)
            text = cleaned
        return ChatResponse(text=text, tool_calls=tool_calls, raw=resp)
