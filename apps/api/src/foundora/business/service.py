from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import Select, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from foundora.auth.service import AuthContext
from foundora.infrastructure.database import get_session_factory
from foundora.models import Business, BusinessGoal, BusinessPreference, OwnerSession


class BusinessNameConflict(Exception):
    pass


class BusinessNotFound(Exception):
    pass


class NoSelectedBusiness(Exception):
    pass


class GoalNotFound(Exception):
    pass


@dataclass(frozen=True)
class Workspace:
    business: Business
    preferences: BusinessPreference
    goals: list[BusinessGoal]


def _now() -> datetime:
    return datetime.now(UTC)


class BusinessService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()

    async def list_businesses(self, context: AuthContext) -> list[Business]:
        async with self._session_factory() as database:
            result = await database.execute(
                select(Business)
                .where(Business.owner_id == context.owner.id)
                .order_by(Business.archived_at.asc().nulls_first(), Business.name.asc())
            )
            return list(result.scalars())

    async def create_business(
        self, context: AuthContext, *, name: str, summary: str | None
    ) -> Business:
        now = _now()
        business = Business(
            id=uuid.uuid4(),
            owner_id=context.owner.id,
            name=name,
            summary=summary,
            status="planning",
            created_at=now,
            updated_at=now,
            archived_at=None,
        )
        preference = BusinessPreference(
            business_id=business.id,
            timezone="UTC",
            currency="USD",
            locale="en",
            updated_at=now,
        )
        try:
            async with self._session_factory() as database:
                async with database.begin():
                    session = await database.scalar(
                        select(OwnerSession)
                        .where(
                            OwnerSession.id == context.session.id,
                            OwnerSession.owner_id == context.owner.id,
                        )
                        .with_for_update()
                    )
                    if session is None:
                        raise BusinessNotFound
                    database.add_all((business, preference))
                    await database.flush()
                    if session.selected_business_id is None:
                        session.selected_business_id = business.id
            return business
        except IntegrityError as error:
            raise BusinessNameConflict from error

    async def select_business(self, context: AuthContext, business_id: uuid.UUID) -> Business:
        async with self._session_factory() as database:
            async with database.begin():
                business = await database.scalar(
                    select(Business).where(
                        Business.id == business_id,
                        Business.owner_id == context.owner.id,
                        Business.archived_at.is_(None),
                    )
                )
                if business is None:
                    raise BusinessNotFound
                result = await database.execute(
                    update(OwnerSession)
                    .where(
                        OwnerSession.id == context.session.id,
                        OwnerSession.owner_id == context.owner.id,
                    )
                    .values(selected_business_id=business.id)
                )
                if result.rowcount != 1:  # type: ignore[attr-defined]
                    raise BusinessNotFound
            return business

    async def get_workspace(self, context: AuthContext) -> Workspace:
        async with self._session_factory() as database:
            business = await self._selected(database, context)
            preferences = await database.get(BusinessPreference, business.id)
            if preferences is None:
                raise NoSelectedBusiness
            result = await database.execute(
                select(BusinessGoal)
                .where(BusinessGoal.business_id == business.id)
                .order_by(BusinessGoal.created_at.desc())
            )
            return Workspace(
                business=business,
                preferences=preferences,
                goals=list(result.scalars()),
            )

    async def update_profile(
        self, context: AuthContext, *, name: str, summary: str | None
    ) -> Business:
        try:
            async with self._session_factory() as database:
                async with database.begin():
                    business = await self._selected(database, context, lock=True)
                    business.name = name
                    business.summary = summary
                    business.updated_at = _now()
                return business
        except IntegrityError as error:
            raise BusinessNameConflict from error

    async def update_status(self, context: AuthContext, status: str) -> Business:
        async with self._session_factory() as database:
            async with database.begin():
                business = await self._selected(database, context, lock=True)
                business.status = status
                business.updated_at = _now()
            return business

    async def update_preferences(
        self,
        context: AuthContext,
        *,
        timezone: str,
        currency: str,
        locale: str,
    ) -> BusinessPreference:
        async with self._session_factory() as database:
            async with database.begin():
                business = await self._selected(database, context)
                preferences = await database.get(
                    BusinessPreference, business.id, with_for_update=True
                )
                if preferences is None:
                    raise NoSelectedBusiness
                preferences.timezone = timezone
                preferences.currency = currency
                preferences.locale = locale
                preferences.updated_at = _now()
            return preferences

    async def add_goal(
        self,
        context: AuthContext,
        *,
        title: str,
        details: str | None,
        target_date: date | None,
    ) -> BusinessGoal:
        async with self._session_factory() as database:
            async with database.begin():
                business = await self._selected(database, context)
                now = _now()
                goal = BusinessGoal(
                    id=uuid.uuid4(),
                    business_id=business.id,
                    title=title,
                    details=details,
                    target_date=target_date,
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
                database.add(goal)
            return goal

    async def update_goal_status(
        self, context: AuthContext, goal_id: uuid.UUID, status: str
    ) -> BusinessGoal:
        async with self._session_factory() as database:
            async with database.begin():
                business = await self._selected(database, context)
                goal = await database.scalar(
                    select(BusinessGoal)
                    .where(
                        BusinessGoal.id == goal_id,
                        BusinessGoal.business_id == business.id,
                    )
                    .with_for_update()
                )
                if goal is None:
                    raise GoalNotFound
                goal.status = status
                goal.updated_at = _now()
            return goal

    async def archive_selected(self, context: AuthContext) -> Business:
        async with self._session_factory() as database:
            async with database.begin():
                business = await self._selected(database, context, lock=True)
                now = _now()
                business.archived_at = now
                business.updated_at = now
                await database.execute(
                    update(OwnerSession)
                    .where(
                        OwnerSession.owner_id == context.owner.id,
                        OwnerSession.selected_business_id == business.id,
                    )
                    .values(selected_business_id=None)
                )
            return business

    async def _selected(
        self, database: AsyncSession, context: AuthContext, *, lock: bool = False
    ) -> Business:
        query: Select[tuple[Business]] = (
            select(Business)
            .join(OwnerSession, OwnerSession.selected_business_id == Business.id)
            .where(
                OwnerSession.id == context.session.id,
                OwnerSession.owner_id == context.owner.id,
                Business.owner_id == context.owner.id,
                Business.archived_at.is_(None),
            )
        )
        if lock:
            query = query.with_for_update(of=Business)
        business = await database.scalar(query)
        if business is None:
            raise NoSelectedBusiness
        return business
