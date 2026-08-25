from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from foundora import __version__
from foundora.api.agents import router as agents_router
from foundora.api.auth import router as auth_router
from foundora.api.brand import router as brand_router
from foundora.api.business_brain import router as business_brain_router
from foundora.api.businesses import router as businesses_router
from foundora.api.events import router as events_router
from foundora.api.governance import router as governance_router
from foundora.api.health import router as health_router
from foundora.api.knowledge import router as knowledge_router
from foundora.api.memory import router as memory_router
from foundora.api.model_gateway import router as model_gateway_router
from foundora.api.onboarding import router as onboarding_router
from foundora.api.product_offers import router as product_offers_router
from foundora.api.strategy import router as strategy_router
from foundora.api.tasks import router as tasks_router
from foundora.api.website_specifications import router as website_specifications_router
from foundora.api.workflows import router as workflows_router
from foundora.business.context import NoSelectedBusiness
from foundora.config import get_settings
from foundora.infrastructure.database import close_database
from foundora.infrastructure.redis import close_redis
from foundora.logging import configure_logging, correlation_id

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)
correlation_pattern = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def add_security_headers(response: Response) -> None:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if settings.environment == "production":
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"


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
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Correlation-ID", "X-CSRF-Token"],
    )

    @application.exception_handler(NoSelectedBusiness)
    async def no_selected_business(_: Request, __: NoSelectedBusiness) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": "No active business is selected"},
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
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                origin = request.headers.get("Origin")
                if origin not in settings.cors_origins:
                    response = Response(
                        content='{"detail":"Request origin is not allowed"}',
                        status_code=403,
                        media_type="application/json",
                    )
                else:
                    response = await call_next(request)
            else:
                response = await call_next(request)
            response.headers["X-Correlation-ID"] = request_id
            add_security_headers(response)
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
    application.include_router(auth_router)
    application.include_router(agents_router)
    application.include_router(businesses_router)
    application.include_router(business_brain_router)
    application.include_router(onboarding_router)
    application.include_router(model_gateway_router)
    application.include_router(tasks_router)
    application.include_router(workflows_router)
    application.include_router(governance_router)
    application.include_router(events_router)
    application.include_router(knowledge_router)
    application.include_router(memory_router)
    application.include_router(strategy_router)
    application.include_router(product_offers_router)
    application.include_router(brand_router)
    application.include_router(website_specifications_router)
    return application


app = create_app()
