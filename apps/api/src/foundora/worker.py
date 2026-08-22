from __future__ import annotations

import logging
import socket

from redis import Redis
from rq import Queue, Worker

from foundora.config import get_settings
from foundora.logging import configure_logging


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
    worker = Worker(
        [queue],
        connection=connection,
        name=f"foundora-{socket.gethostname()}",
    )
    logger.info(
        "Worker started",
        extra={"event": "worker.started"},
    )
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
