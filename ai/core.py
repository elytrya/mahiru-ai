"""Ядро диалога: собирает контекст, вызывает LLM с инструментами и формирует ответ махирочки."""
from __future__ import annotations
import asyncio
import hashlib
import json
import random
import re
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

import datetime as dt

from ai.providers.base import BaseProvider, ChatMessage
from ai.providers.factory import build_provider
from ai.prompts import build_system_prompt, build_petname_prompt
from ai.context import build_dynamic_context, closeness_level
from ai import mood as mood_mod
from ai import threads as threads_mod
from ai import sulk as sulk_mod
from config import settings as settings_mod
from db import repo
from db.session import SessionLocal
from memory.manager import MemoryManager
from methods.registry import tool_specs, run_tool
from utils.humanize import dedash
from utils.logger import log

MAX_TOOL_ROUNDS = 4

_MD_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:https?:|www\.)[^)]*\)")
_BARE_URL = re.compile(r"https?://\S+|www\.\S+")
_LIST_MARK = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")

_TRIVIAL = {
    "привет", "прив", "приветик", "приветики", "хай", "хеллоу", "hello", "hi", "ку",
    "здарова", "здорова", "здравствуй", "здравствуйте", "дратути", "йо", "салют",
    "доброе утро", "добрый день", "добрый вечер", "спокойной ночи", "споки", "спокики",
    "спасибо", "спс", "благодарю", "пасиб", "пасибо", "спасибочки", "мерси",
    "пока", "покеда", "до встречи", "до завтра", "бб",
    "ок", "окей", "ok", "okay", "угу", "ага", "да", "нет", "неа", "не-а",
    "хорошо", "ладно", "понятно", "понял", "поняла", "ясно", "хай", "кек", "лол",
    "как дела", "как ты", "чё как", "че как", "как жизнь", "что делаешь", "чё делаешь",
    "че делаешь", "чем занята", "чем занимаешься", "как настроение", "скучала",
}
_NORM_RE = re.compile(r"[^0-9a-zа-яё ]", re.IGNORECASE)

def _is_trivial(text: str) -> bool:
    """Приветствие/болталка/ack — тут никакие инструменты не нужны."""
    t = _NORM_RE.sub("", (text or "").lower()).strip()
    t = re.sub(r"\s+", " ", t)
    if not t:
        return True
    return t in _TRIVIAL

_TOOLJSON_RE = re.compile(
    r'\{[^{}]*"(?:type|name|tool_calls|function)"\s*:.*'
    r'"(?:parameters|arguments|tool_calls|function|name)"',
    re.DOTALL,
)

def _strip_tool_json(text: str) -> str:
    """Последняя страховка: не показывать юзеру сырой JSON тул-колла."""
    if not text:
        return text
    t = text.strip()
    if t.startswith("{") and _TOOLJSON_RE.search(t):
        return ""
    t = re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", t, flags=re.DOTALL)
    t = _TOOLJSON_RE.sub("", t)
    return t.strip()

