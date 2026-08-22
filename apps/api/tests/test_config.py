import pytest
from pydantic import ValidationError

from foundora.auth.service import _idle_refresh_interval
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


def test_session_refresh_interval_adapts_to_short_idle_timeout() -> None:
    assert _idle_refresh_interval(Settings(session_idle_minutes=1)).total_seconds() == 30
    assert _idle_refresh_interval(Settings(session_idle_minutes=30)).total_seconds() == 300


def test_provider_keys_accept_standard_names_and_stay_masked() -> None:
    settings = Settings(_env_file=None, OPENAI_API_KEY="never-print-this")

    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "never-print-this"
    assert "never-print-this" not in repr(settings)
