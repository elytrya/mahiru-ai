from __future__ import annotations

import html
import random
import re
import time
from collections import deque
from dataclasses import dataclass, field

from aiogram import F, Router
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message, URLInputFile)

from config import settings
from db import repo
from db.session import SessionLocal
from methods.steam.search import (APP_PAGE, SteamReviewsTool,
                                  steam_store_search)
from utils.logger import log

router = Router(name="steam_flow")

_POPULAR: list[tuple[int, str, list[str]]] = [
    (570,     "Dota 2", ["дота", "dota"]),
    (730,     "Counter-Strike 2", ["кс", "контра", "cs", "counter"]),
    (578080,  "PUBG: BATTLEGROUNDS", ["пубг", "pubg"]),
    (1172470, "Apex Legends", ["апекс", "apex"]),
    (1091500, "Cyberpunk 2077", ["киберпанк", "cyberpunk"]),
    (292030,  "The Witcher 3: Wild Hunt", ["ведьмак", "witcher"]),
    (271590,  "Grand Theft Auto V", ["гта", "gta"]),
    (1245620, "ELDEN RING", ["элден", "elden"]),
    (1174180, "Red Dead Redemption 2", ["рдр", "rdr", "red dead"]),
    (413150,  "Stardew Valley", ["стардью", "stardew"]),
    (105600,  "Terraria", ["террария", "terraria"]),
    (252490,  "Rust", ["раст", "rust"]),
    (359550,  "Tom Clancy's Rainbow Six Siege", ["радуга", "осада", "r6", "siege"]),
    (230410,  "Warframe", ["варфрейм", "warframe"]),
    (440,     "Team Fortress 2", ["тф2", "tf2"]),
    (346110,  "ARK: Survival Evolved", ["арк", "ark"]),
    (250900,  "The Binding of Isaac: Rebirth", ["айзак", "isaac"]),
    (1085660, "Destiny 2", ["дестени", "destiny"]),
    (582010,  "Monster Hunter: World", ["монстер хантер", "monster hunter"]),
    (275850,  "No Man's Sky", ["ноу менс скай", "no man"]),
    (322330,  "Don't Starve Together", ["донт старв", "starve"]),
    (236390,  "War Thunder", ["вар тандер", "war thunder"]),
    (238960,  "Path of Exile", ["поэ", "path of exile"]),
    (381210,  "Dead by Daylight", ["дбд", "dbd", "dead by"]),
    (552520,  "Far Cry 5", ["фар край", "far cry"]),
    (620,     "Portal 2", ["портал", "portal"]),
    (4000,    "Garry's Mod", ["гаррис мод", "garry"]),
    (72850,   "The Elder Scrolls V: Skyrim", ["скайрим", "skyrim"]),
    (289070,  "Sid Meier's Civilization VI", ["цива", "цивилизация", "civ"]),
    (960090,  "Bloons TD 6", ["блунс", "bloons"]),
]

_FUNNY_RE = re.compile(r"смешн|угар|прикол|ржач|поржать|весел", re.I)
_RANDOM_RE = re.compile(
    r"\b(любую|любой|любое|любых|рандом|случайн|какую-нибудь|что-нибудь|какую нибудь|наугад)\b",
    re.I,
)

def detect_review_intent(text: str) -> dict | None:
    if not text:
        return None
    low = text.lower()
    if "отзыв" not in low:
        return None
    if not re.search(r"смешн|угар|прикол|ржач|поржать|весел|стим|steam|игр", low):
        return None

    cleaned = re.sub(r"\([^)]*\)", " ", low)

    excludes: list[str] = []
    for m in re.finditer(r"(?:кроме|не считая|только не|исключая)\s+([^,.;!?)]+)", low):
        ex = m.group(1).strip(" )(.,«»\"'")
        if ex:
            excludes.append(ex)

    funny = bool(_FUNNY_RE.search(low))

    game = None
    if not _RANDOM_RE.search(cleaned):
        m = re.search(r"(?:на игру|на|про|об|о)\s+([^,.;!?)]+)", cleaned)
        if m:
            cand = m.group(1)
            cand = re.sub(
                r"\b(в стиме|в стим|в steam|steam|стим|смешн\w*|угар\w*|"
                r"прикол\w*|отзыв\w*|игру|игре|игры|игра)\b",
                " ", cand,
            )
            cand = re.sub(r"\s+", " ", cand).strip(" .,«»\"'-")
            if len(cand) >= 2:
                game = cand

    return {"game": game, "excludes": excludes, "funny": funny}

@dataclass
class _RVState:
    user_id: int
    excludes: list
    funny: bool
    appid: int
    title: str
    url: str
    shown: set = field(default_factory=set)
    ts: float = field(default_factory=time.time)

