from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from foundora.api.auth import require_auth, require_csrf
from foundora.auth.service import AuthContext
from foundora.config import get_settings
from foundora.knowledge.extraction import ExtractionError
from foundora.knowledge.service import (
    KnowledgeConflict,
    KnowledgeDashboard,
    KnowledgeDocumentNotFound,
    KnowledgeSearchHit,
    KnowledgeService,
    KnowledgeSourceNotFound,
)
from foundora.knowledge.storage import KnowledgeStorageError
from foundora.models import KnowledgeDocument, KnowledgeSource

router = APIRouter(prefix="/knowledge", tags=["knowledge ingestion"])
SourceType = Literal["upload", "reference"]
SourceStatus = Literal["active", "invalidated"]
DocumentStatus = Literal["indexed", "invalidated"]


class RegisterSourceRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    source_type: SourceType
    source_uri: str | None = Field(default=None, max_length=2048)
    metadata: dict[str, object] = Field(default_factory=dict)


class InvalidateRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class KnowledgeDocumentView(BaseModel):
    id: UUID
    source_id: UUID
    filename: str
    media_type: str
    byte_size: int
    content_sha256: str
    extraction_version: str
    embedding_model: str
    embedding_dimensions: int
    character_count: int
    chunk_count: int
    metadata: dict[str, object]
    status: DocumentStatus
    revision: int
    created_at: datetime
    updated_at: datetime
    invalidated_at: datetime | None
    invalidation_reason: str | None


class KnowledgeSourceView(BaseModel):
    id: UUID
    business_id: UUID
    source_type: SourceType
    title: str
    source_uri: str | None
    metadata: dict[str, object]
    status: SourceStatus
    revision: int
    created_at: datetime
    updated_at: datetime
    invalidated_at: datetime | None
    invalidation_reason: str | None
    documents: list[KnowledgeDocumentView]


class KnowledgeDashboardView(BaseModel):
    business_id: UUID
    supported_file_types: list[str]
    embedding_model: str
    sources: list[KnowledgeSourceView]


class CitationView(BaseModel):
    source_id: UUID
    source_title: str
    source_uri: str | None
    document_id: UUID
    filename: str
    document_content_sha256: str
    document_created_at: datetime
    chunk_id: UUID
    chunk_ordinal: int
    start_character: int
    end_character: int
    content_sha256: str


class SearchHitView(BaseModel):
    score: float
    text: str
    citation: CitationView


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHitView]


def _document_view(document: KnowledgeDocument) -> KnowledgeDocumentView:
    return KnowledgeDocumentView(
        id=document.id,
        source_id=document.source_id,
        filename=document.filename,
        media_type=document.media_type,
        byte_size=document.byte_size,
        content_sha256=document.content_sha256,
        extraction_version=document.extraction_version,
        embedding_model=document.embedding_model,
        embedding_dimensions=document.embedding_dimensions,
        character_count=document.character_count,
        chunk_count=document.chunk_count,
        metadata=document.document_metadata,
        status=document.status,  # type: ignore[arg-type]
        revision=document.revision,
        created_at=document.created_at,
        updated_at=document.updated_at,
        invalidated_at=document.invalidated_at,
        invalidation_reason=document.invalidation_reason,
    )


def _source_view(
    source: KnowledgeSource, documents: list[KnowledgeDocument]
) -> KnowledgeSourceView:
    return KnowledgeSourceView(
        id=source.id,
        business_id=source.business_id,
        source_type=source.source_type,  # type: ignore[arg-type]
        title=source.title,
        source_uri=source.source_uri,
        metadata=source.source_metadata,
        status=source.status,  # type: ignore[arg-type]
        revision=source.revision,
        created_at=source.created_at,
        updated_at=source.updated_at,
        invalidated_at=source.invalidated_at,
        invalidation_reason=source.invalidation_reason,
        documents=[_document_view(document) for document in documents],
    )


def _dashboard_view(record: KnowledgeDashboard) -> KnowledgeDashboardView:
    embedding_model = "foundora.local-feature-hash.v1"
    for source in record.sources:
        if source.documents:
            embedding_model = source.documents[0].embedding_model
            break
    return KnowledgeDashboardView(
        business_id=record.business_id,
        supported_file_types=[".txt", ".md", ".json", ".csv"],
        embedding_model=embedding_model,
        sources=[_source_view(item.source, item.documents) for item in record.sources],
    )


