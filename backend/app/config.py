from typing import Literal

from pydantic import PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AntiSlop API"
    environment: Literal["development", "test", "production"] = "development"
    database_url: PostgresDsn = "postgresql+psycopg://antislop:antislop_dev@localhost:5432/antislop"
    redis_url: RedisDsn = "redis://localhost:6379/0"
