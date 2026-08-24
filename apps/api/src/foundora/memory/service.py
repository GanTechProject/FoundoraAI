from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlsplit

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from foundora.auth.service import AuthContext
from foundora.business.context import resolve_selected_business
from foundora.events.service import publish_event
from foundora.infrastructure.database import get_session_factory
from foundora.models import (
    AgentRun,
    DocumentChunk,
    KnowledgeDocument,
    KnowledgeSource,
    MemoryPolicy,
    MemoryProposal,
    MemoryProvenance,
    MemoryRecord,
    MemoryRevision,
    Task,
    WorkflowRun,
)

MEMORY_TYPES = frozenset(
    {"working", "episodic", "semantic", "decision", "preference", "workflow", "evaluation"}
)
EPISTEMIC_BY_TYPE = {
    "working": frozenset({"observation", "assumption"}),
    "episodic": frozenset({"observation"}),
    "semantic": frozenset({"fact", "assumption"}),
    "decision": frozenset({"decision"}),
    "preference": frozenset({"preference"}),
    "workflow": frozenset({"procedure"}),
    "evaluation": frozenset({"evaluation"}),
}
EPISTEMIC_STATUSES = frozenset().union(*EPISTEMIC_BY_TYPE.values())
AUTOMATIC_ELIGIBLE_TYPES = frozenset({"working", "episodic", "workflow", "evaluation"})
VERIFIABLE_SOURCE_KINDS = frozenset({"knowledge_chunk", "task", "agent_run", "workflow_run"})
SOURCE_KINDS = VERIFIABLE_SOURCE_KINDS | {"founder_input"}
EXECUTION_TYPES = frozenset({"task", "agent_run", "workflow_run"})
MAX_WORKING_LIFETIME = timedelta(days=7)
MAX_METADATA_BYTES = 16_384
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(
        r"\b(password|passwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*\S+", re.IGNORECASE
    ),
)
_SENSITIVE_QUERY_NAMES = frozenset(
    {"token", "access_token", "api_key", "apikey", "key", "secret", "password", "signature"}
)


class MemoryConflict(Exception):
    pass


class MemoryProposalNotFound(Exception):
    pass


class MemoryRecordNotFound(Exception):
    pass


@dataclass(frozen=True)
class PolicyState:
    automatic_accept_types: tuple[str, ...]
    minimum_confidence: float
    revision: int
    persisted: bool


@dataclass(frozen=True)
class MemoryEntry:
    record: MemoryRecord
    revisions: list[MemoryRevision]
    provenance: list[MemoryProvenance]


@dataclass(frozen=True)
class MemoryDashboard:
    business_id: uuid.UUID
    policy: PolicyState
    proposals: list[MemoryProposal]
    memories: list[MemoryEntry]


@dataclass(frozen=True)
class ResolvedSource:
    kind: str
    source_id: str | None
    uri: str | None
    label: str
    excerpt: str | None
    metadata: dict[str, object]


def _now() -> datetime:
    return datetime.now(UTC)


def _clean(value: str, maximum: int, label: str) -> str:
    normalized = " ".join(value.strip().split())
    if not normalized or len(normalized) > maximum:
        raise MemoryConflict(f"{label} must contain 1 to {maximum} characters")
    return normalized


def _clean_content(value: str) -> str:
    normalized = value.strip().replace("\r\n", "\n").replace("\r", "\n")
    if not normalized or len(normalized) > 8_000:
        raise MemoryConflict("Memory content must contain 1 to 8000 characters")
    return normalized


def _json_metadata(value: dict[str, object]) -> dict[str, object]:
    try:
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise MemoryConflict("Source metadata must be valid JSON") from error
    if len(rendered.encode("utf-8")) > MAX_METADATA_BYTES:
        raise MemoryConflict("Source metadata exceeds 16384 bytes")
    _reject_secrets(rendered)
    return value


def _reject_secrets(*values: str | None) -> None:
    for value in values:
        if value and any(pattern.search(value) for pattern in _SECRET_PATTERNS):
            raise MemoryConflict("Potential credentials or secrets cannot enter durable memory")


