import pytest

from foundora.auth.passwords import (
    InvalidOwnerEmail,
    InvalidOwnerPassword,
    hash_password,
    normalize_email,
    verify_password,
)


def test_owner_email_is_normalized() -> None:
    assert normalize_email(" Owner@Example.COM ") == "owner@example.com"


def test_invalid_owner_email_is_rejected() -> None:
    with pytest.raises(InvalidOwnerEmail):
        normalize_email("not-an-email")


def test_password_uses_argon2id_and_verifies() -> None:
    encoded = hash_password("a sufficiently long passphrase")
    valid, replacement = verify_password("a sufficiently long passphrase", encoded)

    assert encoded.startswith("$argon2id$")
    assert valid is True
    assert replacement is None


def test_short_password_is_rejected() -> None:
    with pytest.raises(InvalidOwnerPassword):
        hash_password("too short")


def test_missing_owner_still_runs_password_verification() -> None:
    valid, replacement = verify_password("any attempted password", None)
    assert valid is False
    assert replacement is None
