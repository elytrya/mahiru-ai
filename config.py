from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    BOT_TOKEN: str = ""
    ADMIN_IDS: str = ""

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
    OLLAMA_MODEL: str = "llama3.1"

    YANDEX_API_KEY: str | None = None
    YANDEX_FOLDER: str | None = None
    YANDEX_MODEL: str = "yandexgpt-lite"
    YANDEX_PROMPT_ID: str | None = None

    G4F_MODEL: str = "gpt-4o-mini"
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

    LOG_LEVEL: str = "INFO"

    @property
    def admin_ids(self) -> set[int]:
        return {int(x) for x in self.ADMIN_IDS.split(",") if x.strip()}

settings = Settings()
