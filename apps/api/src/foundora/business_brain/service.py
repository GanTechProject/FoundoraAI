from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from foundora.auth.service import AuthContext
from foundora.business.context import NoSelectedBusiness, resolve_selected_business
from foundora.infrastructure.database import get_session_factory
from foundora.knowledge.embeddings import LocalFeatureHashEmbedding
from foundora.knowledge.service import KnowledgeSearchHit, search_knowledge
from foundora.models import (
    ApprovedBusinessProfile,
    BusinessGoal,
    BusinessPreference,
    Task,
    TaskDependency,
)

SourceType = Literal[
    "business_profile",
    "approved_profile",
    "approved_goals",
    "products_services",
    "brand",
    "operating_context",
    "operational_goals",
    "current_tasks",
    "knowledge",
]
SourceValidity = Literal["current", "stale", "invalidated"]
SelectionStatus = Literal["included", "excluded"]
ExclusionReason = Literal["not_selected", "stale", "invalidated", "token_budget"]

SOURCE_TYPES: tuple[SourceType, ...] = (
    "business_profile",
    "approved_profile",
    "approved_goals",
    "products_services",
    "brand",
    "operating_context",
    "operational_goals",
    "current_tasks",
    "knowledge",
)

FUTURE_SOURCE_TYPES: dict[str, str] = {
    "approved_strategy": "No approved strategy domain exists before Phase 17.",
    "customers": "No customer domain exists before Phase 33.",
    "decisions": "No governed decision domain exists yet.",
    "kpis": "No KPI domain exists before Phase 40.",
    "relevant_memories": "No memory system exists before Phase 14.",
}


@dataclass(frozen=True)
class ContextBuildRequest:
    purpose: str
    token_budget: int
    selected_source_types: frozenset[SourceType]
    knowledge_query: str | None = None


@dataclass(frozen=True)
class ContextCandidate:
    source_type: SourceType
    source_reference: str
    source_version: str
    authority: str
    label: str
    updated_at: datetime
    validity: SourceValidity
    content: dict[str, object]


@dataclass(frozen=True)
class ContextSourceDecision:
    source_type: SourceType
    source_reference: str
    source_version: str
    authority: str
    label: str
    updated_at: datetime
    validity: SourceValidity
    selection_status: SelectionStatus
    exclusion_reason: ExclusionReason | None
    estimated_tokens: int
    content_sha256: str
    content: dict[str, object] | None


@dataclass(frozen=True)
class BusinessContext:
    context_id: str
    business_id: uuid.UUID
    purpose: str
    generated_at: datetime
    token_budget: int
    estimated_tokens: int
    budget_remaining: int
    selected_source_types: tuple[SourceType, ...]
    sources: list[ContextSourceDecision]
    unavailable_sources: dict[str, str]
    context: str
    context_sha256: str


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _token_upper_bound(value: object) -> int:
    """Conservatively budget one token per UTF-8 byte."""
    return len(_canonical(value).encode("utf-8"))


def _content_hash(content: dict[str, object]) -> str:
    return hashlib.sha256(_canonical(content).encode("utf-8")).hexdigest()


def _source_payload(candidate: ContextCandidate) -> dict[str, object]:
    return {
        "source_type": candidate.source_type,
        "source_reference": candidate.source_reference,
        "source_version": candidate.source_version,
        "authority": candidate.authority,
        "updated_at": candidate.updated_at.astimezone(UTC).isoformat(),
        "content": candidate.content,
    }


def _context_payload(
    business_id: uuid.UUID, purpose: str, sources: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "schema": "foundora.business_context.v1",
        "business_id": str(business_id),
        "purpose": purpose,
        "sources": sources,
    }


