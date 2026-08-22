from __future__ import annotations

import asyncio
import logging
import socket

from redis import Redis
from rq import Queue, Worker

from foundora.agents.recovery import recover_agent_runs
from foundora.config import get_settings
from foundora.infrastructure.database import close_database
from foundora.logging import configure_logging


async def _recover_and_close() -> tuple[int, int]:
    try:
        return await recover_agent_runs()
    finally:
        await close_database()


class FoundoraWorker(Worker):
    def run_maintenance_tasks(self) -> None:
        super().run_maintenance_tasks()  # type: ignore[no-untyped-call]
        recovered, failed = asyncio.run(_recover_and_close())
        if recovered or failed:
            logging.getLogger(__name__).warning(
                "Agent run recovery reconciled durable state",
                extra={"event": "agent.run.recovered"},
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
    recovered, failed = asyncio.run(_recover_and_close())
    if recovered or failed:
        logger.warning(
            "Agent run recovery reconciled durable state",
            extra={"event": "agent.run.recovered"},
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
