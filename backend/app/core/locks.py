"""Thin Redis lock client using SET NX PX (single-instance Redlock pattern)."""
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as aioredis

from app.core.config import settings
from app.core.exceptions import SlotTakenError
from app.core.metrics import redis_lock_acquisitions

_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("del", KEYS[1])
else
  return 0
end
"""

_TTL_MS = 30_000  # 30 seconds


def _make_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


_redis_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = _make_redis()
    return _redis_client


def set_redis(client: aioredis.Redis) -> None:
    """Allow tests to inject a fake redis client."""
    global _redis_client
    _redis_client = client


class LockClient:
    def __init__(self, redis: aioredis.Redis):
        self._redis = redis
        self._owned: dict[str, str] = {}  # key → token

    async def acquire(self, key: str) -> bool:
        token = str(uuid.uuid4())
        acquired = await self._redis.set(key, token, nx=True, px=_TTL_MS)
        # key format: lock:{resource}:{id}:{slot} — extract resource type for label
        resource = key.split(":")[1] if key.count(":") >= 1 else key
        redis_lock_acquisitions.labels(
            resource=resource,
            result="acquired" if acquired else "failed",
        ).inc()
        if acquired:
            self._owned[key] = token
        return bool(acquired)

    async def release(self, key: str) -> None:
        token = self._owned.pop(key, None)
        if token:
            await self._redis.eval(_RELEASE_SCRIPT, 1, key, token)

    async def release_all(self) -> None:
        for key in list(self._owned):
            await self.release(key)


@asynccontextmanager
async def acquire_slot_locks(
    bay_id: str,
    tech_id: str,
    slot_key: str,
) -> AsyncGenerator[None, None]:
    """Context manager that acquires both locks or raises SlotTakenError."""
    client = LockClient(get_redis())
    bay_lock = f"lock:bay:{bay_id}:{slot_key}"
    tech_lock = f"lock:tech:{tech_id}:{slot_key}"

    bay_ok = await client.acquire(bay_lock)
    if not bay_ok:
        raise SlotTakenError()

    tech_ok = await client.acquire(tech_lock)
    if not tech_ok:
        await client.release(bay_lock)
        raise SlotTakenError()

    try:
        yield
    finally:
        await client.release_all()
