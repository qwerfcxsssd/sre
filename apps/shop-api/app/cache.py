from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.errors import DependencyDown
from app.metrics import CACHE_OPERATIONS


def cart_key(user_id: str) -> str:
    return f"cart:{user_id}"


class CartRepository:
    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    @property
    def ttl_seconds(self) -> int:
        return self._ttl

    async def get(self, user_id: str) -> list[dict[str, int]]:
        try:
            raw = await self._redis.get(cart_key(user_id))
        except RedisError as exc:
            CACHE_OPERATIONS.labels(operation="get", result="error").inc()
            raise DependencyDown("redis") from exc
        if raw is None:
            CACHE_OPERATIONS.labels(operation="get", result="miss").inc()
            return []
        CACHE_OPERATIONS.labels(operation="get", result="hit").inc()
        items: list[dict[str, int]] = json.loads(raw)
        return items

    async def add(self, user_id: str, product_id: int, quantity: int) -> list[dict[str, int]]:
        items = await self.get(user_id)
        for item in items:
            if item["product_id"] == product_id:
                item["quantity"] += quantity
                break
        else:
            items.append({"product_id": product_id, "quantity": quantity})
        try:
            await self._redis.set(cart_key(user_id), json.dumps(items), ex=self._ttl)
        except RedisError as exc:
            CACHE_OPERATIONS.labels(operation="set", result="error").inc()
            raise DependencyDown("redis") from exc
        CACHE_OPERATIONS.labels(operation="set", result="hit").inc()
        return items

    async def clear(self, user_id: str) -> None:
        try:
            removed = await self._redis.delete(cart_key(user_id))
        except RedisError as exc:
            CACHE_OPERATIONS.labels(operation="delete", result="error").inc()
            raise DependencyDown("redis") from exc
        result = "hit" if removed else "miss"
        CACHE_OPERATIONS.labels(operation="delete", result=result).inc()


class JobQueue:
    def __init__(self, redis: Redis, queue_key: str, dead_letter_key: str) -> None:
        self._redis = redis
        self._queue_key = queue_key
        self._dead_letter_key = dead_letter_key

    async def push(self, job: dict[str, Any]) -> None:
        try:
            await self._redis.lpush(self._queue_key, json.dumps(job))
        except RedisError as exc:
            raise DependencyDown("redis") from exc

    async def pop(self, timeout: int) -> dict[str, Any] | None:
        popped = await self._redis.brpop([self._queue_key], timeout=timeout)
        if popped is None:
            return None
        _, payload = popped
        job: dict[str, Any] = json.loads(payload)
        return job

    async def bury(self, job: dict[str, Any]) -> None:
        await self._redis.lpush(self._dead_letter_key, json.dumps(job))

    async def depth(self) -> int:
        return int(await self._redis.llen(self._queue_key))
