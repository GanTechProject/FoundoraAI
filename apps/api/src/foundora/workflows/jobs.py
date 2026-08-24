from __future__ import annotations

import asyncio
import uuid

from foundora.infrastructure.database import close_database
from foundora.workflows.runtime import WorkflowRuntime


async def _execute(run_id: uuid.UUID) -> None:
    try:
        await WorkflowRuntime().execute(run_id)
    finally:
        await close_database()


def execute_workflow_run(run_id: str) -> None:
    """RQ entry point; PostgreSQL remains the durable workflow authority."""
    asyncio.run(_execute(uuid.UUID(run_id)))
