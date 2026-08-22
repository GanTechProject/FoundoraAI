from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from redis.exceptions import RedisError

from foundora.auth.passwords import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    normalize_email,
)
from foundora.auth.rate_limit import RateLimitExceeded, enforce_rate_limit
from foundora.auth.service import AuthContext, AuthenticationFailed, AuthService, IssuedSession
from foundora.config import get_settings
from foundora.infrastructure.redis import get_redis
from foundora.models import OwnerSession

router = APIRouter(prefix="/auth", tags=["owner authentication"])
logger = logging.getLogger(__name__)
settings = get_settings()


class OwnerView(BaseModel):
    id: UUID
    email: str


class SessionView(BaseModel):
    id: UUID
    created_at: datetime
    last_seen_at: datetime
    idle_expires_at: datetime
    expires_at: datetime
    user_agent: str | None
    current: bool


class AuthView(BaseModel):
    owner: OwnerView
    session: SessionView


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("email")
    @classmethod
    def normalized_email(cls, value: str) -> str:
        return normalize_email(value)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(
        min_length=MIN_PASSWORD_LENGTH,
        max_length=MAX_PASSWORD_LENGTH,
    )


class RevocationView(BaseModel):
    revoked_sessions: int


def _owner_view(context: AuthContext) -> OwnerView:
    return OwnerView(id=context.owner.id, email=context.owner.email)


def _session_view(context: AuthContext, session: OwnerSession | None = None) -> SessionView:
    record = context.session if session is None else session
    return SessionView(
        id=record.id,
        created_at=record.created_at,
        last_seen_at=record.last_seen_at,
        idle_expires_at=record.idle_expires_at,
        expires_at=record.expires_at,
        user_agent=record.user_agent,
        current=record.id == context.session.id,
    )


def _auth_view(issued: IssuedSession) -> AuthView:
    return AuthView(
        owner=_owner_view(issued.context),
        session=_session_view(issued.context),
    )


def _set_auth_cookies(response: Response, issued: IssuedSession) -> None:
    max_age = settings.session_absolute_minutes * 60
    for name, value in (
        (settings.session_cookie_name, issued.token),
        (settings.csrf_cookie_name, issued.csrf_token),
    ):
        response.set_cookie(
            name,
            value,
            max_age=max_age,
            expires=issued.context.session.expires_at,
            path="/",
            secure=settings.cookie_secure,
            httponly=True,
            samesite="strict",
        )


def _clear_auth_cookies(response: Response) -> None:
    for name in (settings.session_cookie_name, settings.csrf_cookie_name):
        response.delete_cookie(
            name,
            path="/",
            secure=settings.cookie_secure,
            httponly=True,
            samesite="strict",
        )


async def require_auth(
    token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> AuthContext:
    context = await AuthService().resolve_session(token)
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return context


async def require_csrf(
    context: Annotated[AuthContext, Depends(require_auth)],
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> AuthContext:
    if not AuthService().csrf_is_valid(context, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
    return context


@router.post("/login", response_model=AuthView)
async def login(payload: LoginRequest, request: Request, response: Response) -> AuthView:
    client_address = request.client.host if request.client is not None else "unknown"
    try:
        await enforce_rate_limit(
            get_redis(),
            scope="login-account",
            identity=payload.email,
            limit=settings.login_rate_limit,
            window_seconds=settings.login_rate_window_seconds,
        )
        await enforce_rate_limit(
            get_redis(),
            scope="login-network",
            identity=client_address,
            limit=max(settings.login_rate_limit * 5, settings.login_rate_limit),
            window_seconds=settings.login_rate_window_seconds,
        )
    except RateLimitExceeded as error:
        logger.warning("Authentication rate limited", extra={"event": "auth.login.rate_limited"})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Try again later",
            headers={"Retry-After": str(error.retry_after)},
        ) from error
    except RedisError as error:
        logger.error(
            "Authentication rate limiter unavailable", extra={"event": "auth.rate_limit.error"}
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is temporarily unavailable",
        ) from error

    try:
        issued = await AuthService().authenticate(
            payload.email,
            payload.password,
            request.headers.get("User-Agent"),
        )
    except AuthenticationFailed as error:
        logger.warning("Authentication failed", extra={"event": "auth.login.failed"})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        ) from error
    _set_auth_cookies(response, issued)
    response.headers["Cache-Control"] = "no-store"
    logger.info("Authentication succeeded", extra={"event": "auth.login.succeeded"})
    return _auth_view(issued)


@router.get("/session", response_model=AuthView)
async def session(context: Annotated[AuthContext, Depends(require_auth)]) -> AuthView:
    return AuthView(owner=_owner_view(context), session=_session_view(context))


@router.get("/sessions", response_model=list[SessionView])
async def sessions(context: Annotated[AuthContext, Depends(require_auth)]) -> list[SessionView]:
    records = await AuthService().list_active_sessions(context)
    return [_session_view(context, record) for record in records]


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    context: Annotated[AuthContext, Depends(require_csrf)], response: Response
) -> None:
    await AuthService().revoke_current(context)
    _clear_auth_cookies(response)
    response.headers["Clear-Site-Data"] = '"cache", "cookies", "storage"'
    logger.info("Owner session revoked", extra={"event": "auth.logout"})


@router.post("/sessions/revoke-others", response_model=RevocationView)
async def revoke_other_sessions(
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> RevocationView:
    revoked = await AuthService().revoke_other_sessions(context)
    logger.info("Other owner sessions revoked", extra={"event": "auth.sessions.revoked"})
    return RevocationView(revoked_sessions=revoked)


@router.post("/password", response_model=AuthView)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> AuthView:
    try:
        issued = await AuthService().change_password(
            context,
            payload.current_password,
            payload.new_password,
            request.headers.get("User-Agent"),
        )
    except AuthenticationFailed as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        ) from error
    _set_auth_cookies(response, issued)
    response.headers["Cache-Control"] = "no-store"
    logger.info("Owner password changed", extra={"event": "auth.password.changed"})
    return _auth_view(issued)
