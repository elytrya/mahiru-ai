from __future__ import annotations
import asyncio
import hashlib
import json
import random
import re
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from ai.providers.base import BaseProvider, ChatMessage
from ai.providers.factory import build_provider
from ai.prompts import build_system_prompt
from ai import mood as mood_mod
from db import repo
from db.session import SessionLocal
from memory.manager import MemoryManager
from methods.registry import tool_specs, run_tool
from utils.logger import log

MAX_TOOL_ROUNDS = 4  # больше и так не надо

_MD_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:https?:|www\.)[^)]*\)")
_BARE_URL = re.compile(r"https?://\S+|www\.\S+")
_LIST_MARK = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")

# выпиливаем ссылки и картинки, она не каталог
def _humanize(text: str) -> str:
    if not text:
        return text
    text = _MD_IMG.sub("", text)
    text = _MD_LINK.sub(lambda m: m.group(1), text)
    text = _BARE_URL.sub("", text)
    lines: list[str] = []
    for ln in text.splitlines():
        stripped = ln.strip()
        if not stripped or _LIST_MARK.fullmatch(ln):
            if not stripped:
                lines.append("")
            continue
        stripped = _LIST_MARK.sub("", stripped)
        stripped = re.sub(r"\s*[-–—:]\s*$", "", stripped).strip()
        if stripped:
            lines.append(stripped)
    text = "\n".join(lines)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text

AUTO_MEMORY_CHANCE = 0.35
AUTO_MEMORY_EVERY = 6

MOOD_EMOJI = {
    "happy":   "😊",
    "sad":     "😢",
    "tired":   "😴",
    "excited": "✨",
    "curious": "🔎",
    "annoyed": "😒",
    "playful": "😜",
    "loving":  "🫧",
}

_MSG_COUNTER: dict[int, int] = {}

@dataclass
class Turn:
    user_id: int
    text: str
    images: list[bytes] | None = None

@dataclass
class ToolTrace:
    name: str
    arguments: dict
    ok: bool = True
    summary: str = ""

@dataclass
class Attachment:
    kind: str
    path: str | None = None
    url: str | None = None
    caption: str | None = None
    text: str | None = None

@dataclass
class RespondResult:
    text: str
    tools: list[ToolTrace] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)

def _summarize_args(name: str, args: dict) -> str:
    if not isinstance(args, dict):
        return ""
    for k in ("query", "title", "q", "name", "fact", "text", "url"):
        v = args.get(k)
        if isinstance(v, str) and v:
            return v[:40]
    try:
        return json.dumps(args, ensure_ascii=False)[:40]
    except Exception:
        return ""

