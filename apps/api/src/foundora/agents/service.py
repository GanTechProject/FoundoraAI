from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from redis import Redis
from rq import Queue
from rq.job import JobStatus
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from foundora.agents.brand import (
    BRAND_STRATEGIST_AGENT_ID,
    product_offer_references,
)
from foundora.agents.product_offer import PRODUCT_OFFER_AGENT_ID, strategy_item_references
from foundora.agents.research import RESEARCH_AGENT_IDS, validate_research_output
from foundora.agents.schema import AgentSchemaError, validate_schema
from foundora.agents.strategy import BUSINESS_STRATEGIST_AGENT_ID
from foundora.agents.website_coding import (
    WEBSITE_BUILD_SKILL_ID,
    WEBSITE_CODING_AGENT_ID,
    specification_item_references,
)
from foundora.agents.website_specification import (
    WEBSITE_SPECIFICATION_AGENT_ID,
    brand_system_references,
)
from foundora.auth.service import AuthContext
from foundora.business.context import resolve_selected_business
from foundora.business_brain.service import (
    SOURCE_TYPES,
    ContextBuildRequest,
    ContextService,
)
from foundora.config import get_settings
from foundora.infrastructure.database import get_session_factory
from foundora.models import (
    Agent,
    AgentMessage,
    AgentRun,
    AgentSkillAssignment,
    AgentVersion,
    ApprovedBusinessStrategy,
    BrandSystemVersion,
    ModelGatewayCall,
    ProductOfferVersion,
    Skill,
    SkillVersion,
    WebsiteProjectVersion,
    WebsiteSpecificationVersion,
)
from foundora.search.provider import (
    RegisteredKnowledgeSearchProvider,
    SearchEvidence,
    SearchProvider,
    SearchRequest,
)

logger = logging.getLogger(__name__)
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


class AgentNotFound(Exception):
    pass


class AgentRunNotFound(Exception):
    pass


class AgentRunNotCancellable(Exception):
    pass


class SkillNotAssigned(Exception):
    pass


class ResearchQueryInvalid(Exception):
    pass


class ResearchSearchUnavailable(Exception):
    pass


class StrategyEvidenceInvalid(Exception):
    pass


class ProductOfferEvidenceInvalid(Exception):
    pass


class BrandEvidenceInvalid(Exception):
    pass


class WebsiteSpecificationEvidenceInvalid(Exception):
    pass


class WebsiteCodingEvidenceInvalid(Exception):
    pass


class AgentQueueUnavailable(Exception):
    def __init__(self, run_id: uuid.UUID) -> None:
        self.run_id = run_id
        super().__init__("Agent run could not be queued")


@dataclass(frozen=True)
class AgentDefinitionRecord:
    agent: Agent
    version: AgentVersion
    assigned_skills: list[SkillVersion]


@dataclass(frozen=True)
class SkillDefinitionRecord:
    skill: Skill
    version: SkillVersion


@dataclass(frozen=True)
class AgentRunRecord:
    run: AgentRun
    version: AgentVersion
    skill_version: SkillVersion | None
    messages: list[AgentMessage]
    gateway_calls: list[ModelGatewayCall]


@dataclass(frozen=True)
class AgentDashboard:
    business_id: uuid.UUID
    definitions: list[AgentDefinitionRecord]
    skills: list[SkillDefinitionRecord]
    runs: list[AgentRunRecord]


@dataclass(frozen=True)
class ResearchSearchRecord:
    provider: str
    query: str
    evidence: list[SearchEvidence]


def _now() -> datetime:
    return datetime.now(UTC)


def _agent_job_id(run_id: uuid.UUID, worker_recovery_count: int) -> str:
    base = f"agent-run-{run_id}"
    return base if worker_recovery_count == 0 else f"{base}-recovery-{worker_recovery_count}"