def _search_hit_view(hit: KnowledgeSearchHit) -> SearchHitView:
    return SearchHitView(
        score=hit.score,
        text=hit.text,
        citation=CitationView(**vars(hit.citation)),
    )


def _not_found(error: Exception) -> HTTPException:
    detail = (
        "Knowledge source not found"
        if isinstance(error, KnowledgeSourceNotFound)
        else "Knowledge document not found"
    )
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _conflict(error: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


@router.get("", response_model=KnowledgeDashboardView)
async def knowledge_dashboard(
    context: Annotated[AuthContext, Depends(require_auth)], response: Response
) -> KnowledgeDashboardView:
    response.headers["Cache-Control"] = "no-store"
    return _dashboard_view(await KnowledgeService().dashboard(context))


@router.post("/sources", response_model=KnowledgeSourceView, status_code=status.HTTP_201_CREATED)
async def register_source(
    payload: RegisterSourceRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> KnowledgeSourceView:
    try:
        source = await KnowledgeService().register_source(context, **payload.model_dump())
    except KnowledgeConflict as error:
        raise _conflict(error) from error
    return _source_view(source, [])


@router.post(
    "/sources/{source_id}/documents",
    response_model=KnowledgeDocumentView,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    source_id: UUID,
    filename: Annotated[str, Query(min_length=1, max_length=255)],
    file_media_type: Annotated[str, Query(min_length=1, max_length=120)],
    request: Request,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> KnowledgeDocumentView:
    request_media_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if request_media_type != "application/octet-stream":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Upload requests must use application/octet-stream",
        )
    maximum = get_settings().knowledge_max_upload_bytes
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > maximum:
        raise HTTPException(
            status_code=413, detail="The uploaded file exceeds the configured limit"
        )
    body = bytearray()
    async for part in request.stream():
        body.extend(part)
        if len(body) > maximum:
            raise HTTPException(
                status_code=413, detail="The uploaded file exceeds the configured limit"
            )
    try:
        document = await KnowledgeService().upload_document(
            context,
            source_id=source_id,
            filename=filename,
            media_type=file_media_type,
            data=bytes(body),
        )
    except KnowledgeSourceNotFound as error:
        raise _not_found(error) from error
    except (ExtractionError, KnowledgeConflict) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": getattr(error, "code", "invalid_knowledge_document"),
                "message": str(error),
            },
        ) from error
    except KnowledgeStorageError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Knowledge storage is unavailable",
        ) from error
    return _document_view(document)


@router.get("/search", response_model=SearchResponse)
async def search_knowledge_endpoint(
    query: Annotated[str, Query(alias="q", min_length=1, max_length=500)],
    context: Annotated[AuthContext, Depends(require_auth)],
    response: Response,
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
    minimum_score: Annotated[float, Query(ge=0, le=1)] = 0.05,
) -> SearchResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        hits = await KnowledgeService().search(
            context,
            query=query,
            limit=limit,
            minimum_score=minimum_score,
        )
    except KnowledgeConflict as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return SearchResponse(query=query.strip(), hits=[_search_hit_view(hit) for hit in hits])


@router.post("/sources/{source_id}/invalidate", response_model=KnowledgeSourceView)
async def invalidate_source(
    source_id: UUID,
    payload: InvalidateRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> KnowledgeSourceView:
    try:
        source = await KnowledgeService().invalidate_source(
            context, source_id, **payload.model_dump()
        )
    except KnowledgeSourceNotFound as error:
        raise _not_found(error) from error
    except KnowledgeConflict as error:
        raise _conflict(error) from error
    return _source_view(source, [])


@router.post("/documents/{document_id}/invalidate", response_model=KnowledgeDocumentView)
async def invalidate_document(
    document_id: UUID,
    payload: InvalidateRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> KnowledgeDocumentView:
    try:
        document = await KnowledgeService().invalidate_document(
            context, document_id, **payload.model_dump()
        )
    except KnowledgeDocumentNotFound as error:
        raise _not_found(error) from error
    except KnowledgeConflict as error:
        raise _conflict(error) from error
    return _document_view(document)
