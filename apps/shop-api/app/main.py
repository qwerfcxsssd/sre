from __future__ import annotations

import asyncio
import platform
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.exc import InterfaceError, OperationalError

from app.background import db_pool_loop, dependency_probe_loop, queue_depth_loop
from app.cache import JobQueue
from app.chaos import chaos
from app.config import Settings, get_settings
from app.db import Database
from app.deps import ReadinessProbe
from app.errors import DependencyDown
from app.logging_conf import configure_logging
from app.metrics import set_build_info
from app.middleware import ChaosMiddleware, MetricsMiddleware
from app.migrations import run_migrations
from app.routers import admin, api, health
from app.worker import Worker

log = structlog.get_logger(__name__)

MIGRATION_RETRY_SECONDS = 3.0
MIGRATION_RETRY_MAX_SECONDS = 30.0


async def migrate_until_ready(database: Database, settings: Settings) -> None:
    """Keep retrying in the background so a cold Postgres never blocks startup.

    Blocking the lifespan here would leave the port closed while the liveness
    probe is already counting failures; readiness keeps traffic away instead.
    """
    delay = MIGRATION_RETRY_SECONDS
    attempt = 0
    while True:
        attempt += 1
        try:
            seeded = await run_migrations(
                database.engine, database.sessionmaker, settings.seed_products
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("migrations.failed", attempt=attempt, error=str(exc))
            await asyncio.sleep(delay)
            delay = min(delay * 2, MIGRATION_RETRY_MAX_SECONDS)
            continue
        log.info("migrations.applied", attempt=attempt, seeded_products=seeded)
        return


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    database = Database(settings)
    redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    queue = JobQueue(redis_client, settings.queue_key, settings.dead_letter_key)
    probe = ReadinessProbe(database, redis_client, chaos)

    app.state.database = database
    app.state.redis = redis_client
    app.state.queue = queue

    worker = Worker(queue, settings, chaos)
    tasks = [
        asyncio.create_task(migrate_until_ready(database, settings), name="migrations"),
        asyncio.create_task(worker.run(), name="worker"),
        asyncio.create_task(
            queue_depth_loop(queue, settings.queue_depth_interval_seconds),
            name="queue-depth",
        ),
        asyncio.create_task(
            dependency_probe_loop(probe, settings.dependency_probe_interval_seconds),
            name="dependency-probe",
        ),
        asyncio.create_task(
            db_pool_loop(database, settings.db_pool_interval_seconds), name="db-pool"
        ),
    ]
    log.info("startup.complete", version=settings.version, commit=settings.commit)

    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        chaos.shutdown()
        await redis_client.aclose()
        await database.dispose()
        log.info("shutdown.complete")


async def dependency_down_handler(request: Request, exc: Exception) -> JSONResponse:
    dependency = exc.dependency if isinstance(exc, DependencyDown) else "unknown"
    log.error("dependency.down", dependency=dependency, path=request.url.path)
    return JSONResponse(
        {"detail": f"dependency unavailable: {dependency}", "dependency": dependency},
        status_code=503,
    )


async def postgres_failure_handler(request: Request, exc: Exception) -> JSONResponse:
    """A real driver outage answers like the simulated one, so both look the same."""
    log.error("dependency.error", dependency="postgres", path=request.url.path, error=str(exc))
    return JSONResponse(
        {"detail": "dependency unavailable: postgres", "dependency": "postgres"},
        status_code=503,
    )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="shop-api",
        version=settings.version,
        lifespan=lifespan,
        docs_url="/docs",
    )
    app.include_router(api.router)
    app.include_router(admin.router)
    app.include_router(health.router)

    app.add_middleware(ChaosMiddleware, controller=chaos)
    app.add_middleware(MetricsMiddleware, routes=app.routes, controller=chaos)
    app.add_exception_handler(DependencyDown, dependency_down_handler)
    app.add_exception_handler(OperationalError, postgres_failure_handler)
    app.add_exception_handler(InterfaceError, postgres_failure_handler)

    set_build_info(settings.version, settings.commit, platform.python_version())
    return app


app = create_app()
