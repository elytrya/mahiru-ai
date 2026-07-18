#!/usr/bin/env python3
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
    ("gpt-4o",            "тот же GPT-4o, мощнее и медленнее"),
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

def step_autonomous(data: dict) -> None:
    hr()
    p("Автономные сообщения (опционально)")
    p("")
    p("Может ли Mahiru писать первой? Интервалы в часах, можно дробные (0.5 = 30 мин).")
    on = ask_bool("Включить?", True)
    data["AUTONOMOUS_ENABLED"] = "true" if on else "false"
    if on:
        data["AUTONOMOUS_TIME_START"] = ask_number("С какого часа (0..23)", "10", "int")
        data["AUTONOMOUS_TIME_END"]   = ask_number("До какого часа (0..23)", "23", "int")
        data["AUTONOMOUS_MIN_HOURS"]  = ask_number("Мин. интервал (часы)", "3", "float")
        data["AUTONOMOUS_MAX_HOURS"]  = ask_number("Макс. интервал (часы)", "12", "float")

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
        "",
        "# ==== UI ====",
        f"TYPING_INDICATOR={g('TYPING_INDICATOR', 'true')}",
        f"SHOW_TOOL_CALLS={g('SHOW_TOOL_CALLS', 'true')}",
        "",
        "# ==== Autonomous ====",
        f"AUTONOMOUS_ENABLED={g('AUTONOMOUS_ENABLED', 'true')}",
        f"AUTONOMOUS_MIN_HOURS={g('AUTONOMOUS_MIN_HOURS', '3')}",
        f"AUTONOMOUS_MAX_HOURS={g('AUTONOMOUS_MAX_HOURS', '12')}",
        f"AUTONOMOUS_TIME_START={g('AUTONOMOUS_TIME_START', '10')}",
        f"AUTONOMOUS_TIME_END={g('AUTONOMOUS_TIME_END', '23')}",
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
    step_autonomous(data)

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
