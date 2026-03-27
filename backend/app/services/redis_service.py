"""Redis service for caching, rate limiting, and pub/sub."""

import redis.asyncio as redis
import structlog
import json
from datetime import timedelta

logger = structlog.get_logger()


class RedisService:
    def __init__(self, url: str):
        self._url = url
        self._client: redis.Redis | None = None

    async def connect(self):
        self._client = redis.from_url(self._url, decode_responses=True)
        await self._client.ping()
        logger.info("Redis connected", url=self._url)

    async def disconnect(self):
        if self._client:
            await self._client.close()

    @property
    def client(self) -> redis.Redis:
        if not self._client:
            raise RuntimeError("Redis not connected")
        return self._client

    # ─── Rate Limiting ──────────────────────────────────────────────────

    async def check_rate_limit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Sliding window rate limiter. Returns True if under limit."""
        pipe = self.client.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds)
        results = await pipe.execute()
        return results[0] <= limit

    # ─── Session Cost Tracking ──────────────────────────────────────────

    async def track_cost(self, session_id: str, cost: float, budget: float) -> bool:
        """Track API cost per session. Returns False if budget exceeded."""
        key = f"cost:{session_id}"
        current = await self.client.incrbyfloat(key, cost)
        await self.client.expire(key, 86400)  # 24h TTL
        return current <= budget

    async def get_session_cost(self, session_id: str) -> float:
        val = await self.client.get(f"cost:{session_id}")
        return float(val) if val else 0.0

    # ─── Caching ────────────────────────────────────────────────────────

    async def cache_get(self, key: str) -> dict | None:
        val = await self.client.get(f"cache:{key}")
        return json.loads(val) if val else None

    async def cache_set(self, key: str, value: dict, ttl: int = 300):
        await self.client.setex(f"cache:{key}", ttl, json.dumps(value))

    # ─── Pub/Sub for Agent Events ───────────────────────────────────────

    async def publish_event(self, channel: str, event: dict):
        await self.client.publish(channel, json.dumps(event))
