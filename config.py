from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    BOT_TOKEN: str = ""
    ADMIN_IDS: str = ""
    # прокси для Telegram API (обход блокировок). Примеры:
    #   http://user:pass@host:port  |  socks5://user:pass@host:port
    # Для socks5 нужен пакет aiohttp-socks (уже в requirements).
    TELEGRAM_PROXY: str | None = None
    # таймаут запросов к Telegram, сек
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
    OLLAMA_MODEL: str = "qwen2.5:3b"   # лёгкая, хорошо болтает по-русски и умеет tool-calling
    # всё само: скачать/установить Ollama, запустить сервер, скачать модель
    OLLAMA_AUTO_INSTALL: bool = True
    OLLAMA_AUTO_START: bool = True
    OLLAMA_AUTO_PULL: bool = True

    YANDEX_API_KEY: str | None = None
    YANDEX_FOLDER: str | None = None
    YANDEX_MODEL: str = "yandexgpt-lite"
    YANDEX_PROMPT_ID: str | None = None

    # свапнули дефолт с gpt-4o-* на deepseek-v3 (4o остаётся в fallback-цепочке)
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

    AUTONOMOUS_ENABLED: bool = True
    AUTONOMOUS_MIN_HOURS: float = 3.0
    AUTONOMOUS_MAX_HOURS: float = 12.0
    AUTONOMOUS_TIME_START: int = 10
    AUTONOMOUS_TIME_END: int = 23

    TYPING_INDICATOR: bool = True
    SHOW_TOOL_CALLS: bool = True

    # ==== Очеловечивание (настраивается в /admin -> Человечность, /humanset, setup_wizard) ====
    # заменять длинное тире «—»/«–» на обычный дефис «-»
    NO_EMDASH: bool = True
    # имитировать набор текста (паузы + «печатает…» перед ответом)
    HUMAN_TYPING: bool = True
    # скорость «печати» — символов в секунду
    TYPING_SPEED_CPS: float = 14.0
    TYPING_MIN_SECONDS: float = 1.2
    TYPING_MAX_SECONDS: float = 9.0
    # пауза «заметила сообщение» перед началом печати
    READ_DELAY_MIN: float = 0.5
    READ_DELAY_MAX: float = 3.0
    # шанс «занята» (ответит заметно позже), 0..1
    IGNORE_CHANCE: float = 0.12
    IGNORE_MIN_SECONDS: float = 8.0
    IGNORE_MAX_SECONDS: float = 40.0
    # разбивать длинный ответ на несколько сообщений
    SPLIT_MESSAGES: bool = True
    SPLIT_MAX: int = 3

    # реакции-эмодзи на входящее сообщение (ставит перед ответом)
    REACTIONS_ENABLED: bool = True
    REACTION_CHANCE: float = 0.25
    # опечатки с самоисправлением (следующим сообщением «*правильное_слово»)
    TYPO_ENABLED: bool = True
    TYPO_CHANCE: float = 0.12
    # настроение влияет на скорость печати и паузы (злая - медленнее/резче, влюблённая - быстрее/теплее)
    MOOD_SPEED_ENABLED: bool = True
    # «прочитала, но не ответила»: иногда мелькает «печатает…», замолкает на пару минут, потом пишет
    READ_SILENCE_ENABLED: bool = True
    READ_SILENCE_CHANCE: float = 0.07
    READ_SILENCE_MIN_SECONDS: float = 45.0
    READ_SILENCE_MAX_SECONDS: float = 150.0
    # стикеры / кастом-эмодзи по настроению
    STICKERS_ENABLED: bool = True
    STICKER_CHANCE: float = 0.15
    # дефолтные id через запятую: чисто цифровой = кастом-эмодзи, иначе file_id стикера
    STICKER_IDS_DEFAULT: str = "6365185259734040633"
    # памятные даты (дни рождения, годовщины) - сама поздравляет
    DATES_ENABLED: bool = True
    DATES_GREET_HOUR: int = 10

    # ==== Характер / забота ====
    # ревность/обидки: если долго не писал - встречает с лёгкой обидой
    JEALOUSY_ENABLED: bool = True
    JEALOUSY_HOURS: float = 12.0
    # внутренняя энергия/батарейка: к ночи устаёт, отвечает короче и мягче
    ENERGY_ENABLED: bool = True
    # уровень близости: копится со временем, разблокирует более тёплый тон
    CLOSENESS_ENABLED: bool = True
    CLOSENESS_PER_MSG: int = 1
    # клички/пет-неймы: сама придумывает ласковое прозвище, когда близость вырастет
    PETNAMES_ENABLED: bool = True
    PETNAME_THRESHOLD: int = 30

    # ==== Погода (OpenWeather) - забота про погоду ====
    WEATHER_ENABLED: bool = True
    OPENWEATHER_API_KEY: str | None = None
    # город, где живёт владелец (напр. "Moscow" или "Москва,RU")
    WEATHER_CITY: str = ""
    # погода пишется раз в день в СЛУЧАЙНОЕ время в окне [MIN..MAX] часов
    WEATHER_MIN_HOUR: int = 8
    WEATHER_MAX_HOUR: int = 22
    # устаревшее (больше не используется, оставлено для совместимости со старым .env)
    WEATHER_CARE_HOUR: int = 8
    WEATHER_UNITS: str = "metric"
    WEATHER_LANG: str = "ru"
    # город, где «живёт» сама Махиру (учёба/быт/своя погода). Может рассказывать про погоду у себя
    MAHIRU_CITY: str = "Токио"

    LOG_LEVEL: str = "INFO"

    @property
    def admin_ids(self) -> set[int]:
        return {int(x) for x in self.ADMIN_IDS.split(",") if x.strip()}

settings = Settings()
