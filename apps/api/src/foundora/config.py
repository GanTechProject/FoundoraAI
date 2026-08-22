from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="FOUNDORA_",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "foundora-api"
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: str = "postgresql+asyncpg://foundora@localhost:5432/foundora"
    redis_url: str = "redis://localhost:6379/0"
    worker_queue: str = "foundora"
    allowed_origins: str = "http://localhost:3000"

    @field_validator("database_url")
    @classmethod
    def validate_postgresql(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("FOUNDORA_DATABASE_URL must use postgresql+asyncpg")
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
