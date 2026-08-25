from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from foundora.infrastructure.database import get_session_factory
from foundora.knowledge.embeddings import EmbeddingAdapter, LocalFeatureHashEmbedding
from foundora.knowledge.service import search_knowledge


@dataclass(frozen=True)
class SearchRequest:
    business_id: uuid.UUID
    query: str
    limit: int = 8
    minimum_score: float = 0.05


@dataclass(frozen=True)
class SearchEvidence:
    evidence_id: str
    source: str
    source_title: str
    retrieval_date: str
    retrieved_at: str
    excerpt: str
    content_sha256: str


class SearchProvider(Protocol):
    """Provider-neutral, business-scoped search boundary."""

    @property
    def provider_id(self) -> str: ...

    async def search(self, request: SearchRequest) -> list[SearchEvidence]: ...


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class RegisteredKnowledgeSearchProvider:
    """Search founder-registered evidence without an external provider side effect."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        embedding: EmbeddingAdapter | None = None,
    ) -> None:
        self._session_factory = session_factory or get_session_factory()
        self._embedding = embedding or LocalFeatureHashEmbedding()

    @property
    def provider_id(self) -> str:
        return "registered_knowledge"

    async def search(self, request: SearchRequest) -> list[SearchEvidence]:
        retrieved_at = datetime.now(UTC)
        async with self._session_factory() as database:
            hits = await search_knowledge(
                database,
                business_id=request.business_id,
                query=request.query,
                embedding=self._embedding,
                limit=request.limit,
                minimum_score=request.minimum_score,
            )
        timestamp = _timestamp(retrieved_at)
        retrieval_date = retrieved_at.date().isoformat()
        return [
            SearchEvidence(
                evidence_id=str(hit.citation.chunk_id),
                source=(
                    hit.citation.source_uri
                    or (
                        f"knowledge://sources/{hit.citation.source_id}/documents/"
                        f"{hit.citation.document_id}#chunk-{hit.citation.chunk_ordinal}"
                    )
                ),
                source_title=hit.citation.source_title,
                retrieval_date=retrieval_date,
                retrieved_at=timestamp,
                excerpt=hit.text,
                content_sha256=hit.citation.content_sha256,
            )
            for hit in hits
        ]
