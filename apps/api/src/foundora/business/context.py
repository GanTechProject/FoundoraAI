from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from foundora.auth.service import AuthContext
from foundora.models import Business, OwnerSession


class NoSelectedBusiness(Exception):
    pass


async def resolve_selected_business(
    database: AsyncSession, context: AuthContext, *, lock: bool = False
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
