"""Cấu hình đọc từ biến môi trường hoặc file .env."""
from __future__ import annotations

import logging
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_API_BASE = "https://bot-api.zaloplatforms.com"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    zalo_bot_token: SecretStr = SecretStr("")
    zalo_api_base: str = DEFAULT_API_BASE
    webhook_url: str = ""
    webhook_secret: SecretStr = SecretStr("")
    database_url: str = "sqlite:///data/bot.db"
    log_level: str = "INFO"
    poll_timeout: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx ghi URL request (có chứa token bot) ở mức INFO, nên chặn lại.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