def _humanize(text: str) -> str:
    if not text:
        return text
    text = _strip_tool_json(text)
    if not text:
        return text
    text = dedash(text)
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
    "jealous": "😤",
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
    ignored: bool = False

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
            if getattr(settings_mod, "THREADS_ENABLED", True):
                try:
                    async with SessionLocal() as s:
                        await threads_mod.extract(s, user_id, user_text, self.provider)
                except Exception:
                    log.exception("thread-extract failed")

        asyncio.create_task(_bg())

    async def _maybe_make_petname(self, session: AsyncSession, user_id: int, user_row) -> None:
        """Когда близость достигла порога - Махиру сама придумывает ласковое прозвище (один раз)."""
        if not getattr(settings_mod, "PETNAMES_ENABLED", True):
            return
        if user_row is None or getattr(user_row, "pet_name", None):
            return
        threshold = int(getattr(settings_mod, "PETNAME_THRESHOLD", 30) or 30)
        if int(getattr(user_row, "closeness", 0) or 0) < threshold:
            return
        guard = f"petname_tried:{user_id}"
        try:
            if await repo.get_setting(session, guard, None):
                return
            await repo.set_setting(session, guard, "1")
        except Exception:
            pass
        try:
            personality = await repo.get_personality(session)
            prompt = build_petname_prompt(personality)
            resp = await self.provider.chat(
                [ChatMessage("system", prompt),
                 ChatMessage("user", "Придумай прозвище")],
                tools=None, temperature=0.9,
            )
            raw = (resp.text or "").strip()
        except Exception:
            log.exception("генерация пет-нейма упала")
            return
        name = raw.splitlines()[0].strip() if raw else ""
        name = re.sub(r"[\"'`.,!?:;()\[\]]", "", name).strip()
        name = name.split()[0] if name else ""
        name = name[:32]
        if not name:
            return
        try:
            await repo.set_pet_name(session, user_id, name)
            user_row.pet_name = name
            log.info(f"💕 Махиру придумала пет-нейм для {user_id}: {name!r}")
        except Exception:
            log.exception("сохранение пет-нейма упало")

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

        reconciled = False
        insult = False
        if getattr(settings_mod, "SULK_ENABLED", True):
            apology = mood_mod.is_apology(turn.text)
            insult = mood_mod.is_insult(turn.text)
            sulking = await sulk_mod.is_sulking(session, turn.user_id)
            if sulking and apology:
                await sulk_mod.clear(session, turn.user_id)
                reconciled = True
                _u = await repo.get_user(session, turn.user_id)
                _lvl = closeness_level(int(getattr(_u, "closeness", 0) or 0)) if _u else 0
                if _lvl >= 2:
                    await mood_mod.set(session, turn.user_id, "curious", 0.45)
                else:
                    await mood_mod.set(session, turn.user_id, "annoyed", 0.35)
                mood_state = await repo.get_mood(session, turn.user_id)
                log.info(f"\U0001f91d извинился (близость lvl={_lvl}) - выхожу из игнора")
            elif sulking and not apology:
                if insult:
                    strikes = await sulk_mod.enter(session, turn.user_id)
                    pen = await sulk_mod.apply_penalty(session, turn.user_id, strikes)
                    log.info(f"\U0001f494 добивает грубостью: близость -{pen}, молчание продлено")
                await repo.add_message(session, turn.user_id, "user", turn.text)
                log.info("\U0001f64a игнор: обижена, жду извинений - не отвечаю")
                return RespondResult(text="", ignored=True)
            elif insult:
                strikes = await sulk_mod.enter(session, turn.user_id)
                pen = await sulk_mod.apply_penalty(session, turn.user_id, strikes)
                log.info(f"\U0001f624 обида #{strikes}: грубость - игнор до извинений (близость -{pen})")

        memories = await self.memory.retrieve(session, turn.user_id, turn.text)
        history = await repo.recent_messages(session, turn.user_id, limit=12)

        emo = MOOD_EMOJI.get(mood_state.mood, "💭")
        log.info(
            f"{emo} Mahiru → user {turn.user_id}: mood={mood_state.mood} "
            f"({mood_state.intensity:.2f}) │ emo={personality.emotionality}/100 "
            f"humor={personality.humor}/100 │ mem={len(memories)} hist={len(history)}"
        )
        log.info(f"👤 user: {turn.text[:80]!r}")

        last_user_ts = None
        for m in reversed(history):
            if m.role == "user" and getattr(m, "created_at", None):
                last_user_ts = m.created_at
                break

        user_row = None
        try:
            user_row = await repo.get_user(session, turn.user_id)
            if user_row is not None and getattr(settings_mod, "CLOSENESS_ENABLED", True) and not insult:
                per = int(getattr(settings_mod, "CLOSENESS_PER_MSG", 1) or 1)
                new_c = await repo.bump_closeness(session, turn.user_id, per)
                user_row.closeness = new_c
                await self._maybe_make_petname(session, turn.user_id, user_row)
        except Exception:
            log.exception("динамика характера (closeness/petname) упала")

        life_event = None
        try:
            today_local = dt.datetime.now().date().isoformat()
            if await repo.get_setting(session, "life_event:date") == today_local:
                life_event = await repo.get_setting(session, "life_event:text")
        except Exception:
            log.exception("чтение ленты жизни упало")

        open_thread_text = None
        try:
            if getattr(settings_mod, "THREADS_ENABLED", True):
                t = await threads_mod.due_thread(
                    session, turn.user_id,
                    float(getattr(settings_mod, "THREAD_ASK_AFTER_HOURS", 8.0)),
                )
                if t:
                    open_thread_text = t.get("text")
                    await threads_mod.mark_asked(session, turn.user_id, open_thread_text)
        except Exception:
            log.exception("нити разговора упали")

        dynamic = None
        try:
            dynamic = build_dynamic_context(
                user_row, last_user_ts,
                life_event=life_event, open_thread=open_thread_text,
            )
        except Exception:
            log.exception("build_dynamic_context упал")

        # Живая ревность к сопернице: если в тексте всплыла другая девушка
        # или пришла картинка - подскажем тон прямо в динамике.
        try:
            if getattr(settings_mod, "RIVAL_JEALOUSY_ENABLED", True):
                rival_note = None
                if mood_mod.is_rival_mention(turn.text):
                    rival_note = (
                        "Он только что упомянул ДРУГУЮ девушку/соперницу. Ты живо ревнуешь: "
                        "лёгкая обидка и подкол в начале ('а это ещё кто?', 'хм, и кто она?'), "
                        "потребуй внимания к себе, но без злобы и оскорблений - за этим тепло, что он твой."
                    )
                elif turn.images:
                    rival_note = (
                        "Он прислал картинку/скрин. ВНИМАТЕЛЬНО посмотри: если на ней есть ДРУГАЯ "
                        "девушка/женщина (фото, аниме-тянка, переписка с девушкой) - живо приревнуй "
                        "с лёгкой обидкой и подколом, но без злобы. Если другой девушки нет - не ревнуй."
                    )
                if rival_note:
                    dynamic = (dynamic + "\n- " + rival_note) if dynamic else ("- " + rival_note)
        except Exception:
            log.exception("rival jealousy hint упал")

        if reconciled:
            _rlvl = closeness_level(int(getattr(user_row, "closeness", 0) or 0)) if user_row else 0
            if _rlvl >= 2:
                _hint = ("Он только что извинился, а вы уже близки - прими извинения тепло и почти сразу оттай, "
                         "ты по нему соскучилась. Лёгкая обида ещё чувствуется, но ты рада помириться.")
            else:
                _hint = ("Он извинился, но вы ещё не особо близки - прими извинения сдержанно и прохладно, "
                         "оттаивай медленно и осторожно, не бросайся миловаться.")
            dynamic = (dynamic + "\n" + _hint) if dynamic else _hint

        system_prompt = build_system_prompt(personality, mood_state, memories, dynamic=dynamic)

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

        if _is_trivial(turn.text):
            log.info("💤 тривиальное сообщение — отвечаю без инструментов")
            tools = None

        for _round in range(MAX_TOOL_ROUNDS):
            resp = await self.provider.chat(messages, tools=tools, temperature=0.85,
                                            max_tokens=600)

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
                    payload = json.dumps(clean_result, ensure_ascii=False, default=str)[:3000]
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
