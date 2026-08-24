from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from foundora.auth.service import AuthContext
from foundora.business.context import resolve_selected_business
from foundora.config import get_settings
from foundora.events.service import publish_event
from foundora.infrastructure.database import get_session_factory
from foundora.knowledge.embeddings import (
    EmbeddingAdapter,
    LocalFeatureHashEmbedding,
    cosine_similarity,
)
from foundora.knowledge.extraction import (
    EXTRACTION_VERSION,
    ExtractedDocument,
    TextChunk,
    chunk_text,
    extract_text,
)
from foundora.knowledge.storage import KnowledgeStorage, get_knowledge_storage
from foundora.models import DocumentChunk, KnowledgeDocument, KnowledgeSource

MAX_SOURCE_METADATA_BYTES = 32_768


class KnowledgeSourceNotFound(Exception):
    pass


class KnowledgeDocumentNotFound(Exception):
    pass


class KnowledgeConflict(Exception):
    pass


@dataclass(frozen=True)
class SourceRecord:
    source: KnowledgeSource
    documents: list[KnowledgeDocument]


@dataclass(frozen=True)
class KnowledgeDashboard:
    business_id: uuid.UUID
    sources: list[SourceRecord]


@dataclass(frozen=True)
class KnowledgeCitation:
    source_id: uuid.UUID
    source_title: str
    source_uri: str | None
    document_id: uuid.UUID
    filename: str
    document_content_sha256: str
    document_created_at: datetime
    chunk_id: uuid.UUID
    chunk_ordinal: int
    start_character: int
    end_character: int
    content_sha256: str


@dataclass(frozen=True)
class KnowledgeSearchHit:
    score: float
    text: str
    citation: KnowledgeCitation


def _now() -> datetime:
    return datetime.now(UTC)


def _metadata(value: dict[str, object]) -> dict[str, object]:
    try:
        rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as error:
        raise KnowledgeConflict("Source metadata must be valid JSON") from error
    if len(rendered.encode("utf-8")) > MAX_SOURCE_METADATA_BYTES:
        raise KnowledgeConflict("Source metadata exceeds 32768 bytes")
    return value


def _source_uri(value: str | None, source_type: str) -> str | None:
    normalized = value.strip() if value else None
    if normalized is None:
        if source_type == "reference":
            raise KnowledgeConflict("Reference sources require an HTTP(S) source URI")
        return None
    if len(normalized) > 2048:
        raise KnowledgeConflict("Source URI exceeds 2048 characters")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise KnowledgeConflict("Source URI must be an absolute HTTP(S) URL")
    return normalized


def rank_chunks(
    rows: list[tuple[DocumentChunk, KnowledgeDocument, KnowledgeSource]],
    *,
    query: str,
    embedding: EmbeddingAdapter,
    limit: int,
    minimum_score: float,
) -> list[KnowledgeSearchHit]:
    query_vector = embedding.embed(query)
    hits: list[KnowledgeSearchHit] = []
    for chunk, document, source in rows:
        if chunk.embedding_model != embedding.model:
            continue
        score = cosine_similarity(query_vector, chunk.embedding)
        if score < minimum_score:
            continue
        hits.append(
            KnowledgeSearchHit(
                score=round(score, 8),
                text=chunk.content,
                citation=KnowledgeCitation(
                    source_id=source.id,
                    source_title=source.title,
                    source_uri=source.source_uri,
                    document_id=document.id,
                    filename=document.filename,
                    document_content_sha256=document.content_sha256,
                    document_created_at=document.created_at,
                    chunk_id=chunk.id,
                    chunk_ordinal=chunk.ordinal,
                    start_character=chunk.start_character,
                    end_character=chunk.end_character,
                    content_sha256=chunk.content_sha256,
                ),
            )
        )
    hits.sort(key=lambda item: (-item.score, str(item.citation.chunk_id)))
    return hits[:limit]


