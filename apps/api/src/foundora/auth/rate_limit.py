from __future__ import annotations

import hashlib

from redis.asyncio import Redis


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = max(retry_after, 1)
        super().__init__("rate limit exceeded")


async def enforce_rate_limit(
    redis: Redis,
    *,
    scope: str,
    identity: str,
    limit: int,
    window_seconds: int,
) -> None:
    identity_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    key = f"foundora:rate:{scope}:{identity_hash}"
    async with redis.pipeline(transaction=True) as pipeline:
        pipeline.incr(key)
        pipeline.expire(key, window_seconds, nx=True)
        pipeline.ttl(key)
        count, _, ttl = await pipeline.execute()
    if int(count) > limit:
        raise RateLimitExceeded(int(ttl) if int(ttl) > 0 else window_seconds)
