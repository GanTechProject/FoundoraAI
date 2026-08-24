from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel

from foundora.api.auth import require_auth
from foundora.auth.service import AuthContext
from foundora.business_brain.service import (
    SOURCE_TYPES,
    BusinessContext,
    ContextBuildRequest,
    ContextService,
    ExclusionReason,
    SelectionStatus,
    SourceType,
    SourceValidity,
)

router = APIRouter(prefix="/brain", tags=["business brain"])
_PURPOSE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")


class ContextSourceView(BaseModel):
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


class BusinessContextView(BaseModel):
    context_id: str
    business_id: str
    purpose: str
    generated_at: datetime
    token_budget: int
    estimated_tokens: int
    budget_remaining: int
    selected_source_types: list[SourceType]
    sources: list[ContextSourceView]
    unavailable_sources: dict[str, str]
    context: str
    context_sha256: str


def _source_types(value: str | None) -> frozenset[SourceType]:
    if value is None:
        return frozenset(SOURCE_TYPES)
    names = [name.strip().lower() for name in value.split(",") if name.strip()]
    unknown = sorted(set(names).difference(SOURCE_TYPES))
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "unsupported_context_source",
                "message": f"Unsupported context source: {', '.join(unknown)}",
            },
        )
    return frozenset(names)  # type: ignore[arg-type]


def _view(result: BusinessContext) -> BusinessContextView:
    return BusinessContextView(
        context_id=result.context_id,
        business_id=str(result.business_id),
        purpose=result.purpose,
        generated_at=result.generated_at,
        token_budget=result.token_budget,
        estimated_tokens=result.estimated_tokens,
        budget_remaining=result.budget_remaining,
        selected_source_types=list(result.selected_source_types),
        sources=[
            ContextSourceView(
                source_type=item.source_type,
                source_reference=item.source_reference,
                source_version=item.source_version,
                authority=item.authority,
                label=item.label,
                updated_at=item.updated_at,
                validity=item.validity,
                selection_status=item.selection_status,
                exclusion_reason=item.exclusion_reason,
                estimated_tokens=item.estimated_tokens,
                content_sha256=item.content_sha256,
                content=item.content,
            )
            for item in result.sources
        ],
        unavailable_sources=result.unavailable_sources,
        context=result.context,
        context_sha256=result.context_sha256,
    )


@router.get("/context", response_model=BusinessContextView)
async def build_context(
    context: Annotated[AuthContext, Depends(require_auth)],
    response: Response,
    purpose: Annotated[str, Query(min_length=1, max_length=80)] = "general",
    token_budget: Annotated[int, Query(ge=256, le=32_768)] = 4096,
    sources: Annotated[str | None, Query(max_length=512)] = None,
    knowledge_query: Annotated[str | None, Query(min_length=1, max_length=500)] = None,
    memory_query: Annotated[str | None, Query(min_length=1, max_length=500)] = None,
) -> BusinessContextView:
    normalized_purpose = purpose.strip().lower()
    if _PURPOSE_PATTERN.fullmatch(normalized_purpose) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "invalid_context_purpose",
                "message": "Context purpose must be a lowercase identifier",
            },
        )
    result = await ContextService().build(
        context,
        ContextBuildRequest(
            purpose=normalized_purpose,
            token_budget=token_budget,
            selected_source_types=_source_types(sources),
            knowledge_query=knowledge_query.strip() if knowledge_query else None,
            memory_query=memory_query.strip() if memory_query else None,
        ),
    )
    response.headers["Cache-Control"] = "no-store"
    return _view(result)
