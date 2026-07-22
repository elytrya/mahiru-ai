#!/usr/bin/env python3
"""Интерактивный мастер первичной настройки: создаёт .env, ставит зависимости, помогает с ключами."""
from __future__ import annotations
import os
import sys
import shutil
import traceback
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
ERR_LOG = ROOT / "setup_error.log"

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

USE_COLOR = os.name != "nt" and sys.stdout.isatty()
if USE_COLOR:
    C_R, C_G, C_Y = "\033[91m", "\033[92m", "\033[93m"
    C_B, C_M, C_C = "\033[94m", "\033[95m", "\033[96m"
    C_GR, C_0, C_BOLD = "\033[90m", "\033[0m", "\033[1m"
else:
    C_R = C_G = C_Y = C_B = C_M = C_C = C_GR = C_0 = C_BOLD = ""

def p(msg: str = "") -> None:
    print(msg, flush=True)

def hr(char: str = "-") -> None:
    p(char * 70)

def banner() -> None:
    p()
    p("=" * 70)
    p("   M A H I R U  -  Telegram AI Companion  -  мастер настройки")
    p("=" * 70)
    p("")
    p("Enter - принять значение в скобках. Ctrl+C - отмена.")

def _readline(prompt: str) -> str:
    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        line = sys.stdin.readline()
    except (EOFError, KeyboardInterrupt):
        raise
    except UnicodeDecodeError:
        return ""
    if not line:
        raise EOFError
    return line.rstrip("\r\n")

def ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    while True:
        try:
            v = _readline(f"? {prompt}{hint}\n> ").strip()
        except EOFError:
            v = ""
        if not v and default:
            return default
        if v:
            return v
        p("  x Нужно ввести значение.")

def ask_optional(prompt: str, default: str = "") -> str:
    hint = f" [{default or 'пусто'}]"
    try:
        v = _readline(f"? {prompt}{hint}\n> ").strip()
    except EOFError:
        v = ""
    return v or default

def ask_number(prompt: str, default: str, kind: str = "float") -> str:
    while True:
        raw = ask_optional(prompt, default)
        try:
            if kind == "int":
                int(raw)
                return raw
            float(raw.replace(",", "."))
            return raw.replace(",", ".")
        except ValueError:
            p(f"  x Нужно число ({'целое' if kind=='int' else 'можно 0.5'}).")

def ask_choice(prompt: str, options, default: str) -> str:
    p("")
    p(prompt)
    for i, (val, label) in enumerate(options, 1):
        marker = "  <- рекомендую" if val == default else ""
        p(f"  {i}) {val}{marker}\n     {label}")
    while True:
        try:
            raw = _readline(f"? Номер или имя [{default}]\n> ").strip()
        except EOFError:
            raw = ""
        if not raw:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        for val, _ in options:
            if raw.lower() == val.lower():
                return val
        p(f"  x Не поняла. Введи номер (1..{len(options)}) или имя.")

