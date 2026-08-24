from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from foundora.api.auth import require_auth, require_csrf
from foundora.auth.service import AuthContext
from foundora.knowledge.embeddings import LocalFeatureHashEmbedding, cosine_similarity
from foundora.knowledge.extraction import ExtractionError, chunk_text, extract_text
from foundora.knowledge.service import KnowledgeDashboard, SourceRecord, rank_chunks
from foundora.knowledge.storage import LocalKnowledgeStorage
from foundora.main import app
from foundora.models import (
    DocumentChunk,
    KnowledgeDocument,
    KnowledgeSource,
    Owner,
    OwnerSession,
)


def auth_context(business_id: uuid.UUID | None = None) -> AuthContext:
    now = datetime.now(UTC)
    owner = Owner(
        id=uuid.uuid4(),
        singleton_key=1,
        email="owner@example.com",
        password_hash="hash",
        created_at=now,
        updated_at=now,
        password_changed_at=now,
    )
    return AuthContext(
        owner=owner,
        session=OwnerSession(
            id=uuid.uuid4(),
            owner_id=owner.id,
            token_hash="a" * 64,
            csrf_hash="b" * 64,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(minutes=30),
            expires_at=now + timedelta(hours=8),
            revoked_at=None,
            user_agent="test",
            selected_business_id=business_id or uuid.uuid4(),
        ),
    )


def knowledge_records(text: str) -> tuple[KnowledgeSource, KnowledgeDocument, DocumentChunk]:
    now = datetime.now(UTC)
    business_id = uuid.uuid4()
    source_id = uuid.uuid4()
    document_id = uuid.uuid4()
    embedding = LocalFeatureHashEmbedding()
    source = KnowledgeSource(
        id=source_id,
        business_id=business_id,
        source_type="upload",
        title="Founder research",
        source_uri="https://example.com/research",
        source_metadata={"author": "Founder"},
        status="active",
        revision=1,
        created_by_owner_id=uuid.uuid4(),
        created_at=now,
        updated_at=now,
        invalidated_at=None,
        invalidation_reason=None,
    )
    document = KnowledgeDocument(
        id=document_id,
        business_id=business_id,
        source_id=source_id,
        filename="research.md",
        media_type="text/markdown",
        storage_key="test/research.bin",
        byte_size=len(text.encode()),
        content_sha256="a" * 64,
        extraction_version="foundora-text-extractor.v1",
        embedding_model=embedding.model,
        embedding_dimensions=embedding.dimensions,
        character_count=len(text),
        chunk_count=1,
        document_metadata={},
        status="indexed",
        revision=1,
        created_at=now,
        updated_at=now,
        invalidated_at=None,
        invalidation_reason=None,
    )
    chunk = DocumentChunk(
        id=uuid.uuid4(),
        business_id=business_id,
        source_id=source_id,
        document_id=document_id,
        ordinal=0,
        start_character=0,
        end_character=len(text),
        content=text,
        content_sha256="b" * 64,
        estimated_tokens=10,
        embedding_model=embedding.model,
        embedding=embedding.embed(text),
        created_at=now,
    )
    return source, document, chunk


def test_extraction_and_chunking_preserve_offsets_and_reject_malformed_files() -> None:
    text = "Market evidence for independent studios.\n\n" + "Pricing signal. " * 120
    extracted = extract_text(
        text.encode(),
        filename="evidence.md",
        media_type="text/markdown",
        max_bytes=10_000,
        max_characters=10_000,
    )
    chunks = chunk_text(extracted.text, max_characters=300, overlap=40)

    assert len(chunks) > 1
    assert all(
        extracted.text[item.start_character : item.end_character] == item.content for item in chunks
    )
    assert extracted.content_sha256

    with pytest.raises(ExtractionError, match="UTF-8"):
        extract_text(
            b"\xff\xfe",
            filename="bad.txt",
            media_type="text/plain",
            max_bytes=100,
            max_characters=100,
        )
    with pytest.raises(ExtractionError, match="malformed"):
        extract_text(
            b'{"broken":',
            filename="bad.json",
            media_type="application/json",
            max_bytes=100,
            max_characters=100,
        )


def test_local_embedding_and_vector_ranking_are_deterministic_and_cited() -> None:
    embedding = LocalFeatureHashEmbedding()
    source, document, relevant = knowledge_records(
        "Independent studios need predictable subscription pricing"
    )
    _, unrelated_document, unrelated = knowledge_records(
        "Warehouse logistics and industrial freight schedules"
    )
    unrelated.source_id = source.id
    unrelated.document_id = unrelated_document.id

    first = embedding.embed("subscription pricing for studios")
    second = embedding.embed("subscription pricing for studios")
    assert first == second
    assert cosine_similarity(first, first) == pytest.approx(1.0)

    hits = rank_chunks(
        [(relevant, document, source), (unrelated, unrelated_document, source)],
        query="subscription pricing studios",
        embedding=embedding,
        limit=2,
        minimum_score=0,
    )
    assert hits[0].text == relevant.content
    assert hits[0].citation.source_uri == source.source_uri
    assert hits[0].citation.content_sha256 == relevant.content_sha256


@pytest.mark.asyncio
async def test_local_storage_round_trip_uses_scoped_key(tmp_path: Path) -> None:
    storage = LocalKnowledgeStorage(str(tmp_path))
    await storage.put("business/source/document/file.bin", b"durable evidence")
    stored = tmp_path / "business" / "source" / "document" / "file.bin"
    assert stored.read_bytes() == b"durable evidence"
    await storage.delete("business/source/document/file.bin")
    assert not stored.exists()


def test_dashboard_exposes_real_source_and_document_metadata() -> None:
    source, document, _ = knowledge_records("Retrievable evidence")
    context = auth_context(source.business_id)
    dashboard = KnowledgeDashboard(
        business_id=source.business_id,
        sources=[SourceRecord(source=source, documents=[document])],
    )
    app.dependency_overrides[require_auth] = lambda: context
    try:
        with (
            patch(
                "foundora.api.knowledge.KnowledgeService.dashboard",
                new=AsyncMock(return_value=dashboard),
            ),
            TestClient(app) as client,
        ):
            response = client.get("/knowledge")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["sources"][0]["documents"][0]["chunk_count"] == 1


def test_malformed_upload_fails_cleanly_before_persistence() -> None:
    context = auth_context()
    app.dependency_overrides[require_csrf] = lambda: context
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/knowledge/sources/{uuid.uuid4()}/documents",
                params={"filename": "broken.json", "file_media_type": "application/json"},
                content=b'{"broken":',
                headers={
                    "Content-Type": "application/octet-stream",
                    "Origin": "http://localhost:3000",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "malformed_json"


def test_knowledge_requires_authentication() -> None:
    with TestClient(app) as client:
        assert client.get("/knowledge").status_code == 401
        assert client.get("/knowledge/search?q=evidence").status_code == 401
