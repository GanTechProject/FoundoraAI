from __future__ import annotations

import asyncio
import logging
import socket

from redis import Redis
from rq import Queue, Worker

from foundora.agents.recovery import recover_agent_runs
from foundora.config import get_settings
from foundora.events.service import dispatch_pending_events
from foundora.infrastructure.database import close_database
from foundora.logging import configure_logging
from foundora.sandbox.recovery import recover_sandbox_executions
from foundora.workflows.recovery import recover_workflow_runs


async def _recover_and_close() -> tuple[int, int, int, int, int, int, int, int, int]:
    try:
        agent_recovered, agent_failed = await recover_agent_runs()
        workflow_recovered, workflow_failed = await recover_workflow_runs()
        sandbox_recovered, sandbox_failed = await recover_sandbox_executions()
        event_summary = await dispatch_pending_events(limit=100)
        return (
            agent_recovered,
            agent_failed,
            workflow_recovered,
            workflow_failed,
            sandbox_recovered,
            sandbox_failed,
            event_summary.completed,
            event_summary.retry_scheduled,
            event_summary.dead_lettered,
        )
    finally:
        await close_database()


class FoundoraWorker(Worker):
    def run_maintenance_tasks(self) -> None:
        super().run_maintenance_tasks()  # type: ignore[no-untyped-call]
        (
            agent_recovered,
            agent_failed,
            workflow_recovered,
            workflow_failed,
            sandbox_recovered,
            sandbox_failed,
            events_completed,
            events_retried,
            events_dead_lettered,
        ) = asyncio.run(_recover_and_close())
        if agent_recovered or agent_failed:
            logging.getLogger(__name__).warning(
                "Agent run recovery reconciled durable state",
                extra={"event": "agent.run.recovered"},
            )
        if workflow_recovered or workflow_failed:
            logging.getLogger(__name__).warning(
                "Workflow run recovery reconciled durable state",
                extra={"event": "workflow.run.recovered"},
            )
        if sandbox_recovered or sandbox_failed:
            logging.getLogger(__name__).warning(
                "Sandbox execution recovery reconciled durable state",
                extra={
                    "event": "sandbox.execution.recovered",
                    "sandbox_recovered": sandbox_recovered,
                    "sandbox_failed": sandbox_failed,
                },
            )
        if events_completed or events_retried or events_dead_lettered:
            logging.getLogger(__name__).info(
                "Domain event deliveries reconciled",
                extra={"event": "domain_events.dispatched"},
            )


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)
    connection = Redis.from_url(
        settings.redis_url,
        decode_responses=False,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    connection.ping()
    queue = Queue(settings.worker_queue, connection=connection)
    (
        agent_recovered,
        agent_failed,
        workflow_recovered,
        workflow_failed,
        sandbox_recovered,
        sandbox_failed,
        events_completed,
        events_retried,
        events_dead_lettered,
    ) = asyncio.run(_recover_and_close())
    if agent_recovered or agent_failed:
        logger.warning(
            "Agent run recovery reconciled durable state",
            extra={"event": "agent.run.recovered"},
        )
    if workflow_recovered or workflow_failed:
        logger.warning(
            "Workflow run recovery reconciled durable state",
            extra={"event": "workflow.run.recovered"},
        )
    if sandbox_recovered or sandbox_failed:
        logger.warning(
            "Sandbox execution recovery reconciled durable state",
            extra={
                "event": "sandbox.execution.recovered",
                "sandbox_recovered": sandbox_recovered,
                "sandbox_failed": sandbox_failed,
            },
        )
    if events_completed or events_retried or events_dead_lettered:
        logger.info(
            "Domain event deliveries reconciled",
            extra={"event": "domain_events.dispatched"},
        )
    worker = FoundoraWorker(
        [queue],
        connection=connection,
        name=f"foundora-{socket.gethostname()}",
        maintenance_interval=15,
        worker_ttl=30,
    )
    logger.info(
        "Worker started",
        extra={"event": "worker.started"},
    )
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
