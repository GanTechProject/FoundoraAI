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


def test_default_gateway_limit_supports_the_largest_seeded_agent_policy() -> None:
    settings = Settings(_env_file=None)

    assert settings.model_hard_max_output_tokens == 24_000
    assert settings.model_hard_max_output_tokens <= 32_768


def test_provider_keys_accept_standard_names_and_stay_masked() -> None:
    settings = Settings(_env_file=None, OPENAI_API_KEY="never-print-this")

    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "never-print-this"
    assert "never-print-this" not in repr(settings)


def test_sandbox_runner_token_is_bounded_and_stays_masked() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, sandbox_runner_token="short")

    token = "sandbox-runner-secret-000000000001"
    settings = Settings(_env_file=None, sandbox_runner_token=token)
    assert settings.sandbox_runner_token is not None
    assert settings.sandbox_runner_token.get_secret_value() == token
    assert token not in repr(settings)
