from __future__ import annotations

import asyncio
import uuid

from foundora.agents.runtime import AgentRuntime


def execute_agent_run(run_id: str) -> None:
    """RQ entry point; durable state remains in PostgreSQL, not the job result."""
    asyncio.run(AgentRuntime().execute(uuid.UUID(run_id)))
