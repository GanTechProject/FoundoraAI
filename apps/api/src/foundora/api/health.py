from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from foundora.infrastructure.database import probe_database
from foundora.infrastructure.redis import probe_redis

router = APIRouter(prefix="/health", tags=["health"])


class ComponentHealth(BaseModel):
    status: Literal["up", "down"]
    detail: str


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, ComponentHealth]


@router.get("/live", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    return LivenessResponse()


@router.get("/ready", response_model=ReadinessResponse)
async def readiness(response: Response) -> ReadinessResponse:
    database_result, redis_result = await asyncio.gather(probe_database(), probe_redis())
    checks = {
        "postgresql": ComponentHealth(
            status="up" if database_result[0] else "down", detail=database_result[1]
        ),
        "redis": ComponentHealth(
            status="up" if redis_result[0] else "down", detail=redis_result[1]
        ),
    }
    ready = all(component.status == "up" for component in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ready" if ready else "not_ready", checks=checks)
