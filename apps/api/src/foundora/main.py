from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from foundora import __version__
from foundora.api.health import router as health_router
from foundora.config import get_settings
from foundora.infrastructure.database import close_database
from foundora.infrastructure.redis import close_redis
from foundora.logging import configure_logging, correlation_id

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)
correlation_pattern = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("API started", extra={"event": "api.started"})
    yield
    await close_redis()
    await close_database()
    logger.info("API stopped", extra={"event": "api.stopped"})


def create_app() -> FastAPI:
    application = FastAPI(
        title="Foundora API",
        description="Provider-independent Foundora application API",
        version=__version__,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Content-Type", "X-Correlation-ID"],
    )

    @application.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("X-Correlation-ID", "")
        request_id = incoming if correlation_pattern.fullmatch(incoming) else str(uuid.uuid4())
        token = correlation_id.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = request_id
            logger.info(
                "HTTP request completed",
                extra={
                    "event": "http.request.completed",
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "http_status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            return response
        finally:
            correlation_id.reset(token)

    application.include_router(health_router)
    return application


app = create_app()
