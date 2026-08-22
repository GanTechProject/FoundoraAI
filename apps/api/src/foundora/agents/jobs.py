from __future__ import annotations

import asyncio
import uuid

from foundora.agents.runtime import AgentRuntime
from foundora.infrastructure.database import close_database


async def _execute(run_id: uuid.UUID) -> None:
    try:
        await AgentRuntime().execute(run_id)
    finally:
        await close_database()


def execute_agent_run(run_id: str) -> None:
    """RQ entry point; durable state remains in PostgreSQL, not the job result."""
    asyncio.run(_execute(uuid.UUID(run_id)))
