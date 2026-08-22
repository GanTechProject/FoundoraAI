from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
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
    allowed_origins: str = ""
    public_origin: str = "http://localhost:3000"
    session_cookie_name: str = "id"
    csrf_cookie_name: str = "csrf"
    cookie_secure: bool = False
    session_idle_minutes: int = 30
    session_absolute_minutes: int = 480
    login_rate_limit: int = 5
    login_rate_window_seconds: int = 900

    @field_validator("database_url")
    @classmethod
    def validate_postgresql(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("FOUNDORA_DATABASE_URL must use postgresql+asyncpg")
        return value

    @field_validator("public_origin")
    @classmethod
    def validate_public_origin(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("FOUNDORA_PUBLIC_ORIGIN must be an absolute HTTP(S) origin")
        if "/" in normalized.split("://", 1)[1]:
            raise ValueError("FOUNDORA_PUBLIC_ORIGIN must not include a path")
        return normalized

    @field_validator(
        "session_idle_minutes",
        "session_absolute_minutes",
        "login_rate_limit",
        "login_rate_window_seconds",
    )
    @classmethod
    def validate_positive_security_values(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("security duration and limit values must be positive")
        return value

    @model_validator(mode="after")
    def validate_production_transport(self) -> Settings:
        if self.session_idle_minutes > self.session_absolute_minutes:
            raise ValueError("session idle timeout cannot exceed absolute timeout")
        if self.environment == "production":
            if not self.cookie_secure:
                raise ValueError("FOUNDORA_COOKIE_SECURE must be true in production")
            if not self.public_origin.startswith("https://"):
                raise ValueError("FOUNDORA_PUBLIC_ORIGIN must use HTTPS in production")
        return self

    @property
    def cors_origins(self) -> list[str]:
        origins = [self.public_origin]
        origins.extend(
            origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()
        )
        return list(dict.fromkeys(origins))


@lru_cache
def get_settings() -> Settings:
    return Settings()