def ask_bool(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    try:
        raw = _readline(f"? {prompt} [{d}]\n> ").strip().lower()
    except EOFError:
        return default
    if not raw:
        return default
    return raw in ("y", "yes", "д", "да", "true", "1", "+")

def step_telegram(data: dict) -> None:
    hr()
    p("Шаг 1/5 - Telegram бот")
    p("")
    p("Нужно две вещи: токен бота и твой Telegram-ID.")
    p("")
    p("> Как получить BOT_TOKEN:")
    p("  1) В Telegram открой чат с @BotFather.")
    p("  2) Нажми Start, если ещё не запускал.")
    p("  3) Отправь: /newbot")
    p("  4) Имя бота (любое), напр.: Mahiru")
    p("  5) Username (должен кончаться на bot), напр.: my_mahiru_bot")
    p("  6) BotFather пришлёт строку вида:")
    p("     1234567890:AAH-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    p("")
    data["BOT_TOKEN"] = ask("Вставь BOT_TOKEN")
    p("  ok, токен записала.")

    p("")
    p("> Свой Telegram-ID:")
    p("  1) В Telegram найди @userinfobot и нажми Start - пришлёт твой ID.")
    p("     Пример: Id: 123456789  - нужны только цифры.")
    p("  2) Если админов несколько - ��ерез запятую: 123,456,789")
    p("  !  Бот будет общаться ТОЛЬКО с этими ID.")
    p("")
    data["ADMIN_IDS"] = ask("Свой Telegram-ID")

G4F_MODELS = [
    ("gpt-4o-mini",       "быстро, качественно - лучший выбор для чата"),
    ("gpt-4o",            "тот же GPT-4o, мо����ее и медленнее"),
    ("claude-3-5-sonnet", "Anthropic Claude 3.5 Sonnet"),
    ("llama-3.1-70b",     "Meta Llama 3.1 70B - open-source"),
    ("gemini-pro",        "Google Gemini Pro"),
]

G4F_PROVIDERS = [
    ("auto",           "авто (перебор рабочих: PollinationsAI, DDG, Blackbox…) — рекомендую"),
    ("PollinationsAI", "один из самых стабильных бесплатных"),
    ("Blackbox",       "быстрый, без ключей"),
    ("DDG",            "DuckDuckGo AI Chat"),
    ("Free2GPT",       "free2gpt.xyz"),
    ("Yqcloud",        "обычно стабилен, поддерживает gpt-4o-mini"),
]

def step_provider(data: dict) -> None:
    hr()
    p("Шаг 2/5 - Через какую AI Mahiru будет думать?")
    p("")
    p("Сменить потом можно в Telegram: /admin -> Провайдер.")
    provider = ask_choice(
        "Провайдер:",
        [
            ("g4f",      "БЕСПЛАТНО, без ключей (gpt4free)."),
            ("yandex",   "Yandex AI Studio (YandexGPT). Ключ с console.yandex.cloud."),
            ("gemini",   "Google Gemini. Ключ - aistudio.google.com."),
            ("openai",   "OpenAI (GPT-4o). Платный ключ с platform.openai.com."),
            ("claude",   "Anthropic Claude. Ключ с console.anthropic.com."),
            ("deepseek", "DeepSeek. Дешёвый, нужен ключ."),
            ("ollama",   "Локальные модели через Ollama."),
        ],
        default="g4f",
    )
    data["DEFAULT_PROVIDER"] = provider

    if provider == "g4f":
        data["G4F_MODEL"] = ask_choice("Какая модель?", G4F_MODELS, default="gpt-4o-mini")
        p("")
        p("Бэкэнд g4f. Совет: оставь 'auto' — бот сам отберёт рабочий")
        p("бесплатный сервис и обойдёт те, что требуют входа (OpenaiChat, Bing).")
        prov = ask_choice("Через какой бэкэнд?", G4F_PROVIDERS, default="auto")
        data["G4F_PROVIDER"] = "" if prov == "auto" else prov

    elif provider == "gemini":
        p("> Ключ - https://aistudio.google.com/apikey -> Create API key (AIza...)")
        p("")
        data["GEMINI_API_KEY"] = ask("GEMINI_API_KEY")
        data["GEMINI_MODEL"] = ask_optional("Модель", "gemini-2.0-flash")

    elif provider == "openai":
        p("> Ключ - https://platform.openai.com/api-keys")
        p("")
        data["OPENAI_API_KEY"] = ask("OPENAI_API_KEY (sk-...)")
        data["OPENAI_MODEL"] = ask_optional("Модель", "gpt-4o-mini")

    elif provider == "claude":
        p("> Ключ - https://console.anthropic.com")
        p("")
        data["ANTHROPIC_API_KEY"] = ask("ANTHROPIC_API_KEY (sk-ant-...)")
        data["CLAUDE_MODEL"] = ask_optional("Модель", "claude-3-5-sonnet-latest")

    elif provider == "deepseek":
        p("> Ключ - https://platform.deepseek.com")
        p("")
        data["DEEPSEEK_API_KEY"] = ask("DEEPSEEK_API_KEY")
        data["DEEPSEEK_MODEL"] = ask_optional("Модель", "deepseek-chat")

    elif provider == "ollama":
        p("> Ollama - https://ollama.ai. Потом: ollama pull llama3.1")
        p("")
        data["OLLAMA_HOST"] = ask_optional("Адрес Ollama", "http://localhost:11434")
        data["OLLAMA_MODEL"] = ask_optional("Имя модели", "llama3.1")

    elif provider == "yandex":
        p("> API key: https://console.yandex.cloud/folders/<folder>/service-accounts → создай СА с ролью ai.languageModels.user → API key (AQVN...)")
        p("> Folder id взять там же (b1g...) — он же project id.")
        p("> Промпт в AI Studio: https://yandex.cloud/ru/services/ai-studio — id промпта опционален.")
        p("")
        data["YANDEX_API_KEY"] = ask("YANDEX_API_KEY (AQVN...)")
        data["YANDEX_FOLDER"]  = ask("YANDEX_FOLDER (folder/project id, b1g...)")
        data["YANDEX_MODEL"]   = ask_choice(
            "Модель:",
            [
                ("yandexgpt-lite", "YandexGPT Lite — быстрая, дешёвая"),
                ("yandexgpt",      "YandexGPT Pro — лучше качество"),
                ("llama-8b",       "Llama 3.1 8B (сборка Yandex)"),
                ("llama-70b",      "Llama 3.1 70B (сборка Yandex)"),
            ],
            default="yandexgpt-lite",
        )
        pid = ask_optional("YANDEX_PROMPT_ID (опц, пусто = игнор)", "")
        if pid:
            data["YANDEX_PROMPT_ID"] = pid

def step_db(data: dict) -> None:
    hr()
    p("Шаг 3/5 - Где хранить данные?")
    p("")
    p("База хранит личность, диалоги и факты.")
    p("(Redis не нужен — кэш автоматически в памяти, если не настроен.)")
    choice = ask_choice(
        "База данных:",
        [
            ("sqlite",   "Файл mahiru.db в папке проекта. Ничего ставить не надо."),
            ("postgres", "PostgreSQL (docker или отдельная база)."),
            ("custom",   "Ввести DATABASE_URL вручную."),
        ],
        default="sqlite",
    )
    if choice == "sqlite":
        data["DATABASE_URL"] = "sqlite+aiosqlite:///./mahiru.db"
    elif choice == "postgres":
        data["DATABASE_URL"] = ask_optional(
            "DATABASE_URL", "postgresql+asyncpg://mahiru:mahiru@localhost:5432/mahiru"
        )
    else:
        data["DATABASE_URL"] = ask("DATABASE_URL")

    p("")
    p("(если у тебя НЕТ Redis — скипай Enter’ом, всё будет в памяти)")
    data["REDIS_URL"] = ask_optional("REDIS_URL (пусто = в памяти)", "")

def step_google(data: dict) -> None:
    hr()
    p("Шаг 4/5 - Дополнительные интеграции (все опциональны)")
    p("")
    p("[A] Поиск в интернете — по умолчанию через DuckDuckGo (бесплатно, БЕЗ КЛЮЧА).")
    p("    Google Custom Search настраивать НЕ обязательно — можно пропустить.")
    p("    Если хочешь: https://console.cloud.google.com/apis/credentials")
    p("")
    key = ask_optional("GOOGLE_API_KEY (пусто = пропустить)", "")
    if key:
        data["GOOGLE_API_KEY"] = key
        data["GOOGLE_CX"] = ask("GOOGLE_CX (Search engine ID)")

    p("")
    p("[B] MangaLib / RanobeLib / HentaiLib — поиск и скачивание манги/ранобэ.")
    p("    Публичный поиск работает БЕЗ токена. Токен нужен только для 18+/скрытых тайтлов.")
    p("    Аккаунт ОДИН на все три сайта — достаточно ОДНОГО токена.")
    p("    Как взять: открой mangalib.me → F12 → Application → Local Storage → auth → token.")
    p("    Токен можно ввести позже прямо в Telegram: /setkey LIB_TOKEN <твой_токен>.")
    p("")
    tok = ask_optional("LIB_TOKEN (общий для manga/ranobe/hentai — пусто = пропустить)", "")
    if tok:
        data["LIB_TOKEN"] = tok

    p("")
    p("[C] Погода-забота (OpenWeather) - Махиру сама напишет «там у тебя дождь, возьми зонт».")
    p("    Бесплатный ключ: https://openweathermap.org/api -> Sign up -> API keys.")
    p("    Ключ можно ввести позже в Telegram: /weather key <ключ>.")
    p("")
    wkey = ask_optional("OPENWEATHER_API_KEY (пусто = пропустить)", "")
    if wkey:
        data["OPENWEATHER_API_KEY"] = wkey
        data["WEATHER_CITY"] = ask("В каком городе ты живёшь? (напр. Москва)")
        data["WEATHER_ENABLED"] = "true"
        p("")
        p("    Про погоду она вспоминает САМА, когда захочет — без часов и расписания.")
    else:
        data["WEATHER_ENABLED"] = "false"

def step_ui(data: dict) -> None:
    hr()
    p("Шаг 5/5 - Поведение в Telegram")
    p("")
    p("1) Показывать 'печатает…' пока бот думает — чтоб выглядело живо.")
    data["TYPING_INDICATOR"] = "true" if ask_bool("Включить 'печатает…'?", True) else "false"
    p("")
    p("2) Показывать кнопки под ответом, если бот чем-то пользовался")
    p("   (ПОИСК в Гугле, ПОИСК аниме, СОХРАНИЛ в память и т.д.).")
    p("   Клик по кнопке покажет что именно искали.")
    data["SHOW_TOOL_CALLS"] = "true" if ask_bool("Включить кнопки тулов?", True) else "false"

def step_human(data: dict) -> None:
    hr()
    p("Очеловечивание - чтоб она вела себя как живая девушка 🌸")
    p("(всё это потом можно менять в /admin -> Человечность или /humanset)")
    p("")
    p("1) Заменять длинное тире '—' на обычный дефис '-'.")
    data["NO_EMDASH"] = "true" if ask_bool("Заменять тире на -?", True) else "false"
    p("")
    p("2) Имитация набора: паузы + 'печатает…' перед ответом, отвечает не мгновенно.")
    hum = ask_bool("Включить имитацию набора?", True)
    data["HUMAN_TYPING"] = "true" if hum else "false"
    if hum:
        data["TYPING_SPEED_CPS"] = ask_number("Скорость набора (симв/сек, меньше = дольше печатает)", "14", "float")
        p("")
        p("3) Разбивать длинный ответ на нескольк���� сообщений (как живой ч��ловек).")
        data["SPLIT_MESSAGES"] = "true" if ask_bool("Разбивать на сообщения?", True) else "false"
        p("")
        p("4) Иногда 'занята' и отвечает заметно позже (шанс 0..1, напр. 0.12 = 12%).")
        data["IGNORE_CHANCE"] = ask_number("Шанс 'занята' (0 = никогда)", "0.12", "float")
    else:
        data["SPLIT_MESSAGES"] = "false"

    p("")
    p("5) Эмодзи-реакции: иногда ставит реакцию (❤, 😂...) вместо/перед ответом.")
    react = ask_bool("Включить эмодзи-реакции?", True)
    data["REACTIONS_ENABLED"] = "true" if react else "false"
    if react:
        data["REACTION_CHANCE"] = ask_number("Шанс реакции (0..1)", "0.25", "float")
    p("")
    p("6) Опечатки с самоисправлением: иногда опечатается, потом '*то есть ...'.")
    typo = ask_bool("Включить опечатки?", True)
    data["TYPO_ENABLED"] = "true" if typo else "false"
    if typo:
        data["TYPO_CHANCE"] = ask_number("Шанс опечатки (0..1)", "0.12", "float")
    p("")
    p("7) Настроение влияет на скорость: злая - медленнее/резче, влюблённая - быстрее/теплее.")
    data["MOOD_SPEED_ENABLED"] = "true" if ask_bool("Включить влияние настроения?", True) else "false"
    p("")
    p("8) 'Прочитала, но молчит': иногда молчит пару минут, потом пишет.")
    rs = ask_bool("Включить 'прочитала, молчит'?", True)
    data["READ_SILENCE_ENABLED"] = "true" if rs else "false"
    if rs:
        data["READ_SILENCE_CHANCE"] = ask_number("Шанс (0..1)", "0.07", "float")
    p("")
    p("9) Стикеры/кастом-эмодзи по настроению (потом /sticker для набора).")
    stick = ask_bool("Включить стикеры?", True)
    data["STICKERS_ENABLED"] = "true" if stick else "false"
    if stick:
        data["STICKER_CHANCE"] = ask_number("Шанс стикера (0..1)", "0.15", "float")
        data["STICKER_IDS_DEFAULT"] = ask_optional(
            "ID кастом-эмодзи/стикеров через запятую (можно пусто)",
            "6365185259734040633")
    p("")
    p("10) Памятные даты: сама поздравляет с годовщинами/др (потом /date).")
    dts = ask_bool("Включить памятные даты?", True)
    data["DATES_ENABLED"] = "true" if dts else "false"
    if dts:
        p("")
        p("   В свой день она сама поздравит, когда захочет — без фиксированного часа.")

def step_autonomous(data: dict) -> None:
    hr()
    p("Инициатива: она САМА решает, когда писать первой (опционально)")
    p("")
    p("Может ли Mahiru писать первой? НИКАКИХ окон по часам, шансов и лимитов.")
    p("Она смотрит на контекст (сколько прошло, о чём говорили) и сама решает:")
    p("хочет — напишет, не хочет — промолчит.")
    on = ask_bool("Включить?", True)
    data["AUTONOMOUS_ENABLED"] = "true" if on else "false"
    if on:
        p("")
        p("Как часто она получает 'возможность' проявить инициативу (минуты).")
        data["INITIATIVE_TICK_MINUTES"] = ask_number("Проверять каждые (мин)", "20", "int")
        p("")
        p("Мягкий предохранитель от спама: не писать по своей инициативе чаще, чем раз в N мин.")
        p("(Это НЕ расписание и НЕ шанс — просто чтоб не заваливала подряд.)")
        data["INITIATIVE_MIN_GAP_MINUTES"] = ask_number("Мин. пауза между её инициативами (мин)", "40", "int")

def step_screen(data: dict) -> None:
    hr()
    p("Смотрит на экран 👀 (опционально)")
    p("")
    p("Махиру САМА, когда захочет (по контексту), заглядывает на твой экран и живо")
    p("комментирует: 'опять в доту залип?', 'что за аниме смотришь?'.")
    p("НИКАКИХ окон по часам и лимитов — только её желание.")
    p("Также ты сам можешь написать ей 'глянь на экран' — и она посмотрит.")
    p("Скриншот уходит в vision-модель (gemini, openai gpt-4o, g4f с vision и т.п.).")
    p("ВАЖНО: снимок делается на том компьютере, где ЗАПУЩЕН бот - он видит")
    p("именно ЭТОТ экран. На сервере без монитора работать не будет.")
    p("")
    on = ask_bool("Включить подглядывание за экраном?", False)
    data["SCREEN_WATCH_ENABLED"] = "true" if on else "false"
    if not on:
        return
    p("")
    p("Какой монитор снимать? 0 = все сразу, 1 = первый, 2 = второй...")
    data["SCREEN_WATCH_MONITOR"] = ask_number("Номер монитора", "0", "int")
    # Быстрая проверка: получится ли снять экран прямо сейчас
    try:
        sys.path.insert(0, str(ROOT))
        from utils.screen import screen_available
        if screen_available():
            p("  ok, экран вижу - тестовый скриншот получился ✅")
        else:
            p("  ! не смогла снять экран сейчас (нет граф. среды/прав или не установлен mss).")
            p("    Если это твой ПК - скорее всего заработает после установки зависимостей.")
    except Exception as e:
        p(f"  (проверку экрана пропускаю: {e})")

def save_env(data) -> None:
    def g(k, d=""): return data.get(k, d)
    lines = [
        "# Сгенерировано setup_wizard.py",
        "",
        "# ==== Telegram ====",
        f"BOT_TOKEN={g('BOT_TOKEN')}",
        f"ADMIN_IDS={g('ADMIN_IDS')}",
        "",
        "# ==== DB / cache ====",
        f"DATABASE_URL={g('DATABASE_URL', 'sqlite+aiosqlite:///./mahiru.db')}",
        f"REDIS_URL={g('REDIS_URL', '')}",
        "",
        "# ==== AI ====",
        f"DEFAULT_PROVIDER={g('DEFAULT_PROVIDER', 'g4f')}",
        f"GEMINI_API_KEY={g('GEMINI_API_KEY')}",
        f"GEMINI_MODEL={g('GEMINI_MODEL', 'gemini-2.0-flash')}",
        f"OPENAI_API_KEY={g('OPENAI_API_KEY')}",
        f"OPENAI_MODEL={g('OPENAI_MODEL', 'gpt-4o-mini')}",
        f"ANTHROPIC_API_KEY={g('ANTHROPIC_API_KEY')}",
        f"CLAUDE_MODEL={g('CLAUDE_MODEL', 'claude-3-5-sonnet-latest')}",
        f"DEEPSEEK_API_KEY={g('DEEPSEEK_API_KEY')}",
        f"DEEPSEEK_MODEL={g('DEEPSEEK_MODEL', 'deepseek-chat')}",
        f"OLLAMA_HOST={g('OLLAMA_HOST', 'http://localhost:11434')}",
        f"OLLAMA_MODEL={g('OLLAMA_MODEL', 'llama3.1')}",
        f"G4F_MODEL={g('G4F_MODEL', 'gpt-4o-mini')}",
        f"G4F_PROVIDER={g('G4F_PROVIDER')}",
        f"YANDEX_API_KEY={g('YANDEX_API_KEY')}",
        f"YANDEX_FOLDER={g('YANDEX_FOLDER')}",
        f"YANDEX_MODEL={g('YANDEX_MODEL', 'yandexgpt-lite')}",
        f"YANDEX_PROMPT_ID={g('YANDEX_PROMPT_ID')}",
        "",
        "# ==== Tools ====",
        f"GOOGLE_API_KEY={g('GOOGLE_API_KEY')}",
        f"GOOGLE_CX={g('GOOGLE_CX')}",
        f"LIB_TOKEN={g('LIB_TOKEN')}",
        f"OPENWEATHER_API_KEY={g('OPENWEATHER_API_KEY')}",
        "",
        "# ==== Погода-забота (OpenWeather) ====",
        f"WEATHER_ENABLED={g('WEATHER_ENABLED', 'true')}",
        f"WEATHER_CITY={g('WEATHER_CITY', '')}",
        f"WEATHER_UNITS={g('WEATHER_UNITS', 'metric')}",
        f"WEATHER_LANG={g('WEATHER_LANG', 'ru')}",
        "",
        "# ==== Характер: ревность / энергия / близость / пет-неймы ====",
        f"JEALOUSY_ENABLED={g('JEALOUSY_ENABLED', 'true')}",
        f"JEALOUSY_HOURS={g('JEALOUSY_HOURS', '12')}",
        f"ENERGY_ENABLED={g('ENERGY_ENABLED', 'true')}",
        f"CLOSENESS_ENABLED={g('CLOSENESS_ENABLED', 'true')}",
        f"CLOSENESS_PER_MSG={g('CLOSENESS_PER_MSG', '1')}",
        f"PETNAMES_ENABLED={g('PETNAMES_ENABLED', 'true')}",
        f"PETNAME_THRESHOLD={g('PETNAME_THRESHOLD', '30')}",
        "",
        "# ==== UI ====",
        f"TYPING_INDICATOR={g('TYPING_INDICATOR', 'true')}",
        f"SHOW_TOOL_CALLS={g('SHOW_TOOL_CALLS', 'true')}",
        "",
        "# ==== Очеловечивание ====",
        f"NO_EMDASH={g('NO_EMDASH', 'true')}",
        f"HUMAN_TYPING={g('HUMAN_TYPING', 'true')}",
        f"TYPING_SPEED_CPS={g('TYPING_SPEED_CPS', '14')}",
        f"SPLIT_MESSAGES={g('SPLIT_MESSAGES', 'true')}",
        f"IGNORE_CHANCE={g('IGNORE_CHANCE', '0.12')}",
        "",
        "# ==== Живые реакции / опечатки / настроение ====",
        f"REACTIONS_ENABLED={g('REACTIONS_ENABLED', 'true')}",
        f"REACTION_CHANCE={g('REACTION_CHANCE', '0.25')}",
        f"TYPO_ENABLED={g('TYPO_ENABLED', 'true')}",
        f"TYPO_CHANCE={g('TYPO_CHANCE', '0.12')}",
        f"MOOD_SPEED_ENABLED={g('MOOD_SPEED_ENABLED', 'true')}",
        f"READ_SILENCE_ENABLED={g('READ_SILENCE_ENABLED', 'true')}",
        f"READ_SILENCE_CHANCE={g('READ_SILENCE_CHANCE', '0.07')}",
        f"READ_SILENCE_MIN_SECONDS={g('READ_SILENCE_MIN_SECONDS', '45')}",
        f"READ_SILENCE_MAX_SECONDS={g('READ_SILENCE_MAX_SECONDS', '150')}",
        "",
        "# ==== Стикеры / памятные даты ====",
        f"STICKERS_ENABLED={g('STICKERS_ENABLED', 'true')}",
        f"STICKER_CHANCE={g('STICKER_CHANCE', '0.15')}",
        f"STICKER_IDS_DEFAULT={g('STICKER_IDS_DEFAULT', '6365185259734040633')}",
        f"DATES_ENABLED={g('DATES_ENABLED', 'true')}",
        "",
        "# ==== Инициатива: она САМА решает, когда писать / глянуть на экран ====",
        "# БОЛЬШЕ НЕТ окон по часам, шансов и лимитов «N раз в день».",
        f"AUTONOMOUS_ENABLED={g('AUTONOMOUS_ENABLED', 'true')}",
        f"INITIATIVE_TICK_MINUTES={g('INITIATIVE_TICK_MINUTES', '20')}",
        f"INITIATIVE_MIN_GAP_MINUTES={g('INITIATIVE_MIN_GAP_MINUTES', '40')}",
        "",
        "# ==== Смотрит на экран (screen watch) — когда смотреть, решает сама ====",
        f"SCREEN_WATCH_ENABLED={g('SCREEN_WATCH_ENABLED', 'false')}",
        f"SCREEN_WATCH_MONITOR={g('SCREEN_WATCH_MONITOR', '0')}",
        f"SCREEN_WATCH_MAX_WIDTH={g('SCREEN_WATCH_MAX_WIDTH', '1280')}",
        f"SCREEN_WATCH_JPEG_QUALITY={g('SCREEN_WATCH_JPEG_QUALITY', '70')}",
        "",
        f"LOG_LEVEL={g('LOG_LEVEL', 'INFO')}",
        "",
    ]
    ENV_PATH.write_text("\n".join(lines), encoding="utf-8")

def step_install() -> bool:
    hr()
    p("Устанавливаю зависимости...")
    p("")
    cmd = [sys.executable, "-m", "pip", "install", "-U", "-r", "requirements.txt"]
    p(f"$ {' '.join(cmd)}")
    p("")
    try:
        rc = subprocess.call(cmd, cwd=str(ROOT))
    except Exception as e:
        p(f"  x Не смогла запустить pip: {e}")
        return False
    if rc == 0:
        p("")
        p("OK. Зависимости установлены.")
        return True
    p("")
    p(f"  x pip install упал ({rc}). Запусти вручную: pip install -r requirements.txt")
    return False

def finale() -> None:
    hr()
    p("ГОТОВО. Теперь запусти бота командой:")
    p("")
    p("    python bot.py")
    p("")
    p("Потом в Telegram напиши своему боту /start.")

def main() -> None:
    banner()
    if ENV_PATH.exists():
        try:
            bak = ROOT / ".env.bak"
            shutil.copy2(ENV_PATH, bak)
            p(f"(старый .env сохранён как {bak.name})")
        except Exception:
            pass

    data: dict = {}
    step_telegram(data)
    step_provider(data)
    step_db(data)
    step_google(data)
    step_ui(data)
    step_human(data)
    step_autonomous(data)
    step_screen(data)

    save_env(data)
    p("")
    p(f"OK. Конфиг сохранён: {ENV_PATH}")
    step_install()
    finale()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        p("")
        p("Отменено пользователем.")
    except SystemExit:
        raise
    except BaseException as e:
        tb = traceback.format_exc()
        try:
            ERR_LOG.write_text(tb, encoding="utf-8")
        except Exception:
            pass
        p("")
        p("=" * 70)
        p("! Произошла ошибка:")
        p(tb)
        p(f"! Лог сохранён в: {ERR_LOG}")
        p("=" * 70)
        sys.exit(1)
