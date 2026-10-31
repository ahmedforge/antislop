from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AntiSlop API"
    environment: Literal["development", "test", "production"] = "development"
    database_url: PostgresDsn = "postgresql+psycopg://antislop:antislop_dev@localhost:5432/antislop"
    redis_url: RedisDsn = "redis://localhost:6379/0"

    rate_limit_namespace: str = Field(default="antislop:rate-limit:v1", pattern=r"^[A-Za-z0-9:_-]{1,100}$")
    rate_limit_install_capacity: int = Field(default=5, ge=1, le=10000)
    rate_limit_install_refill_seconds: float = Field(default=60, ge=1, le=86400, allow_inf_nan=False)
    rate_limit_ip_capacity: int = Field(default=20, ge=1, le=10000)
    rate_limit_ip_refill_seconds: float = Field(default=10, ge=1, le=86400, allow_inf_nan=False)