def _call_key(name: str, args: dict) -> str:
    try:
        payload = json.dumps(args or {}, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        payload = str(args)
    return f"{name}::{hashlib.sha1(payload.encode()).hexdigest()[:16]}"

def _dedup_tool_calls(calls):
    seen: set[str] = set()
    out = []
    for tc in calls:
        key = _call_key(tc.name, tc.arguments or {})
        if key in seen:
            log.debug(f"🧹 дубликат tool_call {tc.name} скип")
            continue
        seen.add(key)
        out.append(tc)
    return out

def _extract_attachments(result) -> list[Attachment]:
    if not isinstance(result, dict):
        return []
    out: list[Attachment] = []
    if result.get("_send_file"):
        out.append(Attachment(kind="file", path=str(result["_send_file"]),
                              caption=result.get("caption")))
    if result.get("_send_photo"):
        p = result["_send_photo"]
        if isinstance(p, str) and p.startswith("http"):
            out.append(Attachment(kind="photo", url=p, caption=result.get("caption")))
        else:
            out.append(Attachment(kind="photo", path=str(p), caption=result.get("caption")))
    if result.get("_send_message"):
        out.append(Attachment(kind="message", text=str(result["_send_message"])))
    return out

class AICore:
    def __init__(self, provider: BaseProvider | None = None):
        self.provider = provider or build_provider()
        self.memory = MemoryManager()

    async def _maybe_observe(self, user_id: int, user_text: str, bot_text: str) -> None:
        cnt = _MSG_COUNTER.get(user_id, 0) + 1
        _MSG_COUNTER[user_id] = cnt
        forced = (cnt % AUTO_MEMORY_EVERY == 0)
        if not forced and random.random() > AUTO_MEMORY_CHANCE:
            return

        async def _bg():
            try:
                async with SessionLocal() as s:
                    await self.memory.observe(s, user_id, user_text, bot_text, self.provider)
            except Exception:
                log.exception("auto-observe failed")

        asyncio.create_task(_bg())

    async def respond(self, session: AsyncSession, turn: Turn) -> RespondResult:
        personality = await repo.get_personality(session)
        mood_state = await repo.get_mood(session, turn.user_id)

        _rmood, reacted = await mood_mod.react_to_message(
            session, turn.user_id, turn.text, chance=0.5
        )
        if reacted:
            mood_state = await repo.get_mood(session, turn.user_id)
            log.info(
                f"💥 mood react: {MOOD_EMOJI.get(mood_state.mood, '')} "
                f"{mood_state.mood} (intensity={mood_state.intensity:.2f})"
            )
        else:
            _rm, recovered = await mood_mod.relax(session, turn.user_id)
            if recovered:
                mood_state = await repo.get_mood(session, turn.user_id)
                log.info(
                    f"🌤 mood relax → {MOOD_EMOJI.get(mood_state.mood, '')} "
                    f"{mood_state.mood} (intensity={mood_state.intensity:.2f})"
                )
            else:
                _new_mood, drift = await mood_mod.maybe_drift(session, turn.user_id, chance=0.1)
                if drift:
                    mood_state = await repo.get_mood(session, turn.user_id)
                    log.info(
                        f"🌀 mood drift: {MOOD_EMOJI.get(mood_state.mood, '')} "
                        f"{mood_state.mood} (intensity={mood_state.intensity:.2f})"
                    )

        memories = await self.memory.retrieve(session, turn.user_id, turn.text)
        history = await repo.recent_messages(session, turn.user_id, limit=16)

        emo = MOOD_EMOJI.get(mood_state.mood, "💭")
        log.info(
            f"{emo} Mahiru → user {turn.user_id}: mood={mood_state.mood} "
            f"({mood_state.intensity:.2f}) │ emo={personality.emotionality}/100 "
            f"humor={personality.humor}/100 │ mem={len(memories)} hist={len(history)}"
        )
        log.info(f"👤 user: {turn.text[:80]!r}")

        system_prompt = build_system_prompt(personality, mood_state, memories)

        messages: list[ChatMessage] = [ChatMessage("system", system_prompt)]
        for m in history:
            role = m.role if m.role in ("user", "assistant") else "user"
            messages.append(ChatMessage(role, m.content))
        messages.append(ChatMessage("user", turn.text, images=turn.images))

        await repo.add_message(session, turn.user_id, "user", turn.text)

        tool_traces: list[ToolTrace] = []
        attachments: list[Attachment] = []
        called_keys: set[str] = set()
        tools = tool_specs()

        log.info(
            f"🧠 контекст: провайдер={getattr(self.provider, 'name', '?')} "
            f"model={getattr(self.provider, 'model', '?')} │ память={len(memories)} "
            f"история={len(history)} тулов_доступно={len(tools)}"
        )

        for _round in range(MAX_TOOL_ROUNDS):
            resp = await self.provider.chat(messages, tools=tools, temperature=0.85)

            calls = _dedup_tool_calls(resp.tool_calls or [])
            if calls:
                for tc in calls:
                    key = _call_key(tc.name, tc.arguments or {})
                    if key in called_keys:
                        log.debug(f"🧹 {tc.name} уже вызывалась, не повторяю")
                        continue
                    called_keys.add(key)

                    log.info(f"🔧 tool: {tc.name}({_summarize_args(tc.name, tc.arguments) or '…'})")
                    ok = True
                    try:
                        result = await run_tool(
                            tc.name, tc.arguments, session=session, user_id=turn.user_id
                        )
                    except Exception as e:
                        log.exception("tool error")
                        result = {"error": str(e)}
                        ok = False
                    if isinstance(result, dict) and result.get("error"):
                        ok = False
                    log.info(f"   ↳ {tc.name}: {'✅ ok' if ok else '⚠️ ошибка'}")

                    for att in _extract_attachments(result):
                        attachments.append(att)

                    tool_traces.append(ToolTrace(
                        name=tc.name,
                        arguments=tc.arguments or {},
                        ok=ok,
                        summary=_summarize_args(tc.name, tc.arguments or {}),
                    ))
                    if isinstance(result, dict):
                        clean_result = {k: v for k, v in result.items()
                                        if not k.startswith("_send_") and k != "_bytes"}
                    else:
                        clean_result = result
                    payload = json.dumps(clean_result, ensure_ascii=False, default=str)[:6000]
                    messages.append(ChatMessage("tool", payload,
                                                name=tc.name, tool_call_id=tc.id))

                if not (resp.text or "").strip():
                    continue
                text = _humanize(resp.text.strip())
                await repo.add_message(session, turn.user_id, "assistant", text)
                await self._maybe_observe(turn.user_id, turn.text, text)
                log.info(f"💬 Mahiru: {text[:80]!r} │ тулов={len(tool_traces)} "
                         f"вложений={len(attachments)}")
                return RespondResult(text=text, tools=tool_traces, attachments=attachments)

            text = _humanize((resp.text or "").strip())
            if not text:
                text = "Мм... кажется, я задумалась и потеряла мысль"
            await repo.add_message(session, turn.user_id, "assistant", text)
            await self._maybe_observe(turn.user_id, turn.text, text)
            log.info(f"💬 Mahiru: {text[:80]!r} │ тулов={len(tool_traces)} "
                     f"вложений={len(attachments)}")
            return RespondResult(text=text, tools=tool_traces, attachments=attachments)

        return RespondResult(text="Мозги вскипели... давай попробуем ещё раз?",
                             tools=tool_traces, attachments=attachments)
