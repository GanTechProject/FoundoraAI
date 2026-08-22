import pytest
from pydantic import ValidationError

from foundora.config import Settings


def test_database_driver_is_explicit() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="sqlite:///foundora.db")


def test_cors_origins_are_normalized() -> None:
    settings = Settings(allowed_origins="http://localhost:3000, https://example.test ")
    assert settings.cors_origins == ["http://localhost:3000", "https://example.test"]
