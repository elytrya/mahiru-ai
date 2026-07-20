"""Очеловечивание Mahiru: тире, «печатает…», случайные паузы, разбивка на сообщения.

Всё поведение крутится настройками из config.settings (их можно менять из
/admin -> Человечность, командой /humanset и в setup_wizard.py).
"""
from __future__ import annotations
import asyncio
import random
import re

from config import settings

# ── тире ──────────────────────────────────────────────────────────────────
# длинное тире «—», среднее «–», горизонтальная черта «―», минус «−»
_DASH_RE = re.compile(r"[\u2014\u2013\u2015\u2212]")

def dedash(text: str) -> str:
    """Заменяет любые длинные тире на обычный дефис '-'. Управляется NO_EMDASH."""
    if not text:
        return text
    if not getattr(settings, "NO_EMDASH", True):
        return text
    return _DASH_RE.sub("-", text)

# ── задержки ──────────────────────────────────────────────────────────────
def _rand(a: float, b: float) -> float:
    lo, hi = (a, b) if a <= b else (b, a)
    return random.uniform(lo, hi)

# множители скорости по настроению: (печать, пауза «заметила»)
# >1 = медленнее/холоднее, <1 = быстрее/теплее
MOOD_SPEED = {
    "annoyed": (1.35, 1.5),
    "sad":     (1.25, 1.4),
    "tired":   (1.4, 1.6),
    "curious": (1.0, 1.0),
    "happy":   (0.85, 0.8),
    "playful": (0.8, 0.7),
    "excited": (0.7, 0.6),
    "loving":  (0.8, 0.75),
}

def _mood_mult(mood: str | None) -> tuple[float, float]:
    if not mood or not getattr(settings, "MOOD_SPEED_ENABLED", True):
        return 1.0, 1.0
    return MOOD_SPEED.get(mood, (1.0, 1.0))

def read_delay(mood: str | None = None) -> float:
    """Пауза «заметила сообщение» перед тем как начать печатать."""
    base = _rand(
        float(getattr(settings, "READ_DELAY_MIN", 0.5)),
        float(getattr(settings, "READ_DELAY_MAX", 3.0)),
    )
    return base * _mood_mult(mood)[1]

def maybe_ignore_delay() -> float:
    """С шансом IGNORE_CHANCE она «занята» и отвечает не сразу. Возвращает доп. паузу."""
    chance = float(getattr(settings, "IGNORE_CHANCE", 0.0))
    if chance > 0 and random.random() < chance:
        return _rand(
            float(getattr(settings, "IGNORE_MIN_SECONDS", 8.0)),
            float(getattr(settings, "IGNORE_MAX_SECONDS", 40.0)),
        )
    return 0.0

def typing_delay(text: str, mood: str | None = None) -> float:
    """Сколько «печатать» сообщение — зависит от длины, настроения + чуть рандома."""
    n = len(text or "")
    cps = float(getattr(settings, "TYPING_SPEED_CPS", 14.0)) or 14.0
    base = n / cps
    base *= random.uniform(0.8, 1.25)  # живой разброс
    base *= _mood_mult(mood)[0]        # настроение: злая печатает дольше
    lo = float(getattr(settings, "TYPING_MIN_SECONDS", 1.2))
    hi = float(getattr(settings, "TYPING_MAX_SECONDS", 9.0))
    return max(lo, min(hi, base))

# ── разбивка ответа на несколько «пузырей» ────────────────────────────────
_SENT_SPLIT = re.compile(r"(?<=[.!?…)])\s+")

def _looks_html_safe(chunk: str) -> bool:
    # не режем так, чтобы разорвать html-тег (у бота parse_mode=HTML)
    return chunk.count("<") == chunk.count(">")

