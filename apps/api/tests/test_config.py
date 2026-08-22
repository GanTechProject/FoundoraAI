import pytest
from pydantic import ValidationError

from foundora.config import Settings


def test_database_driver_is_explicit() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="sqlite:///foundora.db")


def test_cors_origins_are_normalized() -> None:
    settings = Settings(allowed_origins="http://localhost:3000, https://example.test ")
    assert settings.cors_origins == ["http://localhost:3000", "https://example.test"]


def test_production_origin_is_the_only_default_trusted_origin() -> None:
    settings = Settings(
        environment="production",
        public_origin="https://foundora.example",
        cookie_secure=True,
    )
    assert settings.cors_origins == ["https://foundora.example"]


def test_production_requires_https_and_secure_cookies() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production")

    settings = Settings(
        environment="production",
        public_origin="https://foundora.example",
        cookie_secure=True,
    )
    assert settings.cookie_secure is True


def test_session_idle_timeout_cannot_exceed_absolute_timeout() -> None:
    with pytest.raises(ValidationError):
        Settings(session_idle_minutes=60, session_absolute_minutes=30)
