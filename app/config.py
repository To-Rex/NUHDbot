from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "New & Used Hard Drives"
    debug: bool = False
    secret_key: str = Field(default="change-me-please-32-bytes-minimum-secret")
    base_url: str = "http://localhost:8000"  # public https URL in production (Mini App needs https)

    database_url: str = "postgresql+asyncpg://localhost:5432/nuhdbot"

    bot_token: str = ""
    bot_username: str = "Unetik_bot"
    bot_mode: str = "polling"  # polling | webhook | off
    webhook_secret: str = "nuhd-webhook-secret"
    admin_chat_id: int | None = None  # optional staff group for alerts

    admin_login: str = "admin"
    admin_password: str = "admin12345"

    upload_dir: Path = APP_DIR / "static" / "uploads"
    max_image_mb: int = 8
    max_images_per_product: int = 12

    default_currency: str = "USD"
    timezone: str = "Asia/Shanghai"
    session_max_age: int = 60 * 60 * 24 * 30
    default_lang: str = "uz"
    langs: tuple[str, ...] = ("uz", "uzl", "ru", "en", "zh")  # uz = Cyrillic, uzl = Latin

    auction_extension_seconds: int = 120
    auction_extension_window_seconds: int = 120

    run_migrations: bool = True  # apply alembic migrations automatically at startup

    @model_validator(mode="before")
    @classmethod
    def _strip_inline_comments(cls, data):
        """Some deploy platforms pass `KEY=value  # comment` verbatim; drop the comment part and quotes."""
        if isinstance(data, dict):
            cleaned = {}
            for k, v in data.items():
                if isinstance(v, str):
                    v = v.split(" #", 1)[0].split("\t#", 1)[0].strip()
                    if v.startswith("#"):
                        v = ""
                    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                        v = v[1:-1]
                cleaned[k] = v
            return cleaned
        return data

    @field_validator("admin_chat_id", mode="before")
    @classmethod
    def _empty_to_none(cls, v):
        if v in ("", None):
            return None
        try:
            return int(str(v).strip())
        except ValueError:
            return None


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()
