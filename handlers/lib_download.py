"""Скачивание глав манги/тайтлов и отправка их пользователю."""
from __future__ import annotations
import asyncio
import hashlib
import random
import re
import time
from dataclasses import dataclass, field
from html import escape as _hesc

from aiogram import Router, F
from aiogram.types import (Message, CallbackQuery, FSInputFile,
                           InputMediaPhoto, BufferedInputFile,
                           InlineKeyboardMarkup, InlineKeyboardButton)

from config import settings
from db.session import SessionLocal
from db import repo
from methods.lib.client import api_get, download_bytes, LibError
from methods.lib.downloader import LibDownloadTool, max_chapters
from methods.lib.search import LibSearchTool
from methods.lib.meta import fetch_title_meta, fetch_covers
from utils.logger import log

router = Router(name="lib_download")

_DL_VERBS = (
    r"(?:скача\w*|скачай\w*|скач|качн\w*|кача\w*|загруз\w*|выкач\w*|"
    r"скин\w*|пришл\w*|присыл\w*|достан\w*|сохран\w*|download)"
)
_KIND_WORDS = {
    "ranobe": r"ранобэ|ранобе|ранобчик|новелл|ranobe|novel",
    "hentai": r"хентай|хентайчик|hentai|18\+|додзинси|доджинси",
    "manga": r"мангу|манга|манги|манхв|манхуа|маньхуа|комикс|manga|manhwa",
}
_FILLER = {
    "я", "хочу", "хотел", "хотела", "бы", "б", "пожалуйста", "плиз", "пж",
    "please", "мне", "ещё", "еще", "эту", "это", "эт", "главы", "главу",
    "всю", "все", "всё", "новую", "давай", "ну", "же", "можешь", "можно",
    "ты", "а", "и", "на", "мне-то",
    "ее", "её", "его", "их", "нее", "неё", "него", "нею", "них",
    "этот", "эта", "эти", "этого", "этой", "тот", "та", "те", "it", "them",
}

_TITLE_QUOTE_RE = re.compile(r'[«"“„]\s*([^«»"“”„\n]{2,60}?)\s*[»"”“]')

def _has_kind_word(text: str) -> bool:
    low = (text or "").lower()
    return any(re.search(pat, low) for pat in _KIND_WORDS.values())

async def resolve_last_title(session, user_id: int) -> str | None:
    """Если в запросе местоимение ('её'), тянем последний тайтл из переписки (в кавычках)."""
    try:
        msgs = await repo.recent_messages(session, user_id, limit=12)
    except Exception:
        return None
    for m in reversed(msgs):
        found = _TITLE_QUOTE_RE.findall(getattr(m, "content", "") or "")
        if found:
            return found[-1].strip()
    return None

async def resolve_download_target(session, user_id: int, text: str,
                                 intent: tuple[str, str]) -> tuple[str, str] | None:
    """Разрешает (kind, query) для скачивания, подтягивая название из контекста."""
    kind, query = intent
    if query and len(query) >= 2:
        return kind, query
    explicit_kind = _has_kind_word(text)
    prev = _LAST_QUERY.get(user_id)
    if prev:
        prev_kind, prev_q = prev
        if not explicit_kind:
            kind = prev_kind
        if prev_q and len(prev_q) >= 2:
            return kind, prev_q
    found = await resolve_last_title(session, user_id)
    if found and len(found) >= 2:
        return kind, found
    return None

def _clean_query(text: str) -> str:
    words = [w for w in re.split(r"\s+", text or "")
             if w and w.lower().strip(".,!?—–-«»\"'") not in _FILLER]
    return " ".join(words).strip(" —–-.,!?«»\"'")

def _looks_like_title(text: str) -> bool:
    """Похоже ли сообщение на название тайтла (а не вопрос/болталка)."""
    t = (text or "").strip()
    if not t or "?" in t:
        return False
    if len(t.split()) > 7:
        return False
    if t.lower() in {"да", "давай", "ок", "окей", "ага", "нет", "неа", "не-а"}:
        return False
    return True

