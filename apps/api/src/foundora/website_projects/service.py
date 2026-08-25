from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from foundora.agents.website_coding import WEBSITE_CODING_AGENT_ID
from foundora.auth.service import AuthContext
from foundora.business.context import resolve_selected_business
from foundora.infrastructure.database import get_session_factory
from foundora.models import AgentRun, WebsiteProjectVersion, WebsiteSpecificationVersion


@dataclass(frozen=True)
class WebsiteProjectDashboard:
    business_id: uuid.UUID
    current_specification: WebsiteSpecificationVersion | None
    current_project: WebsiteProjectVersion | None
    history: list[WebsiteProjectVersion]
    recent_runs: list[AgentRun]
    next_operation: str | None
    blocker: str | None


class WebsiteProjectService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()

    async def dashboard(self, context: AuthContext) -> WebsiteProjectDashboard:
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
            specification = await database.scalar(
                select(WebsiteSpecificationVersion).where(
                    WebsiteSpecificationVersion.business_id == business.id,
                    WebsiteSpecificationVersion.status == "active",
                )
            )
            history = list(
                await database.scalars(
                    select(WebsiteProjectVersion)
                    .where(WebsiteProjectVersion.business_id == business.id)
                    .order_by(desc(WebsiteProjectVersion.version))
                )
            )
            recent_runs = list(
                await database.scalars(
                    select(AgentRun)
                    .where(
                        AgentRun.business_id == business.id,
                        AgentRun.agent_id == WEBSITE_CODING_AGENT_ID,
                    )
                    .order_by(desc(AgentRun.created_at))
                    .limit(50)
                )
            )
        current = next((item for item in history if item.status == "active"), None)
        if specification is None:
            next_operation = None
            blocker = "Approve a complete current website specification before generating code."
        elif (
            current is not None
            and current.source_website_specification_id == specification.id
            and current.source_website_specification_version == specification.version
        ):
            next_operation = "modify"
            blocker = None
        else:
            next_operation = "generate"
            blocker = None
        return WebsiteProjectDashboard(
            business_id=business.id,
            current_specification=specification,
            current_project=current,
            history=history,
            recent_runs=recent_runs,
            next_operation=next_operation,
            blocker=blocker,
        )
