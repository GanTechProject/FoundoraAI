from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
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
    model_primary_provider: Literal["openai", "gemini", "anthropic"] = "openai"
    model_fallback_providers: str = "gemini,anthropic"
    model_task_routes: str = "{}"
    model_max_retries: int = 2
    model_timeout_seconds: int = 30
    model_default_max_output_tokens: int = 512
    model_hard_max_output_tokens: int = 24_000
    model_default_token_budget: int = 8192
    model_default_cost_budget_microusd: int = 100_000
    knowledge_storage_backend: Literal["local"] = "local"
    knowledge_storage_path: str = "/var/lib/foundora/knowledge"
    knowledge_max_upload_bytes: int = 5_242_880
    knowledge_max_extracted_characters: int = 1_000_000
    sandbox_runner_url: str = "http://localhost:8080"
    sandbox_runner_token: SecretStr | None = None
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("FOUNDORA_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    gemini_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("FOUNDORA_GEMINI_API_KEY", "GEMINI_API_KEY"),
    )
    anthropic_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("FOUNDORA_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )
    openai_model: str = "gpt-4o-mini"
    gemini_model: str = "gemini-3.6-flash"
    anthropic_model: str = "claude-haiku-4-5-20251001"

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

    @field_validator("sandbox_runner_url")
    @classmethod
    def validate_sandbox_runner_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith("http://") or "/" in normalized.split("://", 1)[1]:
            raise ValueError("FOUNDORA_SANDBOX_RUNNER_URL must be an HTTP origin without a path")
        return normalized

    @field_validator("sandbox_runner_token")
    @classmethod
    def validate_sandbox_runner_token(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < 32:
            raise ValueError("FOUNDORA_SANDBOX_RUNNER_TOKEN must contain at least 32 characters")
        return value

    @field_validator(
        "session_idle_minutes",
        "session_absolute_minutes",
        "login_rate_limit",
        "login_rate_window_seconds",
        "model_timeout_seconds",
        "model_default_max_output_tokens",
        "model_hard_max_output_tokens",
        "model_default_token_budget",
        "model_default_cost_budget_microusd",
        "knowledge_max_upload_bytes",
        "knowledge_max_extracted_characters",
    )
    @classmethod
    def validate_positive_security_values(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("security duration and limit values must be positive")
        return value

    @field_validator("model_max_retries")
    @classmethod
    def validate_model_retries(cls, value: int) -> int:
        if value < 0 or value > 5:
            raise ValueError("model retries must be between zero and five")
        return value

    @field_validator("model_fallback_providers")
    @classmethod
    def validate_fallback_providers(cls, value: str) -> str:
        names = [name.strip().lower() for name in value.split(",") if name.strip()]
        if any(name not in {"openai", "gemini", "anthropic"} for name in names):
            raise ValueError("fallback providers contain an unsupported provider")
        return ",".join(dict.fromkeys(names))

    @model_validator(mode="after")
    def validate_production_transport(self) -> Settings:
        if self.session_idle_minutes > self.session_absolute_minutes:
            raise ValueError("session idle timeout cannot exceed absolute timeout")
        if self.model_default_max_output_tokens > self.model_hard_max_output_tokens:
            raise ValueError("default model output limit cannot exceed the hard limit")
        if self.model_timeout_seconds > 120:
            raise ValueError("model timeout cannot exceed 120 seconds")
        if self.model_hard_max_output_tokens > 32_768:
            raise ValueError("model hard output limit cannot exceed 32768 tokens")
        if self.model_default_token_budget > 1_000_000:
            raise ValueError("default model token budget cannot exceed 1000000 tokens")
        if self.model_default_cost_budget_microusd > 10_000_000:
            raise ValueError("default model cost budget cannot exceed 10000000 micro-USD")
        if self.knowledge_max_upload_bytes > 52_428_800:
            raise ValueError("knowledge uploads cannot exceed 52428800 bytes")
        if self.knowledge_max_extracted_characters > 10_000_000:
            raise ValueError("extracted knowledge cannot exceed 10000000 characters")
        if not self.knowledge_storage_path.strip():
            raise ValueError("knowledge storage path cannot be blank")
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