async def search_knowledge(
    database: AsyncSession,
    *,
    business_id: uuid.UUID,
    query: str,
    embedding: EmbeddingAdapter,
    limit: int,
    minimum_score: float,
) -> list[KnowledgeSearchHit]:
    query_vector = embedding.embed(query)
    distance = DocumentChunk.embedding.cosine_distance(query_vector)
    rows = (
        await database.execute(
            select(DocumentChunk, KnowledgeDocument, KnowledgeSource, distance)
            .join(KnowledgeDocument, KnowledgeDocument.id == DocumentChunk.document_id)
            .join(KnowledgeSource, KnowledgeSource.id == DocumentChunk.source_id)
            .where(
                DocumentChunk.business_id == business_id,
                KnowledgeDocument.status == "indexed",
                KnowledgeSource.status == "active",
                DocumentChunk.embedding_model == embedding.model,
                distance <= 1 - minimum_score,
            )
            .order_by(distance, DocumentChunk.id)
            .limit(limit)
        )
    ).all()
    return [
        KnowledgeSearchHit(
            score=round(1 - float(distance_value), 8),
            text=chunk.content,
            citation=KnowledgeCitation(
                source_id=source.id,
                source_title=source.title,
                source_uri=source.source_uri,
                document_id=document.id,
                filename=document.filename,
                document_content_sha256=document.content_sha256,
                document_created_at=document.created_at,
                chunk_id=chunk.id,
                chunk_ordinal=chunk.ordinal,
                start_character=chunk.start_character,
                end_character=chunk.end_character,
                content_sha256=chunk.content_sha256,
            ),
        )
        for chunk, document, source, distance_value in rows
    ]


