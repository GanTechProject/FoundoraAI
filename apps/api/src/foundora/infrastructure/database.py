from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from foundora.config import get_settings

_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_settings().database_url,
            pool_pre_ping=True,
            pool_recycle=300,
        )
    return _engine


async def probe_database() -> tuple[bool, str]:
    try:
        async with get_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True, "Reachable"
    except Exception as error:
        return False, f"Unavailable ({type(error).__name__})"


async def close_database() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
