from __future__ import annotations

import asyncio
import random
import time
from typing import Any

import structlog
from redis.exceptions import RedisError

from app.cache import JobQueue
from app.chaos import ChaosController
from app.config import Settings
from app.errors import DependencyDown
from app.metrics import WORKER_JOB_DURATION, WORKER_JOBS

log = structlog.get_logger(__name__)


class Worker:
    def __init__(
        self,
        queue: JobQueue,
        settings: Settings,
        controller: ChaosController,
        rng: random.Random | None = None,
    ) -> None:
        self._queue = queue
        self._settings = settings
        self._chaos = controller
        self._rng = rng or random.Random()

    async def run(self) -> None:
        poll = self._settings.worker_poll_seconds
        while True:
            try:
                if self._chaos.state.drop_redis:
                    await asyncio.sleep(poll)
                    continue
                job = await self._queue.pop(timeout=int(poll) or 1)
            except asyncio.CancelledError:
                raise
            except (RedisError, DependencyDown, OSError) as exc:
                log.warning("worker.poll_failed", error=str(exc))
                await asyncio.sleep(poll)
                continue

            if job is None:
                continue
            await self.process(job)

    async def process(self, job: dict[str, Any]) -> None:
        started = time.perf_counter()
        try:
            delay_ms = self._rng.uniform(
                float(self._settings.worker_min_delay_ms),
                float(self._settings.worker_max_delay_ms),
            )
            await asyncio.sleep(delay_ms / 1000.0)

            if self._rng.random() < self._settings.worker_failure_rate:
                await self._handle_failure(job)
                return

            WORKER_JOBS.labels(result="success").inc()
            log.info("worker.job_done", order_id=job.get("order_id"))
        finally:
            WORKER_JOB_DURATION.observe(time.perf_counter() - started)

    async def _handle_failure(self, job: dict[str, Any]) -> None:
        attempt = int(job.get("attempt", 1))
        if attempt >= self._settings.worker_max_attempts:
            WORKER_JOBS.labels(result="dead").inc()
            log.error("worker.job_dead", order_id=job.get("order_id"), attempt=attempt)
            await self._queue.bury({**job, "attempt": attempt, "failed_at": time.time()})
            return

        WORKER_JOBS.labels(result="retry").inc()
        log.warning("worker.job_retry", order_id=job.get("order_id"), attempt=attempt)
        await self._queue.push({**job, "attempt": attempt + 1})
