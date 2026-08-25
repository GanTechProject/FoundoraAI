from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from foundora.agents.product_offer import (
    PRODUCT_OFFER_AGENT_ID,
    offer_strategy_allowlist,
    strategy_item_references,
    validate_product_offer_output,
)
from foundora.agents.schema import AgentSchemaError, validate_schema
from foundora.auth.service import AuthContext
from foundora.business.context import resolve_selected_business
from foundora.events.service import publish_event
from foundora.infrastructure.database import get_session_factory
from foundora.models import (
    AgentRun,
    AgentVersion,
    ApprovedBusinessStrategy,
    ProductOfferVersion,
)


class ProductOfferRunNotFound(Exception):
    pass


class ProductOfferApprovalConflict(Exception):
    pass


class ProductOfferRunInvalid(Exception):
    pass


@dataclass(frozen=True)
class ProductOfferDashboard:
    business_id: uuid.UUID
    current: ProductOfferVersion | None
    versions: list[ProductOfferVersion]
    candidate_runs: list[AgentRun]


def _now() -> datetime:
    return datetime.now(UTC)


class ProductOfferService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()

    async def dashboard(self, context: AuthContext) -> ProductOfferDashboard:
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
            versions = list(
                await database.scalars(
                    select(ProductOfferVersion)
                    .where(ProductOfferVersion.business_id == business.id)
                    .order_by(desc(ProductOfferVersion.version))
                )
            )
            candidates = list(
                await database.scalars(
                    select(AgentRun)
                    .where(
                        AgentRun.business_id == business.id,
                        AgentRun.agent_id == PRODUCT_OFFER_AGENT_ID,
                        AgentRun.status == "completed",
                    )
                    .order_by(desc(AgentRun.completed_at), desc(AgentRun.created_at))
                    .limit(20)
                )
            )
        current = next((item for item in versions if item.status == "active"), None)
        return ProductOfferDashboard(business.id, current, versions, candidates)

    async def approve(
        self,
        context: AuthContext,
        *,
        run_id: uuid.UUID,
        expected_version: int,
    ) -> ProductOfferVersion:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                current = await database.scalar(
                    select(ProductOfferVersion)
                    .where(
                        ProductOfferVersion.business_id == business.id,
                        ProductOfferVersion.status == "active",
                    )
                    .with_for_update()
                )
                current_version = current.version if current is not None else 0
                if expected_version != current_version:
                    raise ProductOfferApprovalConflict
                run = await database.scalar(
                    select(AgentRun)
                    .where(AgentRun.id == run_id, AgentRun.business_id == business.id)
                    .with_for_update()
                )
                if run is None:
                    raise ProductOfferRunNotFound
                if (
                    run.agent_id != PRODUCT_OFFER_AGENT_ID
                    or run.status != "completed"
                    or not isinstance(run.structured_output, dict)
                ):
                    raise ProductOfferRunInvalid
                if current is not None and current.source_agent_run_id == run.id:
                    raise ProductOfferApprovalConflict
                version = await database.get(AgentVersion, run.agent_version_id)
                strategy = await database.get(ApprovedBusinessStrategy, business.id)
                if (
                    version is None
                    or version.agent_id != PRODUCT_OFFER_AGENT_ID
                    or strategy is None
                ):
                    raise ProductOfferRunInvalid
                try:
                    validate_schema(run.structured_input, version.input_schema)
                    validate_schema(run.structured_output, version.output_schema)
                    validate_product_offer_output(
                        run.agent_id, run.structured_input, run.structured_output
                    )
                    strategy_refs = offer_strategy_allowlist(run.structured_input)
                except AgentSchemaError as error:
                    raise ProductOfferRunInvalid from error
                evidence = run.structured_input.get("offer_evidence")
                expected_refs = strategy_item_references(
                    strategy.strategy, business.id, strategy.version
                )
                if not isinstance(evidence, dict) or (
                    evidence.get("strategy_version") != strategy.version
                    or evidence.get("strategy_source_agent_run_id")
                    != str(strategy.source_agent_run_id)
                    or evidence.get("strategy_context_id") != strategy.context_id
                    or evidence.get("approved_strategy") != strategy.strategy
                    or strategy_refs != expected_refs
                ):
                    raise ProductOfferRunInvalid

                now = _now()
                if current is not None:
                    current.status = "superseded"
                    current.superseded_at = now
                approved = ProductOfferVersion(
                    id=uuid.uuid4(),
                    business_id=business.id,
                    version=current_version + 1,
                    status="active",
                    source_agent_run_id=run.id,
                    source_strategy_version=strategy.version,
                    context_id=str(run.structured_input["context_id"]),
                    portfolio=dict(run.structured_output),
                    evidence_refs={"strategy_item_refs": sorted(strategy_refs)},
                    approved_by_owner_id=context.owner.id,
                    approved_at=now,
                    superseded_at=None,
                )
                database.add(approved)
                await database.flush()
                await publish_event(
                    database,
                    business_id=business.id,
                    event_type="product_offer.approved",
                    aggregate_type="product_offer_portfolio",
                    aggregate_id=str(approved.id),
                    idempotency_key=f"product-offer-approved:{business.id}:{approved.version}",
                    payload={
                        "business_id": str(business.id),
                        "portfolio_id": str(approved.id),
                        "portfolio_version": approved.version,
                        "source_agent_run_id": str(run.id),
                        "source_strategy_version": strategy.version,
                        "context_id": approved.context_id,
                    },
                    occurred_at=now,
                )
            return approved
