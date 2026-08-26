from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from foundora.agents.schema import AgentSchemaError, validate_schema
from foundora.agents.strategy import (
    BUSINESS_STRATEGIST_AGENT_ID,
    approved_profile_version,
    evidence_allowlists,
    validate_strategy_output,
)
from foundora.auth.service import AuthContext
from foundora.business.context import resolve_selected_business
from foundora.events.service import publish_event
from foundora.infrastructure.database import get_session_factory
from foundora.models import (
    AgentRun,
    AgentVersion,
    ApprovedBusinessProfile,
    ApprovedBusinessStrategy,
)


class StrategyRunNotFound(Exception):
    pass


class StrategyApprovalConflict(Exception):
    pass


class StrategyRunInvalid(Exception):
    pass


@dataclass(frozen=True)
class StrategyDashboard:
    business_id: uuid.UUID
    approved: ApprovedBusinessStrategy | None
    candidate_runs: list[AgentRun]


def _now() -> datetime:
    return datetime.now(UTC)


class StrategyService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()

    async def dashboard(self, context: AuthContext) -> StrategyDashboard:
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
            approved = await database.get(ApprovedBusinessStrategy, business.id)
            candidates = list(
                await database.scalars(
                    select(AgentRun)
                    .where(
                        AgentRun.business_id == business.id,
                        AgentRun.agent_id == BUSINESS_STRATEGIST_AGENT_ID,
                        AgentRun.status == "completed",
                    )
                    .order_by(desc(AgentRun.completed_at), desc(AgentRun.created_at))
                    .limit(20)
                )
            )
        return StrategyDashboard(business.id, approved, candidates)

    async def approve(
        self,
        context: AuthContext,
        *,
        run_id: uuid.UUID,
        expected_version: int,
    ) -> ApprovedBusinessStrategy:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                approved = await database.get(
                    ApprovedBusinessStrategy, business.id, with_for_update=True
                )
                current_version = approved.version if approved is not None else 0
                if expected_version != current_version:
                    raise StrategyApprovalConflict
                run = await database.scalar(
                    select(AgentRun)
                    .where(AgentRun.id == run_id, AgentRun.business_id == business.id)
                    .with_for_update()
                )
                if run is None:
                    raise StrategyRunNotFound
                if (
                    run.agent_id != BUSINESS_STRATEGIST_AGENT_ID
                    or run.status != "completed"
                    or not isinstance(run.structured_output, dict)
                ):
                    raise StrategyRunInvalid
                if approved is not None and approved.source_agent_run_id == run.id:
                    raise StrategyApprovalConflict
                version = await database.get(AgentVersion, run.agent_version_id)
                if version is None or version.agent_id != BUSINESS_STRATEGIST_AGENT_ID:
                    raise StrategyRunInvalid
                try:
                    validate_schema(run.structured_output, version.output_schema)
                    validate_strategy_output(
                        run.agent_id, run.structured_input, run.structured_output
                    )
                    source_profile_version = approved_profile_version(run.structured_input)
                    approved_refs, research_refs = evidence_allowlists(run.structured_input)
                except AgentSchemaError as error:
                    raise StrategyRunInvalid from error
                current_profile = await database.get(
                    ApprovedBusinessProfile, business.id, with_for_update=True
                )
                if current_profile is None or current_profile.version != source_profile_version:
                    raise StrategyRunInvalid
                now = _now()
                if approved is None:
                    approved = ApprovedBusinessStrategy(
                        business_id=business.id,
                        version=1,
                        source_agent_run_id=run.id,
                        source_profile_version=source_profile_version,
                        context_id=str(run.structured_input["context_id"]),
                        strategy=dict(run.structured_output),
                        evidence_refs={
                            "approved_fact_refs": sorted(approved_refs),
                            "research_finding_refs": sorted(research_refs),
                        },
                        approved_by_owner_id=context.owner.id,
                        approved_at=now,
                    )
                    database.add(approved)
                else:
                    approved.version += 1
                    approved.source_agent_run_id = run.id
                    approved.source_profile_version = source_profile_version
                    approved.context_id = str(run.structured_input["context_id"])
                    approved.strategy = dict(run.structured_output)
                    approved.evidence_refs = {
                        "approved_fact_refs": sorted(approved_refs),
                        "research_finding_refs": sorted(research_refs),
                    }
                    approved.approved_by_owner_id = context.owner.id
                    approved.approved_at = now
                await database.flush()
                await publish_event(
                    database,
                    business_id=business.id,
                    event_type="strategy.approved",
                    aggregate_type="business_strategy",
                    aggregate_id=str(business.id),
                    idempotency_key=f"strategy-approved:{business.id}:{approved.version}",
                    payload={
                        "business_id": str(business.id),
                        "strategy_version": approved.version,
                        "source_agent_run_id": str(run.id),
                        "source_profile_version": approved.source_profile_version,
                        "context_id": approved.context_id,
                    },
                    occurred_at=now,
                )
            return approved