async def maybe_followup_download(session, user_id: int, text: str) -> tuple[str, str] | None:
    """После 'не нашла, напиши точнее' — следующее название сразу запускает скачивание."""
    ent = _AWAIT_TITLE.get(user_id)
    if not ent:
        return None
    kind, ts = ent
    if time.time() - ts > _AWAIT_TTL:
        _AWAIT_TITLE.pop(user_id, None)
        return None
    if not _looks_like_title(text):
        return None
    query = _clean_query(text) or text.strip()
    if len(query) < 2:
        return None
    _AWAIT_TITLE.pop(user_id, None)
    return kind, query

def detect_download_intent(text: str) -> tuple[str, str] | None:
    if not text:
        return None
    low = text.lower()
    if not re.search(_DL_VERBS, low):
        return None
    kind = "manga"
    for k in ("ranobe", "hentai", "manga"):
        if re.search(_KIND_WORDS[k], low):
            kind = k
            break
    anchor = 0
    pats = [_DL_VERBS, _KIND_WORDS.get(kind, "")]
    for pat in pats:
        if not pat:
            continue
        for m in re.finditer(pat, low):
            anchor = max(anchor, m.end())
    tail = text[anchor:]
    tail = re.sub(r"^[\s,.:;!?—–-]+", "", tail)
    words = [w for w in re.split(r"\s+", tail)
             if w and w.lower().strip(".,!?—–-«»\"'") not in _FILLER]
    query = " ".join(words).strip(" —–-.,!?«»\"'")
    return kind, query

_TTL = 1800
PAGE = 24
COLS = 4

@dataclass
class _SearchState:
    user_id: int
    kind: str
    query: str
    items: list[dict]
    ts: float = field(default_factory=time.time)

@dataclass
class _DLState:
    user_id: int
    kind: str
    slug: str
    title: str
    chapters: list[dict]
    selected: set[int] = field(default_factory=set)
    page: int = 0
    ts: float = field(default_factory=time.time)

_SEARCH: dict[str, _SearchState] = {}
_DL: dict[str, _DLState] = {}
_LAST_QUERY: dict[int, tuple[str, str]] = {}
_AWAIT_TITLE: dict[int, tuple[str, float]] = {}
_AWAIT_TTL = 600

def _gc() -> None:
    now = time.time()
    for store in (_SEARCH, _DL):
        dead = [k for k, v in store.items() if now - v.ts > _TTL]
        for k in dead:
            store.pop(k, None)

def _sid(prefix: str, user_id: int) -> str:
    raw = f"{prefix}:{user_id}:{time.time()}:{random.random()}"
    return hashlib.sha1(raw.encode()).hexdigest()[:8]

def _kind_word(kind: str) -> str:
    return {"ranobe": "ранобэ", "hentai": "хентай", "manga": "мангу"}.get(kind, "тайтл")

def _num(c: dict) -> float:
    try:
        return float(c.get("number"))
    except Exception:
        return 1e9

def _vol(c: dict) -> float:
    try:
        return float(c.get("volume"))
    except Exception:
        return 1e9

