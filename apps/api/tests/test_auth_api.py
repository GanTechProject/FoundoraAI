import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from foundora.auth.service import AuthContext, AuthenticationFailed, IssuedSession
from foundora.main import app
from foundora.models import Owner, OwnerSession

ORIGIN = "http://localhost:3000"


def auth_records() -> tuple[AuthContext, IssuedSession]:
    now = datetime.now(UTC)
    owner = Owner(
        id=uuid.uuid4(),
        singleton_key=1,
        email="owner@example.com",
        password_hash="$argon2id$not-used-in-this-test",
        created_at=now,
        updated_at=now,
        password_changed_at=now,
    )
    owner_session = OwnerSession(
        id=uuid.uuid4(),
        owner_id=owner.id,
        token_hash="0" * 64,
        csrf_hash="1" * 64,
        created_at=now,
        last_seen_at=now,
        idle_expires_at=now + timedelta(minutes=30),
        expires_at=now + timedelta(hours=8),
        revoked_at=None,
        user_agent="Foundora test client",
    )
    context = AuthContext(owner=owner, session=owner_session)
    return context, IssuedSession(context=context, token="session-token", csrf_token="csrf-token")


def test_unauthenticated_session_access_is_blocked() -> None:
    with (
        patch(
            "foundora.api.auth.AuthService.resolve_session",
            new=AsyncMock(return_value=None),
        ),
        TestClient(app) as client,
    ):
        response = client.get("/auth/session")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_authenticated_session_responses_are_not_cacheable() -> None:
    context, _ = auth_records()
    with (
        patch(
            "foundora.api.auth.AuthService.resolve_session",
            new=AsyncMock(return_value=context),
        ),
        patch(
            "foundora.api.auth.AuthService.list_active_sessions",
            new=AsyncMock(return_value=[context.session]),
        ),
        TestClient(app) as client,
    ):
        client.cookies.set("id", "session-token")
        session_response = client.get("/auth/session")
        sessions_response = client.get("/auth/sessions")

    assert session_response.status_code == 200
    assert sessions_response.status_code == 200
    assert session_response.headers["Cache-Control"] == "no-store"
    assert sessions_response.headers["Cache-Control"] == "no-store"


def test_unsafe_request_without_trusted_origin_is_blocked() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/auth/login",
            json={"email": "owner@example.com", "password": "irrelevant"},
        )

    assert response.status_code == 403
    assert response.headers["X-Frame-Options"] == "DENY"


def test_login_failure_is_generic() -> None:
    with (
        patch("foundora.api.auth.enforce_rate_limit", new=AsyncMock()),
        patch(
            "foundora.api.auth.AuthService.authenticate",
            new=AsyncMock(side_effect=AuthenticationFailed),
        ),
        TestClient(app) as client,
    ):
        response = client.post(
            "/auth/login",
            headers={"Origin": ORIGIN},
            json={"email": "owner@example.com", "password": "wrong-password"},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}


def test_login_fails_closed_when_rate_limiter_is_unavailable() -> None:
    with (
        patch(
            "foundora.api.auth.enforce_rate_limit",
            new=AsyncMock(side_effect=RedisConnectionError("unavailable")),
        ),
        TestClient(app) as client,
    ):
        response = client.post(
            "/auth/login",
            headers={"Origin": ORIGIN},
            json={"email": "owner@example.com", "password": "irrelevant"},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Authentication is temporarily unavailable"}


def test_successful_login_issues_hardened_cookies() -> None:
    _, issued = auth_records()
    with (
        patch("foundora.api.auth.enforce_rate_limit", new=AsyncMock()),
        patch(
            "foundora.api.auth.AuthService.authenticate",
            new=AsyncMock(return_value=issued),
        ),
        TestClient(app) as client,
    ):
        response = client.post(
            "/auth/login",
            headers={"Origin": ORIGIN},
            json={"email": "OWNER@example.com", "password": "correct-password"},
        )

    cookies = response.headers.get_list("set-cookie")
    assert response.status_code == 200
    assert len(cookies) == 2
    assert all("HttpOnly" in cookie for cookie in cookies)
    assert all("SameSite=strict" in cookie for cookie in cookies)
    assert all("Path=/" in cookie for cookie in cookies)
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["owner"]["email"] == "owner@example.com"


def test_csrf_is_required_for_logout() -> None:
    context, _ = auth_records()
    with (
        patch(
            "foundora.api.auth.AuthService.resolve_session",
            new=AsyncMock(return_value=context),
        ),
        patch("foundora.api.auth.AuthService.csrf_is_valid", return_value=False),
        TestClient(app) as client,
    ):
        client.cookies.set("id", "session-token")
        response = client.post(
            "/auth/logout",
            headers={"Origin": ORIGIN},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF validation failed"}


def test_security_headers_are_applied() -> None:
    with TestClient(app) as client:
        response = client.get("/health/live")

    assert (
        response.headers["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'none'"
    )
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
