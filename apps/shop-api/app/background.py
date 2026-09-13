from __future__ import annotations

import asyncio

import structlog

from app.cache import JobQueue
from app.db import Database
from app.deps import ReadinessProbe
from app.metrics import DB_POOL_CONNECTIONS, DEPENDENCY_UP, QUEUE_DEPTH

log = structlog.get_logger(__name__)


async def queue_depth_loop(queue: JobQueue, interval: float) -> None:
    while True:
        try:
            QUEUE_DEPTH.set(await queue.depth())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("queue_depth.failed", error=str(exc))
        await asyncio.sleep(interval)


async def dependency_probe_loop(probe: ReadinessProbe, interval: float) -> None:
    while True:
        DEPENDENCY_UP.labels(dependency="postgres").set(1 if await probe.postgres() else 0)
        DEPENDENCY_UP.labels(dependency="redis").set(1 if await probe.redis() else 0)
        await asyncio.sleep(interval)


async def db_pool_loop(database: Database, interval: float) -> None:
    while True:
        in_use, idle = database.pool_stats()
        DB_POOL_CONNECTIONS.labels(state="in_use").set(in_use)
        DB_POOL_CONNECTIONS.labels(state="idle").set(idle)
        await asyncio.sleep(interval)