async def _flavor(user_id: int, key: str) -> str:
    mood = "happy"
    try:
        async with SessionLocal() as s:
            m = await repo.get_mood(s, user_id)
            mood = m.mood
    except Exception:
        pass
    banks = {
        "searching": {
            "annoyed": ["Ладно, ищу… но ты мне должен 😒", "Ну ок, секунду, ищу."],
            "tired":   ["Мм, сейчас гляну… держи.", "Ок, ищу, только не торопи."],
            "loving":  ["Конечно, солнышко, сейчас найду ❤️", "Для тебя — что угодно, ищу."],
            "_":       ["Оки, сейчас поищу 👀", "Сек, смотрю что есть.", "О, давай глянем!"],
        },
        "found": {
            "_": ["Вот что нашла — выбери какой:", "Смотри, есть вот эти. Какой именно?",
                  "Нашла несколько — тыкай нужный:"],
        },
        "notfound": {
            "_": ["Мм, ничего не нашла по «{q}» 😔 Может, напишешь точнее?",
                  "Не нахожу «{q}»… попробуй другое название."],
        },
        "picked": {
            "_": ["Отличный выбор! Теперь отметь главы 👇", "О, этот знаю! Выбирай главы:",
                  "Ага, есть. Отмечай что качать:"],
        },
    }
    bank = banks.get(key, {})
    variants = bank.get(mood) or bank.get("_") or [""]
    return random.choice(variants)