def split_message(text: str) -> list[str]:
    """Бьёт длинный ответ на 1..SPLIT_MAX коротких сообщений, как живой человек.

    Сначала по переносам строк, потом длинные куски — по предложениям.
    Не разрывает html-теги.
    """
    text = (text or "").strip()
    if not text:
        return []
    if not getattr(settings, "SPLIT_MESSAGES", False):
        return [text]

    max_parts = int(getattr(settings, "SPLIT_MAX", 3)) or 1
    if max_parts <= 1 or len(text) < 90:
        return [text]

    # 1) по строкам
    parts = [ln.strip() for ln in text.split("\n") if ln.strip()]

    # 2) если строк мало, а текст длинный — доразбиваем по предложениям
    if len(parts) < max_parts:
        expanded: list[str] = []
        for pt in parts:
            if len(pt) > 140:
                expanded.extend(s.strip() for s in _SENT_SPLIT.split(pt) if s.strip())
            else:
                expanded.append(pt)
        parts = expanded

    if not parts:
        return [text]

    # 3) схлопываем до max_parts, склеивая хвост
    if len(parts) > max_parts:
        head = parts[: max_parts - 1]
        tail = " ".join(parts[max_parts - 1 :])
        parts = head + [tail]

    # 4) чиним возможные разорванные html-теги, склеивая соседей
    fixed: list[str] = []
    for pt in parts:
        if fixed and not _looks_html_safe(fixed[-1]):
            fixed[-1] = (fixed[-1] + " " + pt).strip()
        else:
            fixed.append(pt)
    return fixed or [text]


# ── реакции-эмодзи на сообщения ─────────────────────────────────────
# только эмодзи из стандартного набора Telegram-реакций (без премиума)
REACTION_SETS = {
    "happy":   ["\u2764", "\U0001f970", "\U0001f601", "\U0001f44d", "\U0001f389"],
    "loving":  ["\u2764", "\U0001f970", "\U0001f60d", "\U0001f618"],
    "playful": ["\U0001f601", "\U0001f923", "\U0001f608", "\U0001f92a", "\U0001f60e"],
    "excited": ["\U0001f525", "\U0001f389", "\U0001f929", "\U0001f4af", "\U0001f44f"],
    "curious": ["\U0001f914", "\U0001f440", "\U0001f928"],
    "annoyed": ["\U0001f610", "\U0001f928", "\U0001f621"],
    "sad":     ["\U0001f622", "\U0001f62d", "\U0001f494"],
    "tired":   ["\U0001f971", "\U0001f634", "\U0001f610"],
}
_REACTION_DEFAULT = ["\U0001f44d", "\u2764", "\U0001f525", "\U0001f601", "\U0001f914"]

def pick_reaction(mood: str | None = None) -> str:
    pool = REACTION_SETS.get(mood or "", _REACTION_DEFAULT) or _REACTION_DEFAULT
    return random.choice(pool)

async def maybe_react(msg, mood: str | None = None) -> bool:
    """С шансом REACTION_CHANCE ставит эмодзи-реакцию на входящее сообщение."""
    if not getattr(settings, "REACTIONS_ENABLED", False):
        return False
    chance = float(getattr(settings, "REACTION_CHANCE", 0.0))
    if chance <= 0 or random.random() >= chance:
        return False
    try:
        from aiogram.types import ReactionTypeEmoji
        await msg.react([ReactionTypeEmoji(emoji=pick_reaction(mood))])
        return True
    except Exception:
        return False

# ── опечатки с самоисправлением ─────────────────────────────────
_WORD_RE = re.compile(r"[\u0410-\u042f\u0430-\u044f\u0401\u0451A-Za-z]{4,}")

def _make_typo(word: str) -> str:
    if len(word) < 4:
        return word
    i = random.randint(1, len(word) - 2)  # не трогаем первую букву
    chars = list(word)
    chars[i], chars[i + 1] = chars[i + 1], chars[i]  # переставляем две соседние
    return "".join(chars)

def _maybe_typo(chunk: str) -> tuple[str, str | None]:
    """Иногда возвращает (текст_с_опечаткой, "*правильное_слово"). Иначе (чанк, None)."""
    if not getattr(settings, "TYPO_ENABLED", False):
        return chunk, None
    chance = float(getattr(settings, "TYPO_CHANCE", 0.0))
    if chance <= 0 or random.random() >= chance:
        return chunk, None
    # не трогаем сообщения с html/ссылками, чтоб не поломать разметку
    if "<" in chunk or ">" in chunk or "http" in chunk or "`" in chunk:
        return chunk, None
    words = [m for m in _WORD_RE.finditer(chunk) if len(m.group()) >= 4]
    if not words:
        return chunk, None
    m = random.choice(words)
    word = m.group()
    typo = _make_typo(word)
    if typo == word:
        return chunk, None
    typo_chunk = chunk[: m.start()] + typo + chunk[m.end():]
    return typo_chunk, "*" + word