def _manual_uri(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip()
    if len(normalized) > 2048:
        raise MemoryConflict("Source URI exceeds 2048 characters")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
        raise MemoryConflict("Source URI must be an absolute HTTP(S) URL without credentials")
    if any(name.casefold() in _SENSITIVE_QUERY_NAMES for name, _ in parse_qsl(parsed.query)):
        raise MemoryConflict("Source URI cannot contain credential-bearing query parameters")
    _reject_secrets(normalized)
    return normalized


def canonical_key(memory_type: str, epistemic_status: str, title: str, content: str) -> str:
    normalized = "\n".join(
        unicodedata.normalize("NFKC", item).casefold().strip()
        for item in (
            memory_type,
            epistemic_status,
            " ".join(title.split()),
            " ".join(content.split()),
        )
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _validate_type(memory_type: str, epistemic_status: str) -> None:
    if memory_type not in MEMORY_TYPES:
        raise MemoryConflict("Memory type is unsupported")
    if epistemic_status not in EPISTEMIC_BY_TYPE[memory_type]:
        raise MemoryConflict(f"{epistemic_status!r} cannot be stored as {memory_type!r} memory")


def _normalize_expiry(
    memory_type: str,
    expires_at: datetime | None,
    execution_type: str | None,
    execution_id: uuid.UUID | None,
    now: datetime,
) -> datetime | None:
    if expires_at is not None and expires_at.tzinfo is None:
        raise MemoryConflict("Memory expiry must include a timezone")
    if expires_at is not None and expires_at <= now:
        raise MemoryConflict("Memory expiry must be in the future")
    if memory_type == "working":
        if execution_type not in EXECUTION_TYPES or execution_id is None or expires_at is None:
            raise MemoryConflict(
                "Working memory requires an execution type, execution ID, and expiry"
            )
        if expires_at - now > MAX_WORKING_LIFETIME:
            raise MemoryConflict("Working memory cannot live longer than seven days")
    elif execution_type is not None or execution_id is not None:
        raise MemoryConflict("Only working memory can be execution-scoped")
    return expires_at


async def _resolve_entity(
    database: AsyncSession,
    *,
    business_id: uuid.UUID,
    kind: str,
    entity_id: uuid.UUID,
) -> tuple[str, str, dict[str, object]]:
    if kind == "task":
        record = await database.scalar(
            select(Task).where(Task.id == entity_id, Task.business_id == business_id)
        )
        if record is not None:
            return (
                f"Task: {record.title}",
                f"foundora://tasks/{record.id}",
                {"status": record.status},
            )
    elif kind == "agent_run":
        record = await database.scalar(
            select(AgentRun).where(AgentRun.id == entity_id, AgentRun.business_id == business_id)
        )
        if record is not None:
            return (
                f"Agent run: {record.agent_id}",
                f"foundora://agent-runs/{record.id}",
                {"status": record.status},
            )
    elif kind == "workflow_run":
        record = await database.scalar(
            select(WorkflowRun).where(
                WorkflowRun.id == entity_id, WorkflowRun.business_id == business_id
            )
        )
        if record is not None:
            return (
                f"Workflow run: {record.workflow_id}",
                f"foundora://workflow-runs/{record.id}",
                {"status": record.status},
            )
    raise MemoryConflict(f"The {kind.replace('_', ' ')} source is unavailable for this business")


async def _resolve_source(
    database: AsyncSession,
    *,
    business_id: uuid.UUID,
    source_kind: str,
    source_id: str | None,
    source_uri: str | None,
    source_label: str,
    source_excerpt: str | None,
    source_metadata: dict[str, object],
) -> ResolvedSource:
    if source_kind not in SOURCE_KINDS:
        raise MemoryConflict("Memory provenance source is unsupported")
    if source_kind == "founder_input":
        if source_id is not None:
            raise MemoryConflict("Founder input provenance cannot claim a system source ID")
        label = _clean(source_label, 200, "Source label")
        excerpt = source_excerpt.strip() if source_excerpt else None
        if excerpt and len(excerpt) > 1000:
            raise MemoryConflict("Source excerpt exceeds 1000 characters")
        metadata = _json_metadata(source_metadata)
        uri = _manual_uri(source_uri)
        _reject_secrets(label, excerpt)
        return ResolvedSource(source_kind, None, uri, label, excerpt, metadata)
    if source_id is None:
        raise MemoryConflict("System provenance requires a source ID")
    try:
        entity_id = uuid.UUID(source_id)
    except ValueError as error:
        raise MemoryConflict("Source ID must be a UUID") from error
    if source_kind == "knowledge_chunk":
        row = (
            await database.execute(
                select(DocumentChunk, KnowledgeDocument, KnowledgeSource)
                .join(KnowledgeDocument, KnowledgeDocument.id == DocumentChunk.document_id)
                .join(KnowledgeSource, KnowledgeSource.id == DocumentChunk.source_id)
                .where(
                    DocumentChunk.id == entity_id,
                    DocumentChunk.business_id == business_id,
                    KnowledgeDocument.status == "indexed",
                    KnowledgeSource.status == "active",
                )
            )
        ).one_or_none()
        if row is None:
            raise MemoryConflict("The knowledge citation is unavailable for this business")
        chunk, document, source = row
        resolved = ResolvedSource(
            source_kind,
            str(chunk.id),
            source.source_uri or f"foundora://knowledge/chunks/{chunk.id}",
            f"{source.title} — {document.filename}",
            chunk.content[:1000],
            {
                "source_id": str(source.id),
                "document_id": str(document.id),
                "document_sha256": document.content_sha256,
                "chunk_ordinal": chunk.ordinal,
                "chunk_sha256": chunk.content_sha256,
            },
        )
        _reject_secrets(
            resolved.uri,
            resolved.label,
            resolved.excerpt,
            json.dumps(resolved.metadata, sort_keys=True),
        )
        return resolved
    label, uri, metadata = await _resolve_entity(
        database, business_id=business_id, kind=source_kind, entity_id=entity_id
    )
    _reject_secrets(uri, label, json.dumps(metadata, sort_keys=True))
    return ResolvedSource(source_kind, str(entity_id), uri, label, None, metadata)


async def retrieve_memories(
    database: AsyncSession,
    *,
    business_id: uuid.UUID,
    memory_types: frozenset[str] = frozenset(),
    epistemic_statuses: frozenset[str] = frozenset(),
    query: str | None = None,
    execution_type: str | None = None,
    execution_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[MemoryRecord]:
    now = _now()
    statement = select(MemoryRecord).where(
        MemoryRecord.business_id == business_id,
        MemoryRecord.status == "active",
        or_(MemoryRecord.expires_at.is_(None), MemoryRecord.expires_at > now),
    )
    if memory_types:
        statement = statement.where(MemoryRecord.memory_type.in_(memory_types))
    if epistemic_statuses:
        statement = statement.where(MemoryRecord.epistemic_status.in_(epistemic_statuses))
    if execution_type is not None and execution_id is not None:
        statement = statement.where(
            or_(
                MemoryRecord.memory_type != "working",
                (MemoryRecord.execution_type == execution_type)
                & (MemoryRecord.execution_id == execution_id),
            )
        )
    else:
        statement = statement.where(MemoryRecord.memory_type != "working")
    if query:
        term = f"%{query.strip()}%"
        statement = statement.where(
            or_(MemoryRecord.title.ilike(term), MemoryRecord.content.ilike(term))
        )
    return list(
        await database.scalars(
            statement.order_by(desc(MemoryRecord.confidence), desc(MemoryRecord.updated_at)).limit(
                limit
            )
        )
    )


class MemoryService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()

    async def dashboard(
        self,
        context: AuthContext,
        *,
        memory_types: frozenset[str] = frozenset(),
        epistemic_statuses: frozenset[str] = frozenset(),
        query: str | None = None,
        include_inactive: bool = True,
        execution_type: str | None = None,
        execution_id: uuid.UUID | None = None,
    ) -> MemoryDashboard:
        if memory_types.difference(MEMORY_TYPES):
            raise MemoryConflict("Memory filter contains an unsupported type")
        if epistemic_statuses.difference(EPISTEMIC_STATUSES):
            raise MemoryConflict("Memory filter contains an unsupported epistemic status")
        if (execution_type is None) != (execution_id is None):
            raise MemoryConflict("Execution type and execution ID must be supplied together")
        if query is not None and not query.strip():
            raise MemoryConflict("Memory query cannot be blank")
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
            policy = await database.get(MemoryPolicy, business.id)
            state = PolicyState(
                automatic_accept_types=tuple(sorted(policy.automatic_accept_types))
                if policy
                else (),
                minimum_confidence=policy.minimum_confidence if policy else 0.9,
                revision=policy.revision if policy else 0,
                persisted=policy is not None,
            )
            proposal_statement = (
                select(MemoryProposal)
                .where(MemoryProposal.business_id == business.id)
                .order_by(desc(MemoryProposal.created_at))
                .limit(100)
            )
            proposals = list(await database.scalars(proposal_statement))
            if include_inactive:
                statement = select(MemoryRecord).where(MemoryRecord.business_id == business.id)
                if memory_types:
                    statement = statement.where(MemoryRecord.memory_type.in_(memory_types))
                if epistemic_statuses:
                    statement = statement.where(
                        MemoryRecord.epistemic_status.in_(epistemic_statuses)
                    )
                if query:
                    term = f"%{query.strip()}%"
                    statement = statement.where(
                        or_(MemoryRecord.title.ilike(term), MemoryRecord.content.ilike(term))
                    )
                records = list(
                    await database.scalars(
                        statement.order_by(desc(MemoryRecord.updated_at)).limit(100)
                    )
                )
            else:
                records = await retrieve_memories(
                    database,
                    business_id=business.id,
                    memory_types=memory_types,
                    epistemic_statuses=epistemic_statuses,
                    query=query,
                    execution_type=execution_type,
                    execution_id=execution_id,
                    limit=100,
                )
            ids = [record.id for record in records]
            revisions = (
                list(
                    await database.scalars(
                        select(MemoryRevision)
                        .where(MemoryRevision.memory_id.in_(ids))
                        .order_by(MemoryRevision.memory_id, MemoryRevision.revision)
                    )
                )
                if ids
                else []
            )
            provenance = (
                list(
                    await database.scalars(
                        select(MemoryProvenance)
                        .where(MemoryProvenance.memory_id.in_(ids))
                        .order_by(MemoryProvenance.memory_id, MemoryProvenance.revision)
                    )
                )
                if ids
                else []
            )
            return MemoryDashboard(
                business_id=business.id,
                policy=state,
                proposals=proposals,
                memories=[
                    MemoryEntry(
                        record,
                        [item for item in revisions if item.memory_id == record.id],
                        [item for item in provenance if item.memory_id == record.id],
                    )
                    for record in records
                ],
            )

    async def update_policy(
        self,
        context: AuthContext,
        *,
        automatic_accept_types: list[str],
        minimum_confidence: float,
        expected_revision: int,
    ) -> MemoryPolicy:
        if minimum_confidence < 0 or minimum_confidence > 1:
            raise MemoryConflict("Minimum confidence must be between zero and one")
        normalized = sorted(set(automatic_accept_types))
        unsupported = set(normalized).difference(AUTOMATIC_ELIGIBLE_TYPES)
        if unsupported:
            raise MemoryConflict(
                "Automatic acceptance is limited to working, episodic, workflow, "
                "and evaluation memory"
            )
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                policy = await database.scalar(
                    select(MemoryPolicy)
                    .where(MemoryPolicy.business_id == business.id)
                    .with_for_update()
                )
                now = _now()
                if policy is None:
                    if expected_revision != 0:
                        raise MemoryConflict("The memory policy changed; reload before saving")
                    policy = MemoryPolicy(
                        business_id=business.id,
                        automatic_accept_types=normalized,
                        minimum_confidence=minimum_confidence,
                        revision=1,
                        updated_by_owner_id=context.owner.id,
                        created_at=now,
                        updated_at=now,
                    )
                    database.add(policy)
                else:
                    if policy.revision != expected_revision:
                        raise MemoryConflict("The memory policy changed; reload before saving")
                    policy.automatic_accept_types = normalized
                    policy.minimum_confidence = minimum_confidence
                    policy.revision += 1
                    policy.updated_by_owner_id = context.owner.id
                    policy.updated_at = now
            return policy

    async def propose(
        self,
        context: AuthContext,
        *,
        memory_type: str,
        epistemic_status: str,
        title: str,
        content: str,
        confidence: float,
        execution_type: str | None,
        execution_id: uuid.UUID | None,
        expires_at: datetime | None,
        source_kind: str,
        source_id: str | None,
        source_uri: str | None,
        source_label: str,
        source_excerpt: str | None,
        source_metadata: dict[str, object],
    ) -> MemoryProposal:
        _validate_type(memory_type, epistemic_status)
        if confidence < 0 or confidence > 1:
            raise MemoryConflict("Memory confidence must be between zero and one")
        normalized_title = _clean(title, 200, "Memory title")
        normalized_content = _clean_content(content)
        _reject_secrets(normalized_title, normalized_content, source_excerpt)
        now = _now()
        normalized_expiry = _normalize_expiry(
            memory_type, expires_at, execution_type, execution_id, now
        )
        key = canonical_key(memory_type, epistemic_status, normalized_title, normalized_content)
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                if memory_type == "working":
                    await _resolve_entity(
                        database,
                        business_id=business.id,
                        kind=execution_type or "",
                        entity_id=execution_id or uuid.UUID(int=0),
                    )
                source = await _resolve_source(
                    database,
                    business_id=business.id,
                    source_kind=source_kind,
                    source_id=source_id,
                    source_uri=source_uri,
                    source_label=source_label,
                    source_excerpt=source_excerpt,
                    source_metadata=source_metadata,
                )
                policy = await database.get(MemoryPolicy, business.id)
                automatic = bool(
                    policy
                    and memory_type in policy.automatic_accept_types
                    and memory_type in AUTOMATIC_ELIGIBLE_TYPES
                    and confidence >= policy.minimum_confidence
                    and source.kind in VERIFIABLE_SOURCE_KINDS
                    and epistemic_status != "fact"
                )
                proposal = MemoryProposal(
                    id=uuid.uuid4(),
                    business_id=business.id,
                    memory_type=memory_type,
                    epistemic_status=epistemic_status,
                    title=normalized_title,
                    content=normalized_content,
                    confidence=confidence,
                    status="pending",
                    acceptance_route="automatic" if automatic else "founder",
                    canonical_key=key,
                    execution_type=execution_type,
                    execution_id=execution_id,
                    expires_at=normalized_expiry,
                    source_kind=source.kind,
                    source_id=source.source_id,
                    source_uri=source.uri,
                    source_label=source.label,
                    source_excerpt=source.excerpt,
                    source_metadata=source.metadata,
                    requested_by_owner_id=context.owner.id,
                    decided_by_owner_id=None,
                    resolution_memory_id=None,
                    decision_reason=None,
                    revision=1,
                    created_at=now,
                    updated_at=now,
                    decided_at=None,
                )
                database.add(proposal)
                await database.flush()
                await publish_event(
                    database,
                    business_id=business.id,
                    event_type="memory.proposed",
                    aggregate_type="memory_proposal",
                    aggregate_id=str(proposal.id),
                    idempotency_key=f"memory-proposal:{proposal.id}:proposed",
                    payload={
                        "proposal_id": str(proposal.id),
                        "memory_type": memory_type,
                        "epistemic_status": epistemic_status,
                        "acceptance_route": proposal.acceptance_route,
                    },
                )
                if automatic:
                    await self._accept_locked(database, context, proposal, automatic=True)
            return proposal

    async def decide_proposal(
        self,
        context: AuthContext,
        proposal_id: uuid.UUID,
        *,
        expected_revision: int,
        accept: bool,
        reason: str,
    ) -> MemoryProposal:
        normalized_reason = _clean(reason, 500, "Decision reason")
        _reject_secrets(normalized_reason)
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                proposal = await database.scalar(
                    select(MemoryProposal)
                    .where(
                        MemoryProposal.id == proposal_id,
                        MemoryProposal.business_id == business.id,
                    )
                    .with_for_update()
                )
                if proposal is None:
                    raise MemoryProposalNotFound
                if proposal.status != "pending" or proposal.revision != expected_revision:
                    raise MemoryConflict("The memory proposal changed; reload before deciding")
                if accept:
                    proposal.decision_reason = normalized_reason
                    await self._accept_locked(database, context, proposal, automatic=False)
                else:
                    now = _now()
                    proposal.status = "rejected"
                    proposal.revision += 1
                    proposal.decided_by_owner_id = context.owner.id
                    proposal.decision_reason = normalized_reason
                    proposal.updated_at = now
                    proposal.decided_at = now
            return proposal

    async def _accept_locked(
        self,
        database: AsyncSession,
        context: AuthContext,
        proposal: MemoryProposal,
        *,
        automatic: bool,
    ) -> None:
        if proposal.epistemic_status == "fact" and automatic:
            raise MemoryConflict("Semantic facts require explicit founder acceptance")
        now = _now()
        if proposal.expires_at is not None and proposal.expires_at <= now:
            raise MemoryConflict("Expired proposals cannot become durable memory")
        duplicate = await database.scalar(
            select(MemoryRecord)
            .where(
                MemoryRecord.business_id == proposal.business_id,
                MemoryRecord.status == "active",
                MemoryRecord.canonical_key == proposal.canonical_key,
                or_(MemoryRecord.expires_at.is_(None), MemoryRecord.expires_at > now),
            )
            .with_for_update()
        )
        route = "automatic" if automatic else "founder"
        if duplicate is None:
            record = MemoryRecord(
                id=uuid.uuid4(),
                business_id=proposal.business_id,
                originating_proposal_id=proposal.id,
                memory_type=proposal.memory_type,
                epistemic_status=proposal.epistemic_status,
                title=proposal.title,
                content=proposal.content,
                confidence=proposal.confidence,
                status="active",
                accepted_via=route,
                canonical_key=proposal.canonical_key,
                execution_type=proposal.execution_type,
                execution_id=proposal.execution_id,
                expires_at=proposal.expires_at,
                current_revision=1,
                accepted_by_owner_id=None if automatic else context.owner.id,
                created_at=now,
                updated_at=now,
                invalidated_at=None,
                invalidation_reason=None,
            )
            database.add(record)
            await database.flush()
            change_type = "accepted"
            proposal.status = "accepted"
        else:
            record = duplicate
            record.current_revision += 1
            record.confidence = max(record.confidence, proposal.confidence)
            record.updated_at = now
            change_type = "merged"
            proposal.status = "merged"
        database.add(
            MemoryRevision(
                id=uuid.uuid4(),
                memory_id=record.id,
                business_id=record.business_id,
                revision=record.current_revision,
                proposal_id=proposal.id,
                change_type=change_type,
                title=record.title,
                content=record.content,
                confidence=record.confidence,
                canonical_key=record.canonical_key,
                created_by=route,
                created_by_owner_id=None if automatic else context.owner.id,
                created_at=now,
            )
        )
        await database.flush()
        database.add(
            MemoryProvenance(
                id=uuid.uuid4(),
                memory_id=record.id,
                business_id=record.business_id,
                revision=record.current_revision,
                source_kind=proposal.source_kind,
                source_id=proposal.source_id,
                source_uri=proposal.source_uri,
                source_label=proposal.source_label,
                source_excerpt=proposal.source_excerpt,
                source_metadata=proposal.source_metadata,
                created_at=now,
            )
        )
        proposal.resolution_memory_id = record.id
        proposal.revision += 1
        proposal.decided_by_owner_id = None if automatic else context.owner.id
        proposal.decision_reason = (
            "Accepted by configured automatic policy" if automatic else proposal.decision_reason
        )
        proposal.updated_at = now
        proposal.decided_at = now
        event_type = "memory.merged" if change_type == "merged" else "memory.accepted"
        await publish_event(
            database,
            business_id=record.business_id,
            event_type=event_type,
            aggregate_type="memory_record",
            aggregate_id=str(record.id),
            idempotency_key=f"memory-proposal:{proposal.id}:{change_type}",
            payload={
                "proposal_id": str(proposal.id),
                "memory_id": str(record.id),
                "memory_type": record.memory_type,
                "epistemic_status": record.epistemic_status,
                "revision": record.current_revision,
                "accepted_via": route,
            },
        )

    async def invalidate(
        self,
        context: AuthContext,
        memory_id: uuid.UUID,
        *,
        expected_revision: int,
        reason: str,
    ) -> MemoryRecord:
        normalized_reason = _clean(reason, 500, "Invalidation reason")
        _reject_secrets(normalized_reason)
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                record = await database.scalar(
                    select(MemoryRecord)
                    .where(
                        MemoryRecord.id == memory_id,
                        MemoryRecord.business_id == business.id,
                    )
                    .with_for_update()
                )
                if record is None:
                    raise MemoryRecordNotFound
                if record.status != "active" or record.current_revision != expected_revision:
                    raise MemoryConflict("The memory changed; reload before invalidating")
                now = _now()
                record.status = "invalidated"
                record.current_revision += 1
                record.updated_at = now
                record.invalidated_at = now
                record.invalidation_reason = normalized_reason
                await publish_event(
                    database,
                    business_id=record.business_id,
                    event_type="memory.invalidated",
                    aggregate_type="memory_record",
                    aggregate_id=str(record.id),
                    idempotency_key=f"memory:{record.id}:invalidated:{record.current_revision}",
                    payload={
                        "memory_id": str(record.id),
                        "memory_type": record.memory_type,
                        "revision": record.current_revision,
                    },
                )
            return record