def _enqueue_sync(run_id: uuid.UUID, worker_recovery_count: int = 0) -> None:
    settings = get_settings()
    connection = Redis.from_url(
        settings.redis_url,
        decode_responses=False,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    try:
        queue = Queue(settings.worker_queue, connection=connection)
        job_id = _agent_job_id(run_id, worker_recovery_count)
        existing = queue.fetch_job(job_id)
        if existing is not None:
            active_statuses = {
                JobStatus.QUEUED,
                JobStatus.STARTED,
                JobStatus.DEFERRED,
                JobStatus.SCHEDULED,
            }
            if existing.get_status(refresh=True) in active_statuses:
                return
            existing.delete(remove_from_queue=True)
        queue.enqueue(
            "foundora.agents.jobs.execute_agent_run",
            str(run_id),
            job_id=job_id,
            job_timeout=300,
            result_ttl=0,
            failure_ttl=86_400,
        )
    finally:
        connection.close()


async def enqueue_agent_run(run_id: uuid.UUID) -> None:
    await asyncio.to_thread(_enqueue_sync, run_id)


class AgentService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        context_service: ContextService | None = None,
        search_provider: SearchProvider | None = None,
        enqueue: Callable[[uuid.UUID], Awaitable[None]] = enqueue_agent_run,
    ) -> None:
        self._session_factory = session_factory or get_session_factory()
        self._context_service = context_service or ContextService(self._session_factory)
        self._search_provider = search_provider or RegisteredKnowledgeSearchProvider(
            self._session_factory
        )
        self._enqueue = enqueue

    async def search_research_evidence(
        self, context: AuthContext, query: str
    ) -> ResearchSearchRecord:
        normalized_query = " ".join(query.strip().split())
        if not normalized_query or len(normalized_query) > 500:
            raise ResearchQueryInvalid
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
        try:
            evidence = await self._search_provider.search(
                SearchRequest(business_id=business.id, query=normalized_query)
            )
        except Exception as error:
            logger.exception(
                "Research evidence preview failed",
                extra={
                    "event": "agent.research.preview_failed",
                    "business_id": str(business.id),
                },
            )
            raise ResearchSearchUnavailable from error
        return ResearchSearchRecord(
            provider=self._search_provider.provider_id,
            query=normalized_query,
            evidence=evidence,
        )

    async def dashboard(self, context: AuthContext) -> AgentDashboard:
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
            definition_rows = (
                await database.execute(
                    select(Agent, AgentVersion)
                    .join(
                        AgentVersion,
                        and_(
                            AgentVersion.agent_id == Agent.id,
                            AgentVersion.version == Agent.current_version,
                        ),
                    )
                    .order_by(Agent.id)
                )
            ).all()
            skill_rows = (
                await database.execute(
                    select(Skill, SkillVersion)
                    .join(
                        SkillVersion,
                        and_(
                            SkillVersion.skill_id == Skill.id,
                            SkillVersion.version == Skill.current_version,
                        ),
                    )
                    .order_by(Skill.id)
                )
            ).all()
            version_ids = [version.id for _, version in definition_rows]
            assigned_by_agent_version: dict[uuid.UUID, list[SkillVersion]] = {
                version_id: [] for version_id in version_ids
            }
            if version_ids:
                assignment_rows = (
                    await database.execute(
                        select(AgentSkillAssignment.agent_version_id, SkillVersion)
                        .join(
                            SkillVersion,
                            SkillVersion.id == AgentSkillAssignment.skill_version_id,
                        )
                        .where(AgentSkillAssignment.agent_version_id.in_(version_ids))
                        .order_by(SkillVersion.skill_id, SkillVersion.version)
                    )
                ).all()
                for agent_version_id, assigned_version in assignment_rows:
                    assigned_by_agent_version[agent_version_id].append(assigned_version)
            run_rows = (
                await database.execute(
                    select(AgentRun, AgentVersion, SkillVersion)
                    .join(AgentVersion, AgentVersion.id == AgentRun.agent_version_id)
                    .outerjoin(SkillVersion, SkillVersion.id == AgentRun.skill_version_id)
                    .where(AgentRun.business_id == business.id)
                    .order_by(desc(AgentRun.created_at))
                    .limit(20)
                )
            ).all()
            run_ids = [run.id for run, _, _ in run_rows]
            calls_by_run: dict[uuid.UUID, list[ModelGatewayCall]] = {
                run_id: [] for run_id in run_ids
            }
            if run_ids:
                calls = list(
                    await database.scalars(
                        select(ModelGatewayCall)
                        .where(ModelGatewayCall.agent_run_id.in_(run_ids))
                        .order_by(
                            ModelGatewayCall.created_at,
                            ModelGatewayCall.attempt_number,
                        )
                    )
                )
                for call in calls:
                    if call.agent_run_id is not None:
                        calls_by_run[call.agent_run_id].append(call)
        return AgentDashboard(
            business_id=business.id,
            definitions=[
                AgentDefinitionRecord(
                    agent=agent,
                    version=version,
                    assigned_skills=assigned_by_agent_version.get(version.id, []),
                )
                for agent, version in definition_rows
            ],
            skills=[
                SkillDefinitionRecord(skill=skill, version=version) for skill, version in skill_rows
            ],
            runs=[
                AgentRunRecord(
                    run=run,
                    version=version,
                    skill_version=skill_version,
                    messages=[],
                    gateway_calls=calls_by_run.get(run.id, []),
                )
                for run, version, skill_version in run_rows
            ],
        )

    async def create_run(
        self,
        context: AuthContext,
        agent_id: str,
        objective: str,
        skill_id: str | None = None,
        skill_input: dict[str, object] | None = None,
        research_query: str | None = None,
        research_run_ids: list[uuid.UUID] | None = None,
    ) -> AgentRunRecord:
        skill_version: SkillVersion | None = None
        normalized_skill_input = skill_input or {}
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
            row = (
                await database.execute(
                    select(Agent, AgentVersion)
                    .join(
                        AgentVersion,
                        and_(
                            AgentVersion.agent_id == Agent.id,
                            AgentVersion.version == Agent.current_version,
                        ),
                    )
                    .where(Agent.id == agent_id, Agent.enabled.is_(True))
                )
            ).one_or_none()
            if row is None:
                raise AgentNotFound
            agent, version = row
            if skill_id is not None:
                skill_row = (
                    await database.execute(
                        select(Skill, SkillVersion)
                        .join(
                            SkillVersion,
                            and_(
                                SkillVersion.skill_id == Skill.id,
                                SkillVersion.version == Skill.current_version,
                            ),
                        )
                        .join(
                            AgentSkillAssignment,
                            and_(
                                AgentSkillAssignment.skill_version_id == SkillVersion.id,
                                AgentSkillAssignment.agent_version_id == version.id,
                            ),
                        )
                        .where(Skill.id == skill_id, Skill.enabled.is_(True))
                    )
                ).one_or_none()
                if (
                    skill_row is None
                    or skill_id not in version.allowed_skills
                    or agent.id not in skill_row[1].compatible_agents
                ):
                    raise SkillNotAssigned
                _, skill_version = skill_row
                validate_schema(normalized_skill_input, skill_version.input_schema)
            elif normalized_skill_input:
                raise SkillNotAssigned

        normalized_research_query = (
            " ".join(research_query.strip().split()) if research_query is not None else None
        )
        if agent.id in RESEARCH_AGENT_IDS:
            if not normalized_research_query or len(normalized_research_query) > 500:
                raise ResearchQueryInvalid
        elif normalized_research_query is not None:
            raise ResearchQueryInvalid

        selected_research_run_ids = research_run_ids or []
        if agent.id == BUSINESS_STRATEGIST_AGENT_ID:
            if len(selected_research_run_ids) != len(RESEARCH_AGENT_IDS) or len(
                set(selected_research_run_ids)
            ) != len(RESEARCH_AGENT_IDS):
                raise StrategyEvidenceInvalid
        elif selected_research_run_ids:
            raise StrategyEvidenceInvalid

        if agent.id == WEBSITE_CODING_AGENT_ID:
            operation = normalized_skill_input.get("operation")
            if (
                skill_version is None
                or skill_version.skill_id != WEBSITE_BUILD_SKILL_ID
                or operation not in {"generate", "modify"}
            ):
                raise WebsiteCodingEvidenceInvalid

        policy = version.model_policy
        context_budget = policy.get("context_token_budget")
        if not isinstance(context_budget, int) or isinstance(context_budget, bool):
            raise AgentNotFound
        allowed_sources = version.data_access_scope.get("sources")
        if not isinstance(allowed_sources, list):
            raise AgentNotFound
        selected_sources = frozenset(source for source in SOURCE_TYPES if source in allowed_sources)
        business_context = await self._context_service.build(
            context,
            ContextBuildRequest(
                purpose="agent_runtime",
                token_budget=context_budget,
                selected_source_types=selected_sources,
            ),
        )
        compiled_context = json.loads(business_context.context)
        if not isinstance(compiled_context, dict):
            raise AgentNotFound
        structured_input: dict[str, object] = {
            "objective": objective,
            "business_context": compiled_context,
            "context_id": business_context.context_id,
            "context_sha256": business_context.context_sha256,
        }
        if agent.id == BUSINESS_STRATEGIST_AGENT_ID:
            sources = compiled_context.get("sources")
            approved_fact_refs = (
                sorted(
                    {
                        reference
                        for item in sources
                        if isinstance(sources, list)
                        and isinstance(item, dict)
                        and item.get("authority")
                        in {"founder_approved_onboarding", "founder_approved_fact"}
                        and isinstance((reference := item.get("source_reference")), str)
                    }
                )
                if isinstance(sources, list)
                else []
            )
            if not approved_fact_refs:
                raise StrategyEvidenceInvalid
            profile_versions: set[int] = set()
            if isinstance(sources, list):
                for item in sources:
                    if (
                        isinstance(item, dict)
                        and item.get("authority") == "founder_approved_onboarding"
                        and item.get("source_reference")
                        == f"approved_business_profiles/{business.id}"
                    ):
                        try:
                            profile_versions.add(int(str(item.get("source_version"))))
                        except ValueError as error:
                            raise StrategyEvidenceInvalid from error
            if len(profile_versions) != 1 or next(iter(profile_versions)) <= 0:
                raise StrategyEvidenceInvalid
            approved_profile_version = next(iter(profile_versions))
            async with self._session_factory() as database:
                research_rows = list(
                    (
                        await database.execute(
                            select(AgentRun, AgentVersion)
                            .join(AgentVersion, AgentVersion.id == AgentRun.agent_version_id)
                            .where(
                                AgentRun.id.in_(selected_research_run_ids),
                                AgentRun.business_id == business.id,
                                AgentRun.status == "completed",
                                AgentRun.agent_id.in_(RESEARCH_AGENT_IDS),
                            )
                        )
                    ).all()
                )
            if {run.agent_id for run, _ in research_rows} != set(RESEARCH_AGENT_IDS):
                raise StrategyEvidenceInvalid
            pinned_runs: list[dict[str, object]] = []
            for research_run, research_version in sorted(
                research_rows, key=lambda row: row[0].agent_id
            ):
                output = research_run.structured_output
                if not isinstance(output, dict):
                    raise StrategyEvidenceInvalid
                try:
                    validate_schema(research_run.structured_input, research_version.input_schema)
                    validate_schema(output, research_version.output_schema)
                    validate_research_output(
                        research_run.agent_id, research_run.structured_input, output
                    )
                except AgentSchemaError as error:
                    raise StrategyEvidenceInvalid from error
                supported_refs = [
                    f"agent_runs/{research_run.id}/findings/{finding.get('finding_id')}"
                    for finding in output.get("findings", [])
                    if isinstance(finding, dict) and finding.get("supported") is True
                ]
                if not supported_refs:
                    raise StrategyEvidenceInvalid
                pinned_runs.append(
                    {
                        "run_id": str(research_run.id),
                        "agent_id": research_run.agent_id,
                        "agent_version_id": str(research_version.id),
                        "agent_version": research_version.version,
                        "context_id": research_run.structured_input.get("context_id"),
                        "research_query": output.get("research_query"),
                        "supported_finding_refs": supported_refs,
                        "output": output,
                    }
                )
            structured_input["strategy_evidence"] = {
                "approved_profile_version": approved_profile_version,
                "approved_fact_refs": approved_fact_refs,
                "research_runs": pinned_runs,
            }
        if agent.id == PRODUCT_OFFER_AGENT_ID:
            async with self._session_factory() as database:
                approved_strategy = await database.get(ApprovedBusinessStrategy, business.id)
            if approved_strategy is None:
                raise ProductOfferEvidenceInvalid
            strategy_refs = strategy_item_references(
                approved_strategy.strategy, business.id, approved_strategy.version
            )
            if not strategy_refs:
                raise ProductOfferEvidenceInvalid
            sources = compiled_context.get("sources")
            source_items = sources if isinstance(sources, list) else []
            pinned_context_strategy = next(
                (
                    item
                    for item in source_items
                    if isinstance(item, dict)
                    and item.get("authority") == "founder_approved_strategy"
                ),
                None,
            )
            pinned_content = (
                pinned_context_strategy.get("content")
                if isinstance(pinned_context_strategy, dict)
                else None
            )
            if (
                not isinstance(pinned_context_strategy, dict)
                or pinned_context_strategy.get("source_version") != str(approved_strategy.version)
                or not isinstance(pinned_content, dict)
                or pinned_content.get("source_agent_run_id")
                != str(approved_strategy.source_agent_run_id)
                or pinned_content.get("strategy") != approved_strategy.strategy
            ):
                raise ProductOfferEvidenceInvalid
            structured_input["offer_evidence"] = {
                "strategy_version": approved_strategy.version,
                "strategy_source_agent_run_id": str(approved_strategy.source_agent_run_id),
                "strategy_context_id": approved_strategy.context_id,
                "strategy_item_refs": sorted(strategy_refs),
                "approved_strategy": approved_strategy.strategy,
            }
        if agent.id == BRAND_STRATEGIST_AGENT_ID:
            async with self._session_factory() as database:
                approved_strategy = await database.get(ApprovedBusinessStrategy, business.id)
                approved_product_offer = await database.scalar(
                    select(ProductOfferVersion).where(
                        ProductOfferVersion.business_id == business.id,
                        ProductOfferVersion.status == "active",
                    )
                )
            if (
                approved_strategy is None
                or approved_product_offer is None
                or approved_product_offer.source_strategy_version != approved_strategy.version
            ):
                raise BrandEvidenceInvalid
            strategy_refs = strategy_item_references(
                approved_strategy.strategy, business.id, approved_strategy.version
            )
            offer_refs = product_offer_references(
                approved_product_offer.portfolio,
                approved_product_offer.id,
                approved_product_offer.version,
            )
            if not strategy_refs or not offer_refs:
                raise BrandEvidenceInvalid
            sources = compiled_context.get("sources")
            source_items = sources if isinstance(sources, list) else []
            strategy_source = next(
                (
                    item
                    for item in source_items
                    if isinstance(item, dict)
                    and item.get("authority") == "founder_approved_strategy"
                ),
                None,
            )
            offer_source = next(
                (
                    item
                    for item in source_items
                    if isinstance(item, dict)
                    and item.get("authority") == "founder_approved_product_offer"
                ),
                None,
            )
            strategy_content = (
                strategy_source.get("content") if isinstance(strategy_source, dict) else None
            )
            offer_content = offer_source.get("content") if isinstance(offer_source, dict) else None
            if (
                not isinstance(strategy_source, dict)
                or strategy_source.get("source_version") != str(approved_strategy.version)
                or not isinstance(strategy_content, dict)
                or strategy_content.get("strategy") != approved_strategy.strategy
                or not isinstance(offer_source, dict)
                or offer_source.get("source_version") != str(approved_product_offer.version)
                or not isinstance(offer_content, dict)
                or offer_content.get("portfolio_id") != str(approved_product_offer.id)
                or offer_content.get("portfolio") != approved_product_offer.portfolio
            ):
                raise BrandEvidenceInvalid
            structured_input["brand_evidence"] = {
                "strategy_version": approved_strategy.version,
                "strategy_source_agent_run_id": str(approved_strategy.source_agent_run_id),
                "strategy_context_id": approved_strategy.context_id,
                "strategy_item_refs": sorted(strategy_refs),
                "approved_strategy": approved_strategy.strategy,
                "product_offer_id": str(approved_product_offer.id),
                "product_offer_version": approved_product_offer.version,
                "product_offer_source_agent_run_id": str(
                    approved_product_offer.source_agent_run_id
                ),
                "product_offer_context_id": approved_product_offer.context_id,
                "product_offer_refs": sorted(offer_refs),
                "approved_product_offer": approved_product_offer.portfolio,
            }
        if agent.id == WEBSITE_SPECIFICATION_AGENT_ID:
            async with self._session_factory() as database:
                approved_strategy = await database.get(ApprovedBusinessStrategy, business.id)
                approved_product_offer = await database.scalar(
                    select(ProductOfferVersion).where(
                        ProductOfferVersion.business_id == business.id,
                        ProductOfferVersion.status == "active",
                    )
                )
                approved_brand = await database.scalar(
                    select(BrandSystemVersion).where(
                        BrandSystemVersion.business_id == business.id,
                        BrandSystemVersion.status == "active",
                    )
                )
            if (
                approved_strategy is None
                or approved_product_offer is None
                or approved_brand is None
                or approved_product_offer.source_strategy_version != approved_strategy.version
                or approved_brand.source_strategy_version != approved_strategy.version
                or approved_brand.source_product_offer_id != approved_product_offer.id
                or approved_brand.source_product_offer_version != approved_product_offer.version
            ):
                raise WebsiteSpecificationEvidenceInvalid
            strategy_refs = strategy_item_references(
                approved_strategy.strategy, business.id, approved_strategy.version
            )
            offer_refs = product_offer_references(
                approved_product_offer.portfolio,
                approved_product_offer.id,
                approved_product_offer.version,
            )
            brand_refs = brand_system_references(
                approved_brand.brand_system, approved_brand.id, approved_brand.version
            )
            if not strategy_refs or not offer_refs or not brand_refs:
                raise WebsiteSpecificationEvidenceInvalid
            sources = compiled_context.get("sources")
            source_items = sources if isinstance(sources, list) else []

            def source_with_authority(authority: str) -> dict[str, object] | None:
                return next(
                    (
                        item
                        for item in source_items
                        if isinstance(item, dict) and item.get("authority") == authority
                    ),
                    None,
                )

            strategy_source = source_with_authority("founder_approved_strategy")
            offer_source = source_with_authority("founder_approved_product_offer")
            brand_source = source_with_authority("founder_approved_brand_system")
            strategy_content = (
                strategy_source.get("content") if isinstance(strategy_source, dict) else None
            )
            offer_content = offer_source.get("content") if isinstance(offer_source, dict) else None
            brand_content = brand_source.get("content") if isinstance(brand_source, dict) else None
            if (
                not isinstance(strategy_source, dict)
                or strategy_source.get("source_version") != str(approved_strategy.version)
                or not isinstance(strategy_content, dict)
                or strategy_content.get("source_agent_run_id")
                != str(approved_strategy.source_agent_run_id)
                or strategy_content.get("strategy") != approved_strategy.strategy
                or not isinstance(offer_source, dict)
                or offer_source.get("source_version") != str(approved_product_offer.version)
                or not isinstance(offer_content, dict)
                or offer_content.get("portfolio_id") != str(approved_product_offer.id)
                or offer_content.get("source_agent_run_id")
                != str(approved_product_offer.source_agent_run_id)
                or offer_content.get("portfolio") != approved_product_offer.portfolio
                or not isinstance(brand_source, dict)
                or brand_source.get("source_version") != str(approved_brand.version)
                or not isinstance(brand_content, dict)
                or brand_content.get("brand_system_id") != str(approved_brand.id)
                or brand_content.get("source_agent_run_id")
                != str(approved_brand.source_agent_run_id)
                or brand_content.get("brand_system") != approved_brand.brand_system
            ):
                raise WebsiteSpecificationEvidenceInvalid
            structured_input["website_specification_evidence"] = {
                "strategy_version": approved_strategy.version,
                "strategy_source_agent_run_id": str(approved_strategy.source_agent_run_id),
                "strategy_context_id": approved_strategy.context_id,
                "strategy_item_refs": sorted(strategy_refs),
                "approved_strategy": approved_strategy.strategy,
                "product_offer_id": str(approved_product_offer.id),
                "product_offer_version": approved_product_offer.version,
                "product_offer_source_agent_run_id": str(
                    approved_product_offer.source_agent_run_id
                ),
                "product_offer_context_id": approved_product_offer.context_id,
                "product_offer_refs": sorted(offer_refs),
                "approved_product_offer": approved_product_offer.portfolio,
                "brand_system_id": str(approved_brand.id),
                "brand_version": approved_brand.version,
                "brand_source_agent_run_id": str(approved_brand.source_agent_run_id),
                "brand_context_id": approved_brand.context_id,
                "brand_item_refs": sorted(brand_refs),
                "approved_brand_system": approved_brand.brand_system,
            }
        if agent.id == WEBSITE_CODING_AGENT_ID:
            async with self._session_factory() as database:
                approved_specification = await database.scalar(
                    select(WebsiteSpecificationVersion).where(
                        WebsiteSpecificationVersion.business_id == business.id,
                        WebsiteSpecificationVersion.status == "active",
                    )
                )
                current_project = await database.scalar(
                    select(WebsiteProjectVersion).where(
                        WebsiteProjectVersion.business_id == business.id,
                        WebsiteProjectVersion.status == "active",
                    )
                )
            if approved_specification is None:
                raise WebsiteCodingEvidenceInvalid
            specification_refs = specification_item_references(
                approved_specification.specification,
                str(approved_specification.id),
                approved_specification.version,
            )
            if not specification_refs:
                raise WebsiteCodingEvidenceInvalid
            sources = compiled_context.get("sources")
            source_items = sources if isinstance(sources, list) else []
            specification_source = next(
                (
                    item
                    for item in source_items
                    if isinstance(item, dict)
                    and item.get("authority") == "founder_approved_website_specification"
                ),
                None,
            )
            source_content = (
                specification_source.get("content")
                if isinstance(specification_source, dict)
                else None
            )
            if (
                not isinstance(specification_source, dict)
                or specification_source.get("source_version") != str(approved_specification.version)
                or not isinstance(source_content, dict)
                or source_content.get("website_specification_id") != str(approved_specification.id)
                or source_content.get("source_agent_run_id")
                != str(approved_specification.source_agent_run_id)
                or source_content.get("specification") != approved_specification.specification
            ):
                raise WebsiteCodingEvidenceInvalid
            operation = normalized_skill_input.get("operation")
            aligned_current = (
                current_project is not None
                and current_project.source_website_specification_id == approved_specification.id
                and current_project.source_website_specification_version
                == approved_specification.version
            )
            requested_base_version = normalized_skill_input.get("base_project_version")
            if operation == "generate" and aligned_current:
                raise WebsiteCodingEvidenceInvalid
            if operation == "modify" and (
                not aligned_current
                or not isinstance(requested_base_version, int)
                or isinstance(requested_base_version, bool)
                or current_project is None
                or current_project.version != requested_base_version
            ):
                raise WebsiteCodingEvidenceInvalid
            base_project = None
            if operation == "modify" and current_project is not None:
                base_project = {
                    "project_id": str(current_project.id),
                    "project_version": current_project.version,
                    "source_website_specification_id": str(
                        current_project.source_website_specification_id
                    ),
                    "source_website_specification_version": (
                        current_project.source_website_specification_version
                    ),
                    "source_digest": current_project.source_digest,
                    "build_digest": current_project.build_digest,
                    "dependency_manifest": current_project.dependency_manifest,
                    "source_files": current_project.source_files,
                }
            coding_evidence: dict[str, object] = {
                "website_specification_id": str(approved_specification.id),
                "website_specification_version": approved_specification.version,
                "website_specification_source_agent_run_id": str(
                    approved_specification.source_agent_run_id
                ),
                "website_specification_context_id": approved_specification.context_id,
                "specification_item_refs": sorted(specification_refs),
                "approved_website_specification": approved_specification.specification,
                "requested_operation": operation,
            }
            if base_project is not None:
                coding_evidence["base_project"] = base_project
            structured_input["website_coding_evidence"] = coding_evidence
        evidence: list[SearchEvidence] = []
        if normalized_research_query is not None:
            try:
                evidence = await self._search_provider.search(
                    SearchRequest(
                        business_id=business.id,
                        query=normalized_research_query,
                    )
                )
            except Exception as error:
                logger.exception(
                    "Research evidence search failed",
                    extra={
                        "event": "agent.research.search_failed",
                        "agent_id": agent.id,
                        "business_id": str(business.id),
                    },
                )
                raise ResearchSearchUnavailable from error
            structured_input["research"] = {
                "provider": self._search_provider.provider_id,
                "query": normalized_research_query,
                "evidence": [asdict(item) for item in evidence],
            }
        if skill_version is not None:
            structured_input["skill"] = {
                "skill_id": skill_version.skill_id,
                "version": skill_version.version,
                "input": normalized_skill_input,
            }
        validate_schema(structured_input, version.input_schema)
        now = _now()
        run = AgentRun(
            id=uuid.uuid4(),
            business_id=business.id,
            agent_id=agent.id,
            agent_version_id=version.id,
            skill_version_id=skill_version.id if skill_version is not None else None,
            status="queued",
            structured_input=structured_input,
            structured_output=None,
            model_operation_id=None,
            error_type=None,
            error_message=None,
            worker_recovery_count=0,
            created_at=now,
            queued_at=now,
            started_at=None,
            completed_at=None,
            cancellation_requested_at=None,
            cancelled_at=None,
        )
        message = AgentMessage(
            id=uuid.uuid4(),
            run_id=run.id,
            sequence=1,
            role="user",
            message_type="input",
            content={
                "objective": objective,
                "context_id": business_context.context_id,
                "skill_id": skill_version.skill_id if skill_version is not None else None,
                "skill_input": normalized_skill_input if skill_version is not None else None,
                "research_query": normalized_research_query,
                "research_evidence_count": (
                    len(evidence) if normalized_research_query is not None else None
                ),
                "research_run_ids": [str(item) for item in selected_research_run_ids],
            },
            created_at=now,
        )
        async with self._session_factory() as database:
            database.add(run)
            # AgentRun and AgentMessage deliberately have no ORM relationship.
            # Flush the parent explicitly so PostgreSQL never observes the child
            # insert before its foreign-key target.
            await database.flush()
            database.add(message)
            await database.commit()
        try:
            await self._enqueue(run.id)
        except Exception:
            logger.exception(
                "Agent run enqueue failed",
                extra={"event": "agent.run.enqueue_failed", "agent_run_id": str(run.id)},
            )
            await self._mark_enqueue_failure(run.id)
            raise AgentQueueUnavailable(run.id) from None
        return await self._record_for_business(run.id, business.id)

    async def inspect_run(self, context: AuthContext, run_id: uuid.UUID) -> AgentRunRecord:
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
        return await self._record_for_business(run_id, business.id)

    async def cancel_run(self, context: AuthContext, run_id: uuid.UUID) -> AgentRunRecord:
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
            run = await database.scalar(
                select(AgentRun)
                .where(AgentRun.id == run_id, AgentRun.business_id == business.id)
                .with_for_update()
            )
            if run is None:
                raise AgentRunNotFound
            if run.status in TERMINAL_STATUSES:
                raise AgentRunNotCancellable
            now = _now()
            run.status = "cancelled"
            run.cancellation_requested_at = now
            run.cancelled_at = now
            run.completed_at = now
            database.add(
                AgentMessage(
                    id=uuid.uuid4(),
                    run_id=run.id,
                    sequence=2,
                    role="system",
                    message_type="error",
                    content={"error_type": "owner_cancelled"},
                    created_at=now,
                )
            )
            await database.commit()
        return await self._record_for_business(run_id, business.id)

    async def _mark_enqueue_failure(self, run_id: uuid.UUID) -> None:
        async with self._session_factory() as database:
            run = await database.scalar(
                select(AgentRun).where(AgentRun.id == run_id).with_for_update()
            )
            if run is None or run.status != "queued":
                return
            run.status = "failed"
            run.error_type = "queue_unavailable"
            run.error_message = "The background worker queue was unavailable"
            run.completed_at = _now()
            database.add(
                AgentMessage(
                    id=uuid.uuid4(),
                    run_id=run.id,
                    sequence=2,
                    role="system",
                    message_type="error",
                    content={"error_type": run.error_type, "message": run.error_message},
                    created_at=run.completed_at,
                )
            )
            await database.commit()

    async def _record_for_business(
        self, run_id: uuid.UUID, business_id: uuid.UUID
    ) -> AgentRunRecord:
        async with self._session_factory() as database:
            row = (
                await database.execute(
                    select(AgentRun, AgentVersion, SkillVersion)
                    .join(AgentVersion, AgentVersion.id == AgentRun.agent_version_id)
                    .outerjoin(SkillVersion, SkillVersion.id == AgentRun.skill_version_id)
                    .where(AgentRun.id == run_id, AgentRun.business_id == business_id)
                )
            ).one_or_none()
            if row is None:
                raise AgentRunNotFound
            run, version, skill_version = row
            messages = list(
                await database.scalars(
                    select(AgentMessage)
                    .where(AgentMessage.run_id == run.id)
                    .order_by(AgentMessage.sequence)
                )
            )
            calls = list(
                await database.scalars(
                    select(ModelGatewayCall)
                    .where(ModelGatewayCall.agent_run_id == run.id)
                    .order_by(
                        ModelGatewayCall.created_at,
                        ModelGatewayCall.attempt_number,
                    )
                )
            )
        return AgentRunRecord(
            run=run,
            version=version,
            skill_version=skill_version,
            messages=messages,
            gateway_calls=calls,
        )