def select_context(
    *,
    business_id: uuid.UUID,
    request: ContextBuildRequest,
    candidates: list[ContextCandidate],
    unavailable_sources: dict[str, str],
    generated_at: datetime | None = None,
) -> BusinessContext:
    included_payloads: list[dict[str, object]] = []
    decisions: list[ContextSourceDecision] = []
    for candidate in candidates:
        payload = _source_payload(candidate)
        estimated_tokens = _token_upper_bound(payload)
        reason: ExclusionReason | None = None
        if candidate.validity == "stale":
            reason = "stale"
        elif candidate.validity == "invalidated":
            reason = "invalidated"
        elif candidate.source_type not in request.selected_source_types:
            reason = "not_selected"
        else:
            trial = _context_payload(
                business_id,
                request.purpose,
                [*included_payloads, payload],
            )
            if _token_upper_bound(trial) > request.token_budget:
                reason = "token_budget"
            else:
                included_payloads.append(payload)
        decisions.append(
            ContextSourceDecision(
                source_type=candidate.source_type,
                source_reference=candidate.source_reference,
                source_version=candidate.source_version,
                authority=candidate.authority,
                label=candidate.label,
                updated_at=candidate.updated_at,
                validity=candidate.validity,
                selection_status="excluded" if reason is not None else "included",
                exclusion_reason=reason,
                estimated_tokens=estimated_tokens,
                content_sha256=_content_hash(candidate.content),
                content=candidate.content if reason is None else None,
            )
        )
    payload = _context_payload(business_id, request.purpose, included_payloads)
    rendered = _canonical(payload)
    estimated_tokens = len(rendered.encode("utf-8"))
    source_fingerprint = [
        {
            "source_type": item.source_type,
            "reference": item.source_reference,
            "version": item.source_version,
            "content_sha256": item.content_sha256,
            "selection": item.selection_status,
            "reason": item.exclusion_reason,
        }
        for item in decisions
    ]
    context_id = hashlib.sha256(
        _canonical(
            {
                "business_id": str(business_id),
                "purpose": request.purpose,
                "token_budget": request.token_budget,
                "selected_source_types": sorted(request.selected_source_types),
                "knowledge_query": request.knowledge_query,
                "sources": source_fingerprint,
            }
        ).encode("utf-8")
    ).hexdigest()
    return BusinessContext(
        context_id=context_id,
        business_id=business_id,
        purpose=request.purpose,
        generated_at=generated_at or datetime.now(UTC),
        token_budget=request.token_budget,
        estimated_tokens=estimated_tokens,
        budget_remaining=request.token_budget - estimated_tokens,
        selected_source_types=tuple(
            source_type
            for source_type in SOURCE_TYPES
            if source_type in request.selected_source_types
        ),
        sources=decisions,
        unavailable_sources=dict(unavailable_sources),
        context=rendered,
        context_sha256=hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
    )


