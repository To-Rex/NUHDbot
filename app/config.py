import os
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

    upload_dir: Path = APP_DIR / "static" / "uploads"  # local fallback when no S3 store is configured
    max_image_mb: int = 8
    # S3-compatible object store (TorexPloy TibFiles). Empty endpoint = keep files on local disk.
    s3_endpoint: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_region: str = "us-east-1"
    s3_bucket: str = ""
    s3_prefix: str = "uploads"  # key prefix inside the bucket
    s3_public_url: str = ""  # public base URL of the store (https) → direct links; empty → served through /media/
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
            # TorexPloy storage "connection" variables arrive as S3_S3_* / S3_AWS_*; accept them as fallbacks.
            aliases = {"s3_endpoint": ("s3_s3_endpoint", "s3_aws_endpoint_url", "aws_endpoint_url"), "s3_access_key_id": ("s3_s3_access_key_id", "s3_aws_access_key_id", "aws_access_key_id"),
                       "s3_secret_access_key": ("s3_s3_secret_access_key", "s3_aws_secret_access_key", "aws_secret_access_key"), "s3_region": ("s3_s3_region", "s3_aws_region", "aws_region"), "s3_bucket": ("s3_s3_bucket",)}
            low = {str(k).lower(): v for k, v in cleaned.items()}
            env = {k.lower(): v.strip() for k, v in os.environ.items()}
            for target, names in aliases.items():
                if not low.get(target) and not env.get(target):
                    for n in names:
                        if low.get(n) or env.get(n):
                            cleaned[target] = low.get(n) or env.get(n)
                            break
            return cleaned
        return data

    @property
    def s3_enabled(self) -> bool:
        return bool(self.s3_endpoint and self.s3_bucket and self.s3_access_key_id and self.s3_secret_access_key)

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
