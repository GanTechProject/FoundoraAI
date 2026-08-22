from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from foundora.auth.passwords import (
    hash_password,
    normalize_email,
    validate_password,
    verify_password,
)
from foundora.config import Settings, get_settings
from foundora.infrastructure.database import get_session_factory
from foundora.models import Owner, OwnerSession


class AuthenticationFailed(Exception):
    pass


class OwnerAlreadyProvisioned(Exception):
    pass


@dataclass(frozen=True)
class AuthContext:
    owner: Owner
    session: OwnerSession


@dataclass(frozen=True)
class IssuedSession:
    context: AuthContext
    token: str
    csrf_token: str


def _token() -> str:
    return secrets.token_urlsafe(32)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _idle_refresh_interval(settings: Settings) -> timedelta:
    return timedelta(seconds=min(300, settings.session_idle_minutes * 30))


class AuthService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session_factory = session_factory or get_session_factory()
        self._settings = settings or get_settings()

    async def provision_owner(
        self, email: str, password: str, *, replace_existing: bool = False
    ) -> Owner:
        normalized_email = normalize_email(email)
        encoded_password = hash_password(password)
        now = _now()
        async with self._session_factory() as database:
            async with database.begin():
                result = await database.execute(select(Owner).with_for_update())
                owner = result.scalar_one_or_none()
                if owner is not None and not replace_existing:
                    raise OwnerAlreadyProvisioned
                if owner is None:
                    owner = Owner(
                        id=uuid.uuid4(),
                        singleton_key=1,
                        email=normalized_email,
                        password_hash=encoded_password,
                        created_at=now,
                        updated_at=now,
                        password_changed_at=now,
                    )
                    database.add(owner)
                else:
                    owner.email = normalized_email
                    owner.password_hash = encoded_password
                    owner.updated_at = now
                    owner.password_changed_at = now
                    await database.execute(
                        update(OwnerSession)
                        .where(
                            OwnerSession.owner_id == owner.id,
                            OwnerSession.revoked_at.is_(None),
                        )
                        .values(revoked_at=now)
                    )
            return owner

    async def authenticate(
        self, email: str, password: str, user_agent: str | None
    ) -> IssuedSession:
        try:
            normalized_email = normalize_email(email)
        except ValueError:
            normalized_email = "invalid@example.invalid"
        async with self._session_factory() as database:
            async with database.begin():
                result = await database.execute(
                    select(Owner).where(Owner.email == normalized_email)
                )
                owner = result.scalar_one_or_none()
                valid, updated_hash = verify_password(
                    password, owner.password_hash if owner is not None else None
                )
                if not valid or owner is None:
                    raise AuthenticationFailed
                if updated_hash is not None:
                    owner.password_hash = updated_hash
                    owner.updated_at = _now()
                return await self._issue(database, owner, user_agent)

    async def resolve_session(self, token: str | None) -> AuthContext | None:
        if token is None or len(token) > 256:
            return None
        now = _now()
        async with self._session_factory() as database:
            result = await database.execute(
                select(OwnerSession, Owner)
                .join(Owner, Owner.id == OwnerSession.owner_id)
                .where(OwnerSession.token_hash == _digest(token))
            )
            record = result.one_or_none()
            if record is None:
                return None
            owner_session, owner = record
            if (
                owner_session.revoked_at is not None
                or owner_session.expires_at <= now
                or owner_session.idle_expires_at <= now
            ):
                if owner_session.revoked_at is None:
                    owner_session.revoked_at = now
                    await database.commit()
                return None
            if owner_session.last_seen_at <= now - _idle_refresh_interval(self._settings):
                owner_session.last_seen_at = now
                owner_session.idle_expires_at = min(
                    owner_session.expires_at,
                    now + timedelta(minutes=self._settings.session_idle_minutes),
                )
                await database.commit()
            return AuthContext(owner=owner, session=owner_session)

    def csrf_is_valid(self, context: AuthContext, csrf_token: str | None) -> bool:
        if csrf_token is None or len(csrf_token) > 256:
            return False
        return hmac.compare_digest(context.session.csrf_hash, _digest(csrf_token))

    async def revoke_current(self, context: AuthContext) -> None:
        async with self._session_factory() as database:
            await database.execute(
                update(OwnerSession)
                .where(OwnerSession.id == context.session.id, OwnerSession.revoked_at.is_(None))
                .values(revoked_at=_now())
            )
            await database.commit()

    async def revoke_other_sessions(self, context: AuthContext) -> int:
        async with self._session_factory() as database:
            result = await database.execute(
                update(OwnerSession)
                .where(
                    OwnerSession.owner_id == context.owner.id,
                    OwnerSession.id != context.session.id,
                    OwnerSession.revoked_at.is_(None),
                )
                .values(revoked_at=_now())
            )
            await database.commit()
            return result.rowcount  # type: ignore[attr-defined,no-any-return]

    async def list_active_sessions(self, context: AuthContext) -> list[OwnerSession]:
        now = _now()
        async with self._session_factory() as database:
            result = await database.execute(
                select(OwnerSession)
                .where(
                    OwnerSession.owner_id == context.owner.id,
                    OwnerSession.revoked_at.is_(None),
                    OwnerSession.expires_at > now,
                    OwnerSession.idle_expires_at > now,
                )
                .order_by(OwnerSession.created_at.desc())
            )
            return list(result.scalars())

    async def change_password(
        self,
        context: AuthContext,
        current_password: str,
        new_password: str,
        user_agent: str | None,
    ) -> IssuedSession:
        validate_password(new_password)
        now = _now()
        async with self._session_factory() as database:
            async with database.begin():
                result = await database.execute(
                    select(Owner).where(Owner.id == context.owner.id).with_for_update()
                )
                owner = result.scalar_one()
                valid, _ = verify_password(current_password, owner.password_hash)
                if not valid:
                    raise AuthenticationFailed
                owner.password_hash = hash_password(new_password)
                owner.password_changed_at = now
                owner.updated_at = now
                await database.execute(
                    update(OwnerSession)
                    .where(
                        OwnerSession.owner_id == owner.id,
                        OwnerSession.revoked_at.is_(None),
                    )
                    .values(revoked_at=now)
                )
                return await self._issue(database, owner, user_agent)

    async def _issue(
        self, database: AsyncSession, owner: Owner, user_agent: str | None
    ) -> IssuedSession:
        now = _now()
        token = _token()
        csrf_token = _token()
        absolute_expiry = now + timedelta(minutes=self._settings.session_absolute_minutes)
        idle_expiry = min(
            absolute_expiry,
            now + timedelta(minutes=self._settings.session_idle_minutes),
        )
        owner_session = OwnerSession(
            id=uuid.uuid4(),
            owner_id=owner.id,
            token_hash=_digest(token),
            csrf_hash=_digest(csrf_token),
            created_at=now,
            last_seen_at=now,
            idle_expires_at=idle_expiry,
            expires_at=absolute_expiry,
            revoked_at=None,
            user_agent=(user_agent or "")[:512] or None,
        )
        database.add(owner_session)
        return IssuedSession(
            context=AuthContext(owner=owner, session=owner_session),
            token=token,
            csrf_token=csrf_token,
        )