_RV: dict[str, _RVState] = {}
_RV_TTL = 1800

def _gc() -> None:
    now = time.time()
    for k in [k for k, v in _RV.items() if now - v.ts > _RV_TTL]:
        _RV.pop(k, None)

def _sid(user_id: int) -> str:
    return f"{user_id}_{int(time.time() * 1000) % 1_000_000}"

def _hash(t: str) -> int:
    return hash((t or "")[:120])

def _header(appid: int) -> str:
    return ("https://cdn.cloudflare.steamstatic.com/steam/apps/"
            f"{appid}/header.jpg")

def _excluded(name: str, excludes: list[str], aliases: list[str] | None = None) -> bool:
    if not excludes:
        return False
    hay = [(name or "").lower()] + [a.lower() for a in (aliases or [])]
    for ex in excludes:
        ex = (ex or "").lower().strip()
        if len(ex) < 3:
            continue
        stem = ex[:5]
        for h in hay:
            if not h:
                continue
            if ex in h or h in ex or stem in h:
                return True
    return False

def _random_game(excludes: list[str], avoid: int | None = None):
    pool = []
    for appid, name, aliases in _POPULAR:
        if avoid and appid == avoid:
            continue
        if _excluded(name, excludes, aliases):
            continue
        pool.append((appid, name, APP_PAGE + str(appid)))
    if not pool:
        return None
    return random.choice(pool)

async def _mood(user_id: int) -> str:
    try:
        async with SessionLocal() as s:
            m = await repo.get_mood(s, user_id)
            return m.mood
    except Exception:
        return "happy"

async def _fetch_funny(appid: int, funny: bool, shown: set):
    tool = SteamReviewsTool()
    traces: list[tuple[str, dict, bool]] = []
    last_summary = None
    for lang in ("russian", "all"):
        try:
            res = await tool.run({"appid": appid, "lang": lang, "funny": True},
                                 session=None, user_id=0)
        except Exception as e:
            log.warning(f"steam_reviews {appid}/{lang} упал: {e}")
            traces.append(("steam_reviews", {"appid": appid, "lang": lang}, False))
            continue
        ok = isinstance(res, dict) and not res.get("error")
        traces.append(("steam_reviews", {"appid": appid, "lang": lang}, ok))
        if not ok:
            continue
        last_summary = res.get("summary") or last_summary
        pool = res.get("funny_reviews") or []
        if not pool and funny:
            pool = res.get("helpful_reviews") or []
        fresh = [r for r in pool if _hash(r.get("text", "")) not in shown]
        cand = fresh or pool
        if cand:
            return random.choice(cand[:3]), last_summary, traces
    return None, last_summary, traces

_INTROS: dict[str, list[str]] = {
    "playful": ["Оо, это меня уложило", "Лови, я ржала", "Ха, вот это перла", "Ну ты только глянь, я плакала", "Забирай, это золото"],
    "excited": ["Аа, смотри какой!", "Вот это топ!", "Ой всё, я в восторге", "Нашла бомбу, держи", "Как тебе такое, а?"],
    "annoyed": ["Ладно, держи", "Нашла, только не привыкай", "На, раз уж просил", "Вот, хоть посмеёшься"],
    "tired": ["Мм, вот это неплохое", "Лениво тыкнула, а тут такое", "Держи, даже меня расшевелило"],
    "sad": ["Мм, меня тоже немного развеселило", "Держи, даже я улыбнулась", "Вот, немножко отпустило"],
    "loving": ["Лови, солнышко", "Это тебе, чтоб улыбнулся", "Смотри, милый, какой угар"],
    "_": ["Глянула отзывы, вот этот топ", "Смотри, какой нашла", "Оо, вот это смешно", "Вот этот зашёл", "На, оцени", "Классный попался"],
}
_ENDINGS = ["", "", "", " 😹", " 😂", " 😅", " 🙈"]
_RECENT_INTROS: deque = deque(maxlen=10)

def _pick_intro(mood: str) -> str:
    pool = _INTROS.get(mood, []) + _INTROS["_"]
    fresh = [x for x in pool if x not in _RECENT_INTROS]
    intro = random.choice(fresh or pool)
    _RECENT_INTROS.append(intro)
    return intro + random.choice(_ENDINGS)

def _compose(mood: str, title: str, review: dict, summary: str | None) -> str:
    intro = _pick_intro(mood)
    thumb = "👍" if review.get("voted_up") else "👎"
    body = html.escape((review.get("text") or "").strip())[:900]
    meta = []
    if review.get("votes_funny"):
        meta.append(f"{review['votes_funny']} 😹")
    if review.get("playtime_h"):
        meta.append(f"{review['playtime_h']}ч в игре")
    parts = [f"{intro} <b>{html.escape(title)}</b> {thumb}", f"«{body}»"]
    tail = []
    if meta:
        tail.append(" · ".join(meta))
    if summary:
        tail.append(html.escape(summary))
    if tail:
        parts.append("<i>" + " · ".join(tail) + "</i>")
    return "\n".join(parts)