class KnowledgeService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        storage: KnowledgeStorage | None = None,
        embedding: EmbeddingAdapter | None = None,
    ) -> None:
        self._session_factory = session_factory or get_session_factory()
        self._storage = storage or get_knowledge_storage()
        self._embedding = embedding or LocalFeatureHashEmbedding()

    async def dashboard(self, context: AuthContext) -> KnowledgeDashboard:
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
            sources = list(
                await database.scalars(
                    select(KnowledgeSource)
                    .where(KnowledgeSource.business_id == business.id)
                    .order_by(desc(KnowledgeSource.created_at), KnowledgeSource.id)
                )
            )
            source_ids = [source.id for source in sources]
            documents = (
                list(
                    await database.scalars(
                        select(KnowledgeDocument)
                        .where(KnowledgeDocument.source_id.in_(source_ids))
                        .order_by(desc(KnowledgeDocument.created_at), KnowledgeDocument.id)
                    )
                )
                if source_ids
                else []
            )
            by_source: dict[uuid.UUID, list[KnowledgeDocument]] = {
                source_id: [] for source_id in source_ids
            }
            for document in documents:
                by_source[document.source_id].append(document)
            return KnowledgeDashboard(
                business_id=business.id,
                sources=[SourceRecord(source, by_source[source.id]) for source in sources],
            )

    async def register_source(
        self,
        context: AuthContext,
        *,
        title: str,
        source_type: str,
        source_uri: str | None,
        metadata: dict[str, object],
    ) -> KnowledgeSource:
        normalized_title = title.strip()
        if not normalized_title or len(normalized_title) > 200:
            raise KnowledgeConflict("Source title must contain 1 to 200 characters")
        if source_type not in {"upload", "reference"}:
            raise KnowledgeConflict("Source type is unsupported")
        normalized_uri = _source_uri(source_uri, source_type)
        normalized_metadata = _metadata(metadata)
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                now = _now()
                source = KnowledgeSource(
                    id=uuid.uuid4(),
                    business_id=business.id,
                    source_type=source_type,
                    title=normalized_title,
                    source_uri=normalized_uri,
                    source_metadata=normalized_metadata,
                    status="active",
                    revision=1,
                    created_by_owner_id=context.owner.id,
                    created_at=now,
                    updated_at=now,
                    invalidated_at=None,
                    invalidation_reason=None,
                )
                database.add(source)
                await database.flush()
                await publish_event(
                    database,
                    business_id=business.id,
                    event_type="knowledge.source_registered",
                    aggregate_type="knowledge_source",
                    aggregate_id=str(source.id),
                    idempotency_key=f"knowledge-source:{source.id}:registered",
                    payload={
                        "source_id": str(source.id),
                        "source_type": source.source_type,
                        "title": source.title,
                    },
                )
            return source

    async def upload_document(
        self,
        context: AuthContext,
        *,
        source_id: uuid.UUID,
        filename: str,
        media_type: str,
        data: bytes,
    ) -> KnowledgeDocument:
        settings = get_settings()
        extracted = extract_text(
            data,
            filename=filename,
            media_type=media_type,
            max_bytes=settings.knowledge_max_upload_bytes,
            max_characters=settings.knowledge_max_extracted_characters,
        )
        chunks = chunk_text(extracted.text)
        vectors = [self._embedding.embed(chunk.content) for chunk in chunks]
        document_id = uuid.uuid4()
        storage_key: str | None = None
        try:
            async with self._session_factory() as database:
                async with database.begin():
                    business = await resolve_selected_business(database, context, lock=True)
                    source = await database.scalar(
                        select(KnowledgeSource)
                        .where(
                            KnowledgeSource.id == source_id,
                            KnowledgeSource.business_id == business.id,
                        )
                        .with_for_update()
                    )
                    if source is None:
                        raise KnowledgeSourceNotFound
                    if source.status != "active":
                        raise KnowledgeConflict("Invalidated sources cannot accept documents")
                    duplicate = await database.scalar(
                        select(KnowledgeDocument.id).where(
                            KnowledgeDocument.source_id == source.id,
                            KnowledgeDocument.content_sha256 == extracted.content_sha256,
                        )
                    )
                    if duplicate is not None:
                        raise KnowledgeConflict("This source already contains the uploaded content")
                    storage_key = (
                        f"{business.id}/{source.id}/{document_id}/{extracted.content_sha256}.bin"
                    )
                    await self._storage.put(storage_key, data)
                    document = self._document(
                        business_id=business.id,
                        source_id=source.id,
                        document_id=document_id,
                        storage_key=storage_key,
                        extracted=extracted,
                        chunks=chunks,
                    )
                    database.add(document)
                    await database.flush()
                    database.add_all(
                        [
                            DocumentChunk(
                                id=uuid.uuid4(),
                                business_id=business.id,
                                source_id=source.id,
                                document_id=document.id,
                                ordinal=chunk.ordinal,
                                start_character=chunk.start_character,
                                end_character=chunk.end_character,
                                content=chunk.content,
                                content_sha256=chunk.content_sha256,
                                estimated_tokens=chunk.estimated_tokens,
                                embedding_model=self._embedding.model,
                                embedding=vector,
                                created_at=document.created_at,
                            )
                            for chunk, vector in zip(chunks, vectors, strict=True)
                        ]
                    )
                    await database.flush()
                    await publish_event(
                        database,
                        business_id=business.id,
                        event_type="knowledge.document_indexed",
                        aggregate_type="knowledge_document",
                        aggregate_id=str(document.id),
                        idempotency_key=f"knowledge-document:{document.id}:indexed",
                        payload={
                            "source_id": str(source.id),
                            "document_id": str(document.id),
                            "filename": document.filename,
                            "content_sha256": document.content_sha256,
                            "chunk_count": document.chunk_count,
                        },
                    )
                return document
        except Exception:
            if storage_key is not None:
                await self._storage.delete(storage_key)
            raise

    def _document(
        self,
        *,
        business_id: uuid.UUID,
        source_id: uuid.UUID,
        document_id: uuid.UUID,
        storage_key: str,
        extracted: ExtractedDocument,
        chunks: list[TextChunk],
    ) -> KnowledgeDocument:
        now = _now()
        return KnowledgeDocument(
            id=document_id,
            business_id=business_id,
            source_id=source_id,
            filename=extracted.filename,
            media_type=extracted.media_type,
            storage_key=storage_key,
            byte_size=extracted.byte_size,
            content_sha256=extracted.content_sha256,
            extraction_version=EXTRACTION_VERSION,
            embedding_model=self._embedding.model,
            embedding_dimensions=self._embedding.dimensions,
            character_count=len(extracted.text),
            chunk_count=len(chunks),
            document_metadata={"original_filename": extracted.filename},
            status="indexed",
            revision=1,
            created_at=now,
            updated_at=now,
            invalidated_at=None,
            invalidation_reason=None,
        )

    async def search(
        self,
        context: AuthContext,
        *,
        query: str,
        limit: int = 10,
        minimum_score: float = 0.05,
    ) -> list[KnowledgeSearchHit]:
        normalized = query.strip()
        if not normalized or len(normalized) > 500:
            raise KnowledgeConflict("Search query must contain 1 to 500 characters")
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
            return await search_knowledge(
                database,
                business_id=business.id,
                query=normalized,
                embedding=self._embedding,
                limit=limit,
                minimum_score=minimum_score,
            )

    async def invalidate_source(
        self,
        context: AuthContext,
        source_id: uuid.UUID,
        *,
        expected_revision: int,
        reason: str,
    ) -> KnowledgeSource:
        normalized_reason = reason.strip()
        if not normalized_reason or len(normalized_reason) > 500:
            raise KnowledgeConflict("Invalidation reason must contain 1 to 500 characters")
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                source = await database.scalar(
                    select(KnowledgeSource)
                    .where(
                        KnowledgeSource.id == source_id,
                        KnowledgeSource.business_id == business.id,
                    )
                    .with_for_update()
                )
                if source is None:
                    raise KnowledgeSourceNotFound
                if source.status != "active" or source.revision != expected_revision:
                    raise KnowledgeConflict("The source changed; reload before invalidating")
                now = _now()
                source.status = "invalidated"
                source.revision += 1
                source.updated_at = now
                source.invalidated_at = now
                source.invalidation_reason = normalized_reason
                documents = list(
                    await database.scalars(
                        select(KnowledgeDocument)
                        .where(
                            KnowledgeDocument.source_id == source.id,
                            KnowledgeDocument.status == "indexed",
                        )
                        .with_for_update()
                    )
                )
                for document in documents:
                    document.status = "invalidated"
                    document.revision += 1
                    document.updated_at = now
                    document.invalidated_at = now
                    document.invalidation_reason = normalized_reason
                await publish_event(
                    database,
                    business_id=business.id,
                    event_type="knowledge.source_invalidated",
                    aggregate_type="knowledge_source",
                    aggregate_id=str(source.id),
                    idempotency_key=f"knowledge-source:{source.id}:invalidated:{source.revision}",
                    payload={
                        "source_id": str(source.id),
                        "revision": source.revision,
                        "invalidated_document_count": len(documents),
                    },
                )
            return source

    async def invalidate_document(
        self,
        context: AuthContext,
        document_id: uuid.UUID,
        *,
        expected_revision: int,
        reason: str,
    ) -> KnowledgeDocument:
        normalized_reason = reason.strip()
        if not normalized_reason or len(normalized_reason) > 500:
            raise KnowledgeConflict("Invalidation reason must contain 1 to 500 characters")
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                document = await database.scalar(
                    select(KnowledgeDocument)
                    .where(
                        KnowledgeDocument.id == document_id,
                        KnowledgeDocument.business_id == business.id,
                    )
                    .with_for_update()
                )
                if document is None:
                    raise KnowledgeDocumentNotFound
                if document.status != "indexed" or document.revision != expected_revision:
                    raise KnowledgeConflict("The document changed; reload before invalidating")
                now = _now()
                document.status = "invalidated"
                document.revision += 1
                document.updated_at = now
                document.invalidated_at = now
                document.invalidation_reason = normalized_reason
                await publish_event(
                    database,
                    business_id=business.id,
                    event_type="knowledge.document_invalidated",
                    aggregate_type="knowledge_document",
                    aggregate_id=str(document.id),
                    idempotency_key=(
                        f"knowledge-document:{document.id}:invalidated:{document.revision}"
                    ),
                    payload={
                        "source_id": str(document.source_id),
                        "document_id": str(document.id),
                        "revision": document.revision,
                    },
                )
            return document
