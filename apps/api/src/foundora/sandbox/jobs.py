from __future__ import annotations

import asyncio
import uuid

from foundora.infrastructure.database import close_database
from foundora.sandbox.runtime import SandboxRuntime


async def _execute(execution_id: uuid.UUID) -> None:
    try:
        await SandboxRuntime().execute(execution_id)
    finally:
        await close_database()


def execute_sandbox(execution_id: str) -> None:
    """RQ entry point; PostgreSQL and the runner receipt remain authoritative."""
    asyncio.run(_execute(uuid.UUID(execution_id)))