def _kb(sid: str, traces: list[tuple[str, dict, bool]]) -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton(text="🎲 Другая игра", callback_data=f"steamrv:reroll:{sid}"),
        InlineKeyboardButton(text="😹 Ещё отзыв", callback_data=f"steamrv:more:{sid}"),
    ]]
    if settings.SHOW_TOOL_CALLS and traces:
        try:
            from ai.core import ToolTrace
            from handlers.messages import _tools_keyboard
            tt = [ToolTrace(name=n, arguments=a, ok=ok,
                            summary=str(a.get("query") or a.get("appid") or "")[:30])
                  for (n, a, ok) in traces]
            tks = _tools_keyboard(tt)
            if tks:
                rows += tks.inline_keyboard
        except Exception as e:
            log.debug(f"steam_flow: кнопка тула не собралась: {e}")
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def _send_review(target: Message, sid: str, st: _RVState,
                       traces: list[tuple[str, dict, bool]]) -> None:
    rev, summary, tr2 = await _fetch_funny(st.appid, st.funny, st.shown)
    traces = list(traces) + tr2
    mood = await _mood(st.user_id)
    if not rev:
        txt = (f"Глянула отзывы на <b>{html.escape(st.title)}</b>, но смешных не нашла 😅 "
               + (html.escape(summary) if summary else "")).strip()
        await target.answer(txt, reply_markup=_kb(sid, traces),
                            disable_web_page_preview=True)
        return
    st.shown.add(_hash(rev.get("text", "")))
    text = _compose(mood, st.title, rev, summary)
    try:
        await target.answer_photo(URLInputFile(_header(st.appid)),
                                  caption=text[:1000], reply_markup=_kb(sid, traces))
    except Exception as e:
        log.debug(f"steam_flow: фото не отправилось ({e}), шлю текстом")
        await target.answer(text, reply_markup=_kb(sid, traces),
                            disable_web_page_preview=False)

async def start_review_flow(msg: Message, user_id: int, intent: dict) -> None:
    _gc()
    excludes = intent.get("excludes") or []
    funny = intent.get("funny", True)
    game = intent.get("game")
    log.info(f"🎮 steam_flow: запрос отзыва game={game!r} excludes={excludes} funny={funny}")
    await msg.answer(random.choice([
        "Секунду, гляну отзывы 👀", "О, давай! Сейчас найду что-нибудь угарное 😄",
    ]))

    appid = title = url = None
    traces: list[tuple[str, dict, bool]] = []
    if game:
        try:
            items = await steam_store_search(game)
        except Exception as e:
            log.warning(f"steam_flow: поиск '{game}' упал: {e}")
            items = []
        traces.append(("steam_search", {"query": game}, bool(items)))
        items = [it for it in items if not _excluded(it.get("title", ""), excludes)]
        if items:
            appid, title, url = items[0]["appid"], items[0]["title"], items[0]["url"]
    if not appid:
        pick = _random_game(excludes)
        if pick:
            appid, title, url = pick
    if not appid:
        await msg.answer("Хм, не нашла подходящую игру 😅 назови другую?")
        return

    sid = _sid(user_id)
    _RV[sid] = _RVState(user_id=user_id, excludes=excludes, funny=funny,
                        appid=appid, title=title, url=url)
    await _send_review(msg, sid, _RV[sid], traces)

@router.callback_query(F.data.startswith("steamrv:reroll:"))
async def cb_reroll(cb: CallbackQuery) -> None:
    sid = cb.data.split(":", 2)[2]
    st = _RV.get(sid)
    if not st:
        await cb.answer("Это уже устарело 🌸", show_alert=True)
        return
    await cb.answer("Ищу другую 🎲")
    pick = _random_game(st.excludes, avoid=st.appid)
    if not pick:
        await cb.message.answer("Больше вариантов не осталось 😅")
        return
    st.appid, st.title, st.url = pick
    st.shown = set()
    st.ts = time.time()
    await _send_review(cb.message, sid, st, [])

@router.callback_query(F.data.startswith("steamrv:more:"))
async def cb_more(cb: CallbackQuery) -> None:
    sid = cb.data.split(":", 2)[2]
    st = _RV.get(sid)
    if not st:
        await cb.answer("Это уже устарело 🌸", show_alert=True)
        return
    await cb.answer("Ща ещё гляну 😹")
    st.ts = time.time()
    await _send_review(cb.message, sid, st, [])