class ContextService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()

    async def build(self, context: AuthContext, request: ContextBuildRequest) -> BusinessContext:
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
            preferences = await database.get(BusinessPreference, business.id)
            if preferences is None:
                raise NoSelectedBusiness
            approved = await database.get(ApprovedBusinessProfile, business.id)
            goals = list(
                await database.scalars(
                    select(BusinessGoal)
                    .where(BusinessGoal.business_id == business.id)
                    .order_by(BusinessGoal.updated_at.desc(), BusinessGoal.id.asc())
                )
            )
            tasks = list(
                await database.scalars(
                    select(Task)
                    .where(Task.business_id == business.id)
                    .order_by(Task.priority, Task.updated_at.desc(), Task.id.asc())
                )
            )
            task_ids = [task.id for task in tasks]
            dependency_rows = (
                (
                    await database.execute(
                        select(
                            TaskDependency.task_id,
                            TaskDependency.depends_on_task_id,
                            Task.status,
                        )
                        .join(Task, Task.id == TaskDependency.depends_on_task_id)
                        .where(TaskDependency.task_id.in_(task_ids))
                    )
                ).all()
                if task_ids
                else []
            )
            knowledge_hits = (
                await search_knowledge(
                    database,
                    business_id=business.id,
                    query=request.knowledge_query,
                    embedding=LocalFeatureHashEmbedding(),
                    limit=5,
                    minimum_score=0.05,
                )
                if "knowledge" in request.selected_source_types and request.knowledge_query
                else []
            )

        candidates = [
            ContextCandidate(
                source_type="business_profile",
                source_reference=f"businesses/{business.id}",
                source_version=(
                    f"business:{business.updated_at.astimezone(UTC).isoformat()};"
                    f"preferences:{preferences.updated_at.astimezone(UTC).isoformat()}"
                ),
                authority="founder_workspace",
                label="Live business profile and operating preferences",
                updated_at=max(business.updated_at, preferences.updated_at),
                validity="current",
                content={
                    "name": business.name,
                    "summary": business.summary,
                    "status": business.status,
                    "preferences": {
                        "timezone": preferences.timezone,
                        "currency": preferences.currency,
                        "locale": preferences.locale,
                    },
                },
            )
        ]
        unavailable = dict(FUTURE_SOURCE_TYPES)
        if approved is None:
            reason = "No founder-approved onboarding profile exists for this business."
            for source_type in (
                "approved_profile",
                "approved_goals",
                "products_services",
                "brand",
                "operating_context",
            ):
                unavailable[source_type] = reason
        else:
            candidates.extend(self._approved_candidates(approved))
        candidates.extend(self._goal_candidates(goals))
        if not goals:
            unavailable["operational_goals"] = "No business goals are recorded."
        dependencies_by_task: dict[uuid.UUID, list[dict[str, object]]] = {}
        for task_id, dependency_id, dependency_status in dependency_rows:
            dependencies_by_task.setdefault(task_id, []).append(
                {
                    "task_id": str(dependency_id),
                    "status": dependency_status,
                    "satisfied": dependency_status == "completed",
                }
            )
        candidates.extend(self._task_candidates(tasks, dependencies_by_task))
        if not tasks:
            unavailable["current_tasks"] = "No tasks are recorded."
        candidates.extend(self._knowledge_candidates(knowledge_hits))
        if "knowledge" in request.selected_source_types and not request.knowledge_query:
            unavailable["knowledge"] = "Knowledge context requires an explicit retrieval query."
        elif request.knowledge_query and not knowledge_hits:
            unavailable["knowledge"] = "No active knowledge chunk matched the retrieval query."
        return select_context(
            business_id=business.id,
            request=request,
            candidates=candidates,
            unavailable_sources=unavailable,
        )

    @staticmethod
    def _knowledge_candidates(hits: list[KnowledgeSearchHit]) -> list[ContextCandidate]:
        return [
            ContextCandidate(
                source_type="knowledge",
                source_reference=(
                    f"knowledge_sources/{hit.citation.source_id}/documents/"
                    f"{hit.citation.document_id}/chunks/{hit.citation.chunk_id}"
                ),
                source_version=hit.citation.document_content_sha256,
                authority="founder_registered_knowledge",
                label=f"{hit.citation.source_title} — {hit.citation.filename}",
                updated_at=hit.citation.document_created_at,
                validity="current",
                content={
                    "text": hit.text,
                    "similarity": hit.score,
                    "citation": {
                        "source_id": str(hit.citation.source_id),
                        "source_uri": hit.citation.source_uri,
                        "document_id": str(hit.citation.document_id),
                        "filename": hit.citation.filename,
                        "chunk_id": str(hit.citation.chunk_id),
                        "chunk_ordinal": hit.citation.chunk_ordinal,
                        "start_character": hit.citation.start_character,
                        "end_character": hit.citation.end_character,
                        "content_sha256": hit.citation.content_sha256,
                    },
                },
            )
            for hit in hits
        ]

    @staticmethod
    def _approved_candidates(
        profile: ApprovedBusinessProfile,
    ) -> list[ContextCandidate]:
        reference = f"approved_business_profiles/{profile.business_id}"
        version = str(profile.version)
        common = {
            "source_reference": reference,
            "source_version": version,
            "authority": "founder_approved_onboarding",
            "updated_at": profile.approved_at,
            "validity": "current",
        }
        return [
            ContextCandidate(
                source_type="approved_profile",
                label=f"Founder-approved business profile v{version}",
                content={
                    "business_type": profile.business_type,
                    "business_name": profile.business_name,
                    "industry": profile.industry,
                    "geography": profile.geography,
                    "problem": profile.problem,
                    "target_audience": profile.target_audience,
                    "budget": profile.budget,
                },
                **common,  # type: ignore[arg-type]
            ),
            ContextCandidate(
                source_type="approved_goals",
                label=f"Founder-approved strategic goals v{version}",
                content={"goals": profile.goals},
                **common,  # type: ignore[arg-type]
            ),
            ContextCandidate(
                source_type="products_services",
                label=f"Founder-approved offer v{version}",
                content={"offer": profile.offer},
                **common,  # type: ignore[arg-type]
            ),
            ContextCandidate(
                source_type="brand",
                label=f"Founder-approved brand preferences v{version}",
                content={"brand_preferences": profile.brand_preferences},
                **common,  # type: ignore[arg-type]
            ),
            ContextCandidate(
                source_type="operating_context",
                label=f"Founder-approved assets and constraints v{version}",
                content={
                    "existing_assets": profile.existing_assets,
                    "constraints": profile.constraints,
                    "declared_services": profile.connected_services,
                },
                **common,  # type: ignore[arg-type]
            ),
        ]

    @staticmethod
    def _goal_candidates(goals: list[BusinessGoal]) -> list[ContextCandidate]:
        result: list[ContextCandidate] = []
        for goal in goals:
            validity: SourceValidity = "current"
            if goal.status == "completed":
                validity = "stale"
            elif goal.status == "cancelled":
                validity = "invalidated"
            result.append(
                ContextCandidate(
                    source_type="operational_goals",
                    source_reference=f"business_goals/{goal.id}",
                    source_version=goal.updated_at.astimezone(UTC).isoformat(),
                    authority="founder_workspace",
                    label=goal.title,
                    updated_at=goal.updated_at,
                    validity=validity,
                    content={
                        "title": goal.title,
                        "details": goal.details,
                        "target_date": (
                            goal.target_date.isoformat() if goal.target_date is not None else None
                        ),
                        "status": goal.status,
                    },
                )
            )
        return result

    @staticmethod
    def _task_candidates(
        tasks: list[Task], dependencies_by_task: dict[uuid.UUID, list[dict[str, object]]]
    ) -> list[ContextCandidate]:
        result: list[ContextCandidate] = []
        for task in tasks:
            validity: SourceValidity = "current"
            if task.status == "completed":
                validity = "stale"
            elif task.status == "cancelled":
                validity = "invalidated"
            result.append(
                ContextCandidate(
                    source_type="current_tasks",
                    source_reference=f"tasks/{task.id}",
                    source_version=task.updated_at.astimezone(UTC).isoformat(),
                    authority="task_engine",
                    label=task.title,
                    updated_at=task.updated_at,
                    validity=validity,
                    content={
                        "title": task.title,
                        "description": task.description,
                        "goal_id": str(task.goal_id) if task.goal_id is not None else None,
                        "priority": task.priority,
                        "owner_type": task.owner_type,
                        "owner_agent_id": task.owner_agent_id,
                        "status": task.status,
                        "due_at": (
                            task.due_at.astimezone(UTC).isoformat()
                            if task.due_at is not None
                            else None
                        ),
                        "retry_count": task.retry_count,
                        "max_retries": task.max_retries,
                        "dependencies": dependencies_by_task.get(task.id, []),
                    },
                )
            )
        return result