# ── «прочитала, но не ответила» + стикеры ────────────────────────
async def _maybe_read_silence(msg) -> None:
    if not getattr(settings, "READ_SILENCE_ENABLED", False):
        return
    chance = float(getattr(settings, "READ_SILENCE_CHANCE", 0.0))
    if chance <= 0 or random.random() >= chance:
        return
    from aiogram.utils.chat_action import ChatActionSender
    try:
        # мелькнуло «печатает…» - будто увидела и начала отвечать
        async with ChatActionSender.typing(bot=msg.bot, chat_id=msg.chat.id):
            await asyncio.sleep(_rand(1.0, 2.5))
    except Exception:
        pass
    # ...и пропала на пару минут
    await asyncio.sleep(_rand(
        float(getattr(settings, "READ_SILENCE_MIN_SECONDS", 45.0)),
        float(getattr(settings, "READ_SILENCE_MAX_SECONDS", 150.0)),
    ))

async def _maybe_send_sticker(msg, mood: str | None) -> None:
    if not getattr(settings, "STICKERS_ENABLED", False):
        return
    chance = float(getattr(settings, "STICKER_CHANCE", 0.0))
    if chance <= 0 or random.random() >= chance:
        return
    try:
        from utils import stickers
        await stickers.send(msg, mood)
    except Exception:
        pass


async def send_humanlike(msg, text: str, reply_markup=None,
                         disable_web_page_preview: bool = False,
                         mood: str | None = None) -> None:
    """Отправляет ответ «по-живому»: паузы + «печатает…» + разбивка + опечатки + стикеры.

    msg — aiogram Message. reply_markup вешается только на ПОСЛЕДНЕЕ сообщение.
    mood — текущее настроение (влияет на скорость и выбор стикера).
    Если HUMAN_TYPING выключен — просто отправляет одним сообщением сразу.
    """
    from aiogram.utils.chat_action import ChatActionSender

    text = dedash((text or "").strip())
    if not text:
        return

    if not getattr(settings, "HUMAN_TYPING", False):
        await msg.answer(text, reply_markup=reply_markup,
                         disable_web_page_preview=disable_web_page_preview)
        await _maybe_send_sticker(msg, mood)
        return

    chunks = split_message(text)
    last = len(chunks) - 1

    # «занята» — иногда отвечает заметно позже
    ignore = maybe_ignore_delay()
    if ignore > 0:
        await asyncio.sleep(ignore)

    # «прочитала, но не ответила» — мелькнула «печатает…», пропала на пару минут
    await _maybe_read_silence(msg)

    for i, chunk in enumerate(chunks):
        # пауза «читаю/думаю» перед первым, короткая пауза между пузырями
        pre = read_delay(mood) if i == 0 else _rand(0.3, 1.1) * _mood_mult(mood)[1]
        if pre > 0:
            await asyncio.sleep(pre)
        # иногда пишет с опечаткой и тут же поправляется
        send_text, correction = _maybe_typo(chunk)
        try:
            async with ChatActionSender.typing(bot=msg.bot, chat_id=msg.chat.id):
                await asyncio.sleep(typing_delay(send_text, mood))
        except Exception:
            # если индикатор не смог — просто ждём, ответ всё равно уйдёт
            await asyncio.sleep(min(2.0, typing_delay(send_text, mood)))
        await msg.answer(
            send_text,
            reply_markup=(reply_markup if (i == last and not correction) else None),
            disable_web_page_preview=disable_web_page_preview,
        )
        if correction:
            await asyncio.sleep(_rand(0.6, 1.8))
            try:
                async with ChatActionSender.typing(bot=msg.bot, chat_id=msg.chat.id):
                    await asyncio.sleep(_rand(0.5, 1.2))
            except Exception:
                await asyncio.sleep(0.6)
            await msg.answer(
                correction,
                reply_markup=(reply_markup if i == last else None),
                disable_web_page_preview=disable_web_page_preview,
            )

    # иногда докидывает стикер/гифку под настроение
    await _maybe_send_sticker(msg, mood)
