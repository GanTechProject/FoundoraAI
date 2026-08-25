from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from foundora.agents.brand import product_offer_references
from foundora.agents.product_offer import strategy_item_references
from foundora.agents.schema import AgentSchemaError, validate_schema
from foundora.agents.website_specification import (
    WEBSITE_SPECIFICATION_AGENT_ID,
    brand_system_references,
    validate_website_specification_output,
    website_specification_evidence_allowlists,
)
from foundora.auth.service import AuthContext
from foundora.business.context import resolve_selected_business
from foundora.events.service import publish_event
from foundora.infrastructure.database import get_session_factory
from foundora.models import (
    AgentRun,
    AgentVersion,
    ApprovedBusinessStrategy,
    BrandSystemVersion,
    ProductOfferVersion,
    WebsiteSpecificationVersion,
)


class WebsiteSpecificationRunNotFound(Exception):
    pass


class WebsiteSpecificationApprovalConflict(Exception):
    pass


class WebsiteSpecificationRunInvalid(Exception):
    pass


@dataclass(frozen=True)
class WebsiteSpecificationDashboard:
    business_id: uuid.UUID
    current: WebsiteSpecificationVersion | None
    versions: list[WebsiteSpecificationVersion]
    candidate_runs: list[AgentRun]


def _now() -> datetime:
    return datetime.now(UTC)


