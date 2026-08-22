from __future__ import annotations

from redis import Redis
from rq import Worker

from foundora.config import get_settings


def main() -> None:
    settings = get_settings()
    connection = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    workers = Worker.all(connection=connection)
    if not any(worker.name.startswith("foundora-") for worker in workers):
        raise SystemExit("No Foundora worker is registered")


if __name__ == "__main__":
    main()
