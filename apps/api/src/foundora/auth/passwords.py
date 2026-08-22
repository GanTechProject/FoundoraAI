from __future__ import annotations

import re

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

MIN_PASSWORD_LENGTH = 15
MAX_PASSWORD_LENGTH = 128
MAX_EMAIL_LENGTH = 320
_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_password_hash = PasswordHash.recommended()
_dummy_hash = _password_hash.hash("not-a-real-owner-password")


class InvalidOwnerEmail(ValueError):
    pass


class InvalidOwnerPassword(ValueError):
    pass


def normalize_email(value: str) -> str:
    normalized = value.strip().casefold()
    if len(normalized) > MAX_EMAIL_LENGTH or not _EMAIL_PATTERN.fullmatch(normalized):
        raise InvalidOwnerEmail("Enter a valid email address")
    return normalized


def validate_password(value: str) -> str:
    if len(value) < MIN_PASSWORD_LENGTH:
        raise InvalidOwnerPassword(
            f"Password must contain at least {MIN_PASSWORD_LENGTH} characters"
        )
    if len(value) > MAX_PASSWORD_LENGTH:
        raise InvalidOwnerPassword(
            f"Password must contain no more than {MAX_PASSWORD_LENGTH} characters"
        )
    return value


def hash_password(value: str) -> str:
    return _password_hash.hash(validate_password(value))


def verify_password(value: str, encoded_hash: str | None) -> tuple[bool, str | None]:
    candidate_hash = encoded_hash if encoded_hash is not None else _dummy_hash
    try:
        valid, updated_hash = _password_hash.verify_and_update(value, candidate_hash)
    except (UnknownHashError, ValueError):
        return False, None
    return valid and encoded_hash is not None, updated_hash