class WebsiteSpecificationService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()

    async def dashboard(self, context: AuthContext) -> WebsiteSpecificationDashboard:
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
            versions = list(
                await database.scalars(
                    select(WebsiteSpecificationVersion)
                    .where(WebsiteSpecificationVersion.business_id == business.id)
                    .order_by(desc(WebsiteSpecificationVersion.version))
                )
            )
            candidates = list(
                await database.scalars(
                    select(AgentRun)
                    .where(
                        AgentRun.business_id == business.id,
                        AgentRun.agent_id == WEBSITE_SPECIFICATION_AGENT_ID,
                        AgentRun.status == "completed",
                    )
                    .order_by(desc(AgentRun.completed_at), desc(AgentRun.created_at))
                    .limit(20)
                )
            )
        current = next((item for item in versions if item.status == "active"), None)
        return WebsiteSpecificationDashboard(business.id, current, versions, candidates)

    async def approve(
        self,
        context: AuthContext,
        *,
        run_id: uuid.UUID,
        expected_version: int,
    ) -> WebsiteSpecificationVersion:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                current = await database.scalar(
                    select(WebsiteSpecificationVersion)
                    .where(
                        WebsiteSpecificationVersion.business_id == business.id,
                        WebsiteSpecificationVersion.status == "active",
                    )
                    .with_for_update()
                )
                current_version = current.version if current is not None else 0
                if expected_version != current_version:
                    raise WebsiteSpecificationApprovalConflict
                run = await database.scalar(
                    select(AgentRun)
                    .where(AgentRun.id == run_id, AgentRun.business_id == business.id)
                    .with_for_update()
                )
                if run is None:
                    raise WebsiteSpecificationRunNotFound
                if (
                    run.agent_id != WEBSITE_SPECIFICATION_AGENT_ID
                    or run.status != "completed"
                    or not isinstance(run.structured_output, dict)
                ):
                    raise WebsiteSpecificationRunInvalid
                if current is not None and current.source_agent_run_id == run.id:
                    raise WebsiteSpecificationApprovalConflict

                version = await database.get(AgentVersion, run.agent_version_id)
                strategy = await database.get(ApprovedBusinessStrategy, business.id)
                product_offer = await database.scalar(
                    select(ProductOfferVersion)
                    .where(
                        ProductOfferVersion.business_id == business.id,
                        ProductOfferVersion.status == "active",
                    )
                    .with_for_update()
                )
                brand = await database.scalar(
                    select(BrandSystemVersion)
                    .where(
                        BrandSystemVersion.business_id == business.id,
                        BrandSystemVersion.status == "active",
                    )
                    .with_for_update()
                )
                if (
                    version is None
                    or version.agent_id != WEBSITE_SPECIFICATION_AGENT_ID
                    or strategy is None
                    or product_offer is None
                    or brand is None
                    or product_offer.source_strategy_version != strategy.version
                    or brand.source_strategy_version != strategy.version
                    or brand.source_product_offer_id != product_offer.id
                    or brand.source_product_offer_version != product_offer.version
                ):
                    raise WebsiteSpecificationRunInvalid
                try:
                    validate_schema(run.structured_input, version.input_schema)
                    validate_schema(run.structured_output, version.output_schema)
                    validate_website_specification_output(
                        run.agent_id, run.structured_input, run.structured_output
                    )
                    strategy_refs, offer_refs, brand_refs = (
                        website_specification_evidence_allowlists(run.structured_input)
                    )
                except AgentSchemaError as error:
                    raise WebsiteSpecificationRunInvalid from error

                evidence = run.structured_input.get("website_specification_evidence")
                expected_strategy_refs = strategy_item_references(
                    strategy.strategy, business.id, strategy.version
                )
                expected_offer_refs = product_offer_references(
                    product_offer.portfolio, product_offer.id, product_offer.version
                )
                expected_brand_refs = brand_system_references(
                    brand.brand_system, brand.id, brand.version
                )
                if not isinstance(evidence, dict) or (
                    evidence.get("strategy_version") != strategy.version
                    or evidence.get("strategy_source_agent_run_id")
                    != str(strategy.source_agent_run_id)
                    or evidence.get("strategy_context_id") != strategy.context_id
                    or evidence.get("approved_strategy") != strategy.strategy
                    or evidence.get("product_offer_id") != str(product_offer.id)
                    or evidence.get("product_offer_version") != product_offer.version
                    or evidence.get("product_offer_source_agent_run_id")
                    != str(product_offer.source_agent_run_id)
                    or evidence.get("product_offer_context_id") != product_offer.context_id
                    or evidence.get("approved_product_offer") != product_offer.portfolio
                    or evidence.get("brand_system_id") != str(brand.id)
                    or evidence.get("brand_version") != brand.version
                    or evidence.get("brand_source_agent_run_id") != str(brand.source_agent_run_id)
                    or evidence.get("brand_context_id") != brand.context_id
                    or evidence.get("approved_brand_system") != brand.brand_system
                    or strategy_refs != expected_strategy_refs
                    or offer_refs != expected_offer_refs
                    or brand_refs != expected_brand_refs
                ):
                    raise WebsiteSpecificationRunInvalid

                now = _now()
                if current is not None:
                    current.status = "superseded"
                    current.superseded_at = now
                approved = WebsiteSpecificationVersion(
                    id=uuid.uuid4(),
                    business_id=business.id,
                    version=current_version + 1,
                    status="active",
                    source_agent_run_id=run.id,
                    source_strategy_version=strategy.version,
                    source_product_offer_id=product_offer.id,
                    source_product_offer_version=product_offer.version,
                    source_brand_system_id=brand.id,
                    source_brand_version=brand.version,
                    context_id=str(run.structured_input["context_id"]),
                    specification=dict(run.structured_output),
                    evidence_refs={
                        "strategy_item_refs": sorted(strategy_refs),
                        "product_offer_refs": sorted(offer_refs),
                        "brand_item_refs": sorted(brand_refs),
                    },
                    approved_by_owner_id=context.owner.id,
                    approved_at=now,
                    superseded_at=None,
                )
                database.add(approved)
                await database.flush()
                await publish_event(
                    database,
                    business_id=business.id,
                    event_type="website_specification.approved",
                    aggregate_type="website_specification",
                    aggregate_id=str(approved.id),
                    idempotency_key=(
                        f"website-specification-approved:{business.id}:{approved.version}"
                    ),
                    payload={
                        "business_id": str(business.id),
                        "website_specification_id": str(approved.id),
                        "website_specification_version": approved.version,
                        "source_agent_run_id": str(run.id),
                        "source_strategy_version": strategy.version,
                        "source_product_offer_id": str(product_offer.id),
                        "source_product_offer_version": product_offer.version,
                        "source_brand_system_id": str(brand.id),
                        "source_brand_version": brand.version,
                        "context_id": approved.context_id,
                    },
                    occurred_at=now,
                )
            return approved
