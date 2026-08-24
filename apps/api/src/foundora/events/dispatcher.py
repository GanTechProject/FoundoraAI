from __future__ import annotations

import argparse
import asyncio

from foundora.events.service import dispatch_pending_events
from foundora.infrastructure.database import close_database


async def _run(limit: int) -> int:
    try:
        summary = await dispatch_pending_events(limit=limit)
        print(
            f"completed={summary.completed} "
            f"retry_scheduled={summary.retry_scheduled} "
            f"dead_lettered={summary.dead_lettered}"
        )
        return 0
    finally:
        await close_database()


def main() -> None:
    parser = argparse.ArgumentParser(description="Dispatch durable Foundora domain events once")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 1000:
        parser.error("--limit must be between 1 and 1000")
    raise SystemExit(asyncio.run(_run(args.limit)))


if __name__ == "__main__":
    main()