async def start_download_flow(msg: Message, user_id: int, kind: str, query: str) -> None:
    _gc()
    await msg.answer(await _flavor(user_id, "searching"))

    try:
        res = await LibSearchTool().run({"query": query, "kind": kind, "limit": 8},
                                        session=None, user_id=user_id)
    except Exception:
        log.exception("lib_search failed")
        res = {"error": "поиск упал"}

    if not isinstance(res, dict) or res.get("error") or not res.get("items"):
        note = (await _flavor(user_id, "notfound")).format(q=query)
        await msg.answer(note)
        _AWAIT_TITLE[user_id] = (kind, time.time())
        return

    items = res["items"]
    _LAST_QUERY[user_id] = (kind, query)
    _AWAIT_TITLE.pop(user_id, None)
    sid = _sid("s", user_id)
    _SEARCH[sid] = _SearchState(user_id=user_id, kind=kind, query=query, items=items)

    rows = []
    for i, it in enumerate(items):
        name = it.get("name") or it.get("eng_name") or "?"
        year = it.get("year") or ""
        chaps = it.get("chapters")
        rating = it.get("rating")
        bits = [name]
        extra = []
        if year:
            extra.append(str(year)[:4])
        if chaps:
            extra.append(f"{chaps} гл")
        if rating:
            extra.append(f"���{rating}")
        label = name if not extra else f"{name} — {', '.join(extra)}"
        rows.append([InlineKeyboardButton(text=label[:60],
                                          callback_data=f"libdl:pick:{sid}:{i}")])
    rows.append([InlineKeyboardButton(text="✖ Отмена", callback_data=f"libdl:cancel:{sid}")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    header = f"{await _flavor(user_id, 'found')}\n<i>по запросу «{query}» — {_kind_word(kind)}</i>"
    await msg.answer(header, reply_markup=kb, disable_web_page_preview=True)

async def _fetch_all_chapters(kind: str, slug: str) -> list[dict]:
    data = await api_get(kind, f"/api/manga/{slug}/chapters")
    chs = data.get("data") if isinstance(data, dict) else None
    out: list[dict] = []
    if isinstance(chs, list):
        for c in chs:
            if isinstance(c, dict):
                out.append({"volume": c.get("volume"), "number": c.get("number"),
                            "name": c.get("name") or ""})
    out.sort(key=lambda c: (_vol(c), _num(c)))
    return out

def _meta_caption(meta: dict) -> str:
    def e(x) -> str:
        return _hesc(str(x))

    parts: list[str] = [f"📖 <b>{e(meta.get('name') or '?')}</b>"]
    if meta.get("eng_name"):
        parts.append(f"<i>{e(meta['eng_name'])}</i>")
    line1 = " · ".join(e(x) for x in [meta.get("type"), meta.get("year"),
                                       meta.get("status"), meta.get("age")] if x)
    if line1:
        parts.append(line1)
    if meta.get("rating"):
        r = f"⭐ {e(meta['rating'])}"
        if meta.get("votes"):
            r += f" ({e(meta['votes'])})"
        if meta.get("views"):
            r += f" · 👁 {e(meta['views'])}"
        parts.append(r)
    if meta.get("genres"):
        parts.append("��� " + e(", ".join(meta["genres"][:8])))
    if meta.get("authors"):
        parts.append("✍️ " + e(", ".join(meta["authors"][:4])))
    if meta.get("teams"):
        parts.append("🌐 Перевод: " + e(", ".join(meta["teams"][:6])))
    summary = meta.get("summary") or ""
    if summary:
        if len(summary) > 450:
            summary = summary[:450].rstrip() + "…"
        parts.append("\n" + e(summary))
    return "\n".join(parts)[:1024]

async def _send_title_card(message: Message, kind: str, slug: str) -> None:
    meta = await fetch_title_meta(kind, slug)
    caption = _meta_caption(meta)

    covers: list[str] = []
    try:
        covers = await fetch_covers(kind, slug, limit=10)
    except Exception:
        pass
    if meta.get("cover") and meta["cover"] not in covers:
        covers.insert(0, meta["cover"])
    if not covers and meta.get("cover"):
        covers = [meta["cover"]]

    photos: list[bytes] = []
    for url in covers[:10]:
        try:
            photos.append(await download_bytes(url))
        except Exception:
            continue

    if not photos:
        await message.answer(caption, disable_web_page_preview=True)
        return
    if len(photos) == 1:
        await message.answer_photo(BufferedInputFile(photos[0], "cover.jpg"),
                                   caption=caption)
        return
    media = []
    for i, buf in enumerate(photos):
        img = BufferedInputFile(buf, f"cover_{i}.jpg")
        if i == 0:
            media.append(InputMediaPhoto(media=img, caption=caption, parse_mode="HTML"))
        else:
            media.append(InputMediaPhoto(media=img))
    try:
        await message.answer_media_group(media=media)
    except Exception:
        log.exception("media group send failed")
        await message.answer_photo(BufferedInputFile(photos[0], "cover.jpg"),
                                   caption=caption)

def _render_selector(st: _DLState) -> tuple[str, InlineKeyboardMarkup]:
    total = len(st.chapters)
    pages = max(1, (total + PAGE - 1) // PAGE)
    st.page = max(0, min(st.page, pages - 1))
    start = st.page * PAGE
    chunk = st.chapters[start:start + PAGE]

    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for off, ch in enumerate(chunk):
        idx = start + off
        num = ch.get("number")
        mark = "✅" if idx in st.selected else ""
        row.append(InlineKeyboardButton(text=f"{mark}{num}",
                                        callback_data=f"libdl:tog:{_find_sid(st)}:{idx}"))
        if len(row) == COLS:
            rows.append(row); row = []
    if row:
        rows.append(row)

    sid = _find_sid(st)
    if pages > 1:
        rows.append([
            InlineKeyboardButton(text="◀", callback_data=f"libdl:pg:{sid}:{st.page-1}"),
            InlineKeyboardButton(text=f"стр {st.page+1}/{pages}", callback_data="libdl:noop"),
            InlineKeyboardButton(text="▶", callback_data=f"libdl:pg:{sid}:{st.page+1}"),
        ])
    rows.append([
        InlineKeyboardButton(text="✅ Все", callback_data=f"libdl:all:{sid}"),
        InlineKeyboardButton(text="❎ Сброс", callback_data=f"libdl:none:{sid}"),
    ])
    presets = [n for n in (1, 3, 10) if n <= total]
    if presets:
        rows.append([InlineKeyboardButton(text=f"1–{n}" if n > 1 else "1 гл",
                                          callback_data=f"libdl:first:{sid}:{n}")
                     for n in presets])
    rows.append([
        InlineKeyboardButton(text=f"⬇️ Скачать ({len(st.selected)})",
                             callback_data=f"libdl:go:{sid}"),
        InlineKeyboardButton(text="✖ Отмена", callback_data=f"libdl:cancel:{sid}"),
    ])

    lim = max_chapters(st.kind)
    fmt_hint = "EPUB/TXT" if st.kind == "ranobe" else "CBZ/PDF"
    text = (
        f"📚 <b>{st.title}</b>\n"
        f"Глав всего: <b>{total}</b> · выбрано: <b>{len(st.selected)}</b> · формат: {fmt_hint} (спрошу перед скачкой)\n"
        f"<i>тыкай номера г��ав — потом «Скачать». Лимит за раз: {lim} гл.</i>"
    )
    return text, InlineKeyboardMarkup(inline_keyboard=rows)

def _find_sid(st: _DLState) -> str:
    for k, v in _DL.items():
        if v is st:
            return k
    return "?"

@router.callback_query(F.data == "libdl:noop")
async def cb_noop(cb: CallbackQuery):
    await cb.answer()

@router.callback_query(F.data.startswith("libdl:pick:"))
async def cb_pick(cb: CallbackQuery):
    _, _, sid, i = cb.data.split(":", 3)
    ss = _SEARCH.get(sid)
    if not ss:
        await cb.answer("Устарело, попроси заново 🌸", show_alert=True)
        return
    try:
        it = ss.items[int(i)]
    except Exception:
        await cb.answer("Не нашла этот пункт", show_alert=True)
        return
    slug = it.get("slug") or ""
    title = it.get("name") or it.get("eng_name") or slug
    if not slug:
        await cb.answer("У этого тайтла нет slug 😕", show_alert=True)
        return

    await cb.answer("Сек, тяну главы…")
    try:
        chapters = await _fetch_all_chapters(ss.kind, slug)
    except LibError as e:
        await cb.message.answer(f"Не смогла взять главы: {e}")
        return
    except Exception:
        log.exception("fetch chapters failed")
        await cb.message.answer("Ой, главы не загрузились 😓 Попробуй ещё раз.")
        return
    if not chapters:
        await cb.message.answer("У этого тайтла нет глав или нужен токен 😔")
        return

    try:
        await _send_title_card(cb.message, ss.kind, slug)
    except Exception:
        log.exception("title card failed")

    dsid = _sid("d", ss.user_id)
    st = _DLState(user_id=ss.user_id, kind=ss.kind, slug=slug, title=title,
                  chapters=chapters)
    st.selected.add(0)
    _DL[dsid] = st
    text = await _flavor(ss.user_id, "picked")
    sel_text, kb = _render_selector(st)
    await cb.message.answer(f"{text}\n\n{sel_text}", reply_markup=kb,
                            disable_web_page_preview=True)

async def _refresh(cb: CallbackQuery, st: _DLState):
    text, kb = _render_selector(st)
    try:
        await cb.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception:
        try:
            await cb.message.edit_reply_markup(reply_markup=kb)
        except Exception:
            pass

@router.callback_query(F.data.startswith("libdl:tog:"))
async def cb_toggle(cb: CallbackQuery):
    _, _, sid, idx = cb.data.split(":", 3)
    st = _DL.get(sid)
    if not st:
        await cb.answer("Устарело 🌸", show_alert=True)
        return
    i = int(idx)
    if i in st.selected:
        st.selected.discard(i)
    else:
        st.selected.add(i)
    st.ts = time.time()
    await cb.answer()
    await _refresh(cb, st)

@router.callback_query(F.data.startswith("libdl:pg:"))
async def cb_page(cb: CallbackQuery):
    _, _, sid, n = cb.data.split(":", 3)
    st = _DL.get(sid)
    if not st:
        await cb.answer("Устарело 🌸", show_alert=True)
        return
    st.page = int(n)
    st.ts = time.time()
    await cb.answer()
    await _refresh(cb, st)

@router.callback_query(F.data.startswith("libdl:all:"))
async def cb_all(cb: CallbackQuery):
    sid = cb.data.split(":", 2)[2]
    st = _DL.get(sid)
    if not st:
        await cb.answer("Устарело 🌸", show_alert=True)
        return
    st.selected = set(range(len(st.chapters)))
    st.ts = time.time()
    lim = max_chapters(st.kind)
    if len(st.selected) > lim:
        await cb.answer(f"Отметила все, но за раз скачаю макс {lim} — остальные потом.",
                        show_alert=True)
    else:
        await cb.answer("Выбрала все главы")
    await _refresh(cb, st)

@router.callback_query(F.data.startswith("libdl:none:"))
async def cb_none(cb: CallbackQuery):
    sid = cb.data.split(":", 2)[2]
    st = _DL.get(sid)
    if not st:
        await cb.answer("Устарело 🌸", show_alert=True)
        return
    st.selected.clear()
    st.ts = time.time()
    await cb.answer("Сбросила")
    await _refresh(cb, st)

@router.callback_query(F.data.startswith("libdl:first:"))
async def cb_first(cb: CallbackQuery):
    _, _, sid, n = cb.data.split(":", 3)
    st = _DL.get(sid)
    if not st:
        await cb.answer("Устарело 🌸", show_alert=True)
        return
    k = int(n)
    st.selected = set(range(min(k, len(st.chapters))))
    st.ts = time.time()
    await cb.answer(f"Отметила первые {k}")
    await _refresh(cb, st)

@router.callback_query(F.data.startswith("libdl:cancel:"))
async def cb_cancel(cb: CallbackQuery):
    sid = cb.data.split(":", 2)[2]
    _DL.pop(sid, None)
    _SEARCH.pop(sid, None)
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await cb.answer("Ок, отменила")
    await cb.message.answer("Как передумаешь — пиши 🌸")

@router.callback_query(F.data.startswith("libdl:go:"))
async def cb_go(cb: CallbackQuery):
    sid = cb.data.split(":", 2)[2]
    st = _DL.get(sid)
    if not st:
        await cb.answer("Устарело 🌸", show_alert=True)
        return
    if not st.selected:
        await cb.answer("Сначала отметь хотя бы одну главу 🙏", show_alert=True)
        return
    await cb.answer()
    n = len(st.selected)
    if st.kind == "ranobe":
        rows = [[
            InlineKeyboardButton(text="📕 EPUB (одним файлом)",
                                 callback_data=f"libdl:fmt:{sid}:epub"),
            InlineKeyboardButton(text="📄 TXT", callback_data=f"libdl:fmt:{sid}:txt"),
        ]]
    else:
        rows = [[
            InlineKeyboardButton(text="🗜 CBZ (архив)",
                                 callback_data=f"libdl:fmt:{sid}:cbz"),
            InlineKeyboardButton(text="📕 PDF", callback_data=f"libdl:fmt:{sid}:pdf"),
        ]]
    rows.append([
        InlineKeyboardButton(text="◀ К главам", callback_data=f"libdl:back:{sid}"),
        InlineKeyboardButton(text="✖ Отмена", callback_data=f"libdl:cancel:{sid}"),
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    txt = f"В каком формате собрать <b>{st.title}</b> ({n} гл.)?"
    try:
        await cb.message.edit_text(txt, reply_markup=kb, disable_web_page_preview=True)
    except Exception:
        await cb.message.answer(txt, reply_markup=kb, disable_web_page_preview=True)

@router.callback_query(F.data.startswith("libdl:back:"))
async def cb_back(cb: CallbackQuery):
    sid = cb.data.split(":", 2)[2]
    st = _DL.get(sid)
    if not st:
        await cb.answer("Устарело 🌸", show_alert=True)
        return
    await cb.answer()
    await _refresh(cb, st)

@router.callback_query(F.data.startswith("libdl:fmt:"))
async def cb_fmt(cb: CallbackQuery):
    _, _, sid, fmt = cb.data.split(":", 3)
    st = _DL.get(sid)
    if not st:
        await cb.answer("Устарело 🌸", show_alert=True)
        return
    await _do_download(cb, sid, st, fmt)

async def _do_download(cb: CallbackQuery, sid: str, st: _DLState, fmt: str) -> None:
    idxs = sorted(st.selected)
    if not idxs:
        await cb.answer("Сначала отметь хотя бы одну главу 🙏", show_alert=True)
        return
    lim = max_chapters(st.kind)
    truncated = len(idxs) > lim
    if truncated:
        idxs = idxs[:lim]
    selected = [st.chapters[i] for i in idxs]
    first_n = selected[0].get("number")
    last_n = selected[-1].get("number")

    await cb.answer("Начинаю 🚀")
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    extra = f" (обрезала до {lim})" if truncated else ""
    status = await cb.message.answer(
        f"⏳ Качаю <b>{st.title}</b> — {len(selected)} гл. ({first_n}…{last_n}){extra}, "
        f"формат {fmt.upper()}. Это может занять пару минут…"
    )

    tool = LibDownloadTool()
    try:
        if st.kind == "ranobe":
            res = await tool._download_ranobe(st.kind, st.slug, selected,
                                              fmt=fmt, title=st.title)
        else:
            res = await tool._download_manga(st.kind, st.slug, selected, fmt=fmt)
    except Exception as e:
        log.exception("download failed")
        res = {"error": str(e)}

    if not isinstance(res, dict) or res.get("error"):
        err = res.get("error") if isinstance(res, dict) else "неизвестно"
        try:
            await status.edit_text(f"Не получилось 😢\n<code>{err}</code>")
        except Exception:
            await cb.message.answer(f"Не получилось 😢 {err}")
        return

    path = res.get("_send_file") or res.get("path")
    caption = res.get("caption") or st.title
    try:
        await status.edit_text("Готово! Держи 🌸")
    except Exception:
        pass
    kb = None
    if settings.SHOW_TOOL_CALLS:
        try:
            from ai.core import ToolTrace
            from handlers.messages import _tools_keyboard
            tname = "lib_download"
            targs = {"kind": st.kind, "slug": st.slug,
                     "chapters": len(selected), "format": fmt}
            skipped = res.get("skipped") or 0
            summary = f"{st.title[:24]} ({len(selected)} гл.)"
            if skipped:
                summary += f", проп. {skipped}"
            kb = _tools_keyboard([ToolTrace(name=tname, arguments=targs,
                                           ok=True, summary=summary)])
        except Exception as e:
            log.debug(f"lib_download: кнопка тула не собралась: {e}")
    import os
    size = os.path.getsize(path) if path and os.path.exists(path) else 0

    async def _too_big_note() -> None:
        mb = f"{size / (1024 * 1024):.1f} МБ" if size else "больше 50 МБ"
        fname = os.path.basename(path) if path else "?"
        folder = os.path.dirname(os.path.abspath(path)) if path else "downloads"
        await cb.message.answer(
            f"Файл собрала ({mb}), но Telegram не даёт отправить — у ботов лимит 50 МБ 😔\n"
            f"Я сохранила его тебе локально, забери из папки загрузок:\n"
            f"📁 <code>{_hesc(folder)}</code>\n"
            f"📄 <b>{_hesc(fname)}</b>\n"
            f"<i>Совет: возьми меньше глав за раз или формат полегче (TXT/EPUB/CBZ).</i>"
        )

    if size > 49 * 1024 * 1024:
        try:
            await status.edit_text("Готово, но файл большой 📦")
        except Exception:
            pass
        await _too_big_note()
        _DL.pop(sid, None)
        return

    try:
        await cb.message.answer_document(FSInputFile(path), caption=caption[:1000],
                                         reply_markup=kb)
    except Exception:
        log.exception("send document failed")
        await _too_big_note()
        return
    _DL.pop(sid, None)
