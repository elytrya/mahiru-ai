"""Настройки бота (pydantic Settings): токены, провайдеры, поведение, голос, стикеры и пр., читаются из .env."""
from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    BOT_TOKEN: str = ""
    ADMIN_IDS: str = ""
    TELEGRAM_PROXY: str | None = None
    TELEGRAM_TIMEOUT: int = 60

    DATABASE_URL: str = "sqlite+aiosqlite:///./mahiru.db"
    REDIS_URL: str = ""

    DEFAULT_PROVIDER: str = "g4f"
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-2.0-flash"
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    ANTHROPIC_API_KEY: str | None = None
    CLAUDE_MODEL: str = "claude-3-5-sonnet-latest"
    DEEPSEEK_API_KEY: str | None = None
    DEEPSEEK_MODEL: str = "deepseek-chat"
    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:3b"
    OLLAMA_AUTO_INSTALL: bool = True
    OLLAMA_AUTO_START: bool = True
    OLLAMA_AUTO_PULL: bool = True

    YANDEX_API_KEY: str | None = None
    YANDEX_FOLDER: str | None = None
    YANDEX_MODEL: str = "yandexgpt-lite"
    YANDEX_PROMPT_ID: str | None = None

    G4F_MODEL: str = "deepseek-v3"
    G4F_PROVIDER: str | None = None

    GOOGLE_API_KEY: str | None = None
    GOOGLE_CX: str | None = None
    STEAM_API_KEY: str | None = None
    MANGALIB_TOKEN: str | None = None
    HENTAILIB_TOKEN: str | None = None
    RANOBELIB_TOKEN: str | None = None

    MANGADEX_LANG: str = "ru"
    DOWNLOAD_DIR: str = "./downloads"

    # ==== Инициатива: Махиру САМА решает, когда написать / глянуть на экран ====
    # БОЛЬШЕ НЕТ окон по часам, НЕТ «шансов» и НЕТ лимита «N раз в день».
    # Каждые INITIATIVE_TICK_MINUTES минут она смотрит на контекст (сколько
    # прошло времени, о чём говорили, её настроение) и САМА решает: хочет —
    # напишет или глянет на экран, не хочет — промолчит.
    AUTONOMOUS_ENABLED: bool = True
    # Как часто она получает «возможность» проявить инициативу (минуты).
    INITIATIVE_TICK_MINUTES: int = 20
    # Мягкий предохранитель от спама: не проявлять инициативу чаще, чем раз в N минут.
    # Это НЕ расписание и НЕ шанс — просто чтоб не заваливала сообщениями подряд.
    INITIATIVE_MIN_GAP_MINUTES: int = 40

    # ==== Смотрит на экран (screen watch) ====
    # Махиру САМА, когда захочет (по контексту), заглядывает тебе на экран и живо
    # комментирует. Никаких окон по часам и лимитов — только её желание.
    # Также ты сам можешь попросить её «глянь на экран» прямо в чате.
    # Работает на машине, где запущен бот. Нужен провайдер с vision.
    SCREEN_WATCH_ENABLED: bool = False
    # Какой монитор снимать: 0 = все сразу, 1 = первый, 2 = второй...
    SCREEN_WATCH_MONITOR: int = 0
    # Скриншот ужимается до этой ширины перед отправкой в vision-модель
    SCREEN_WATCH_MAX_WIDTH: int = 1280
    SCREEN_WATCH_JPEG_QUALITY: int = 70

    TYPING_INDICATOR: bool = True
    SHOW_TOOL_CALLS: bool = True

    NO_EMDASH: bool = True
    HUMAN_TYPING: bool = True
    TYPING_SPEED_CPS: float = 14.0
    TYPING_MIN_SECONDS: float = 1.2
    TYPING_MAX_SECONDS: float = 9.0
    READ_DELAY_MIN: float = 0.5
    READ_DELAY_MAX: float = 3.0
    IGNORE_CHANCE: float = 0.12
    IGNORE_MIN_SECONDS: float = 8.0
    IGNORE_MAX_SECONDS: float = 40.0
    SPLIT_MESSAGES: bool = True
    SPLIT_MAX: int = 3

    REACTIONS_ENABLED: bool = True
    REACTION_CHANCE: float = 0.25
    TYPO_ENABLED: bool = True
    TYPO_CHANCE: float = 0.12
    TYPO_EDIT_FIX: bool = True
    TYPO_EDIT_CHANCE: float = 0.6
    MOOD_SPEED_ENABLED: bool = True
    READ_SILENCE_ENABLED: bool = True
    READ_SILENCE_CHANCE: float = 0.07
    READ_SILENCE_MIN_SECONDS: float = 45.0
    READ_SILENCE_MAX_SECONDS: float = 150.0
    STICKERS_ENABLED: bool = True
    STICKER_CHANCE: float = 0.10
    STICKER_COOLDOWN_SECONDS: int = 240
    STICKER_EMOJI_FALLBACK: bool = True
    SULK_ENABLED: bool = True
    SULK_MAX_HOURS: float = 24.0
    SULK_CLOSENESS_PENALTY: int = 3
    VOICE_ENABLED: bool = False
    VOICE_CHANCE: float = 0.12
    VOICE_SPEAKER: str = "xenia"
    VOICE_MODEL_ID: str = "v4_ru"
    VOICE_MAX_CHARS: int = 200
    VOICE_AUTO_INSTALL: bool = True
    VOICE_TORCH_INDEX_URL: str = "https://download.pytorch.org/whl/cpu"
    FFMPEG_BINARY: str = ""
    STICKER_IDS_DEFAULT: str = "6365185259734040633"
    # Памятные даты: в свой день она сама поздравит, когда захочет (без фикс. часа)
    DATES_ENABLED: bool = True

    JEALOUSY_ENABLED: bool = True
    JEALOUSY_HOURS: float = 12.0
    ENERGY_ENABLED: bool = True
    CLOSENESS_ENABLED: bool = True
    CLOSENESS_PER_MSG: int = 1
    PETNAMES_ENABLED: bool = True
    PETNAME_THRESHOLD: int = 30

    # Погода-забота: про погоду она вспоминает сама, когда захочет (без фикс. часа)
    WEATHER_ENABLED: bool = True
    OPENWEATHER_API_KEY: str | None = None
    WEATHER_CITY: str = ""
    WEATHER_UNITS: str = "metric"
    WEATHER_LANG: str = "ru"
    MAHIRU_CITY: str = "Токио"

    # Лента жизни: раз в день сама придумывает себе бытовое событие дня (фон)
    LIFE_FEED_ENABLED: bool = True

    THREADS_ENABLED: bool = True
    THREAD_ASK_AFTER_HOURS: float = 8.0

    MOOD_PERSIST_ENABLED: bool = True
    MOOD_LINGER_HOURS: float = 2.0

    RETURN_NOTE_ENABLED: bool = True
    RETURN_MIN_HOURS: float = 3.0

    LOG_LEVEL: str = "INFO"

    @property
    def admin_ids(self) -> set[int]:
        return {int(x) for x in self.ADMIN_IDS.split(",") if x.strip()}

settings = Settings()
