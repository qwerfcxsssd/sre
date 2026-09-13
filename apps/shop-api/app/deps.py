from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import CartRepository, JobQueue
from app.chaos import ChaosController, chaos
from app.config import Settings, get_settings
from app.db import Database
from app.errors import DependencyDown
from app.repository import OrderRepository, ProductRepository


class ReadinessProbe:
    def __init__(
        self, database: Database, redis: Redis, controller: ChaosController
    ) -> None:
        self._database = database
        self._redis = redis
        self._chaos = controller

    async def postgres(self) -> bool:
        if self._chaos.state.drop_postgres:
            return False
        return await self._database.ping()

    async def redis(self) -> bool:
        if self._chaos.state.drop_redis:
            return False
        try:
            return bool(await self._redis.ping())
        except (RedisError, OSError):
            return False


def get_settings_dep() -> Settings:
    return get_settings()


def get_chaos() -> ChaosController:
    return chaos


def get_database(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


def get_redis(request: Request) -> Redis:
    client: Redis = request.app.state.redis
    return client


async def get_session(
    database: Annotated[Database, Depends(get_database)],
    controller: Annotated[ChaosController, Depends(get_chaos)],
) -> AsyncIterator[AsyncSession]:
    if controller.state.drop_postgres:
        raise DependencyDown("postgres")
    try:
        async with database.sessionmaker() as session:
            yield session
    except (OperationalError, InterfaceError, OSError) as exc:
        raise DependencyDown("postgres") from exc


def get_product_repo(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProductRepository:
    return ProductRepository(session)


def get_order_repo(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OrderRepository:
    return OrderRepository(session)


def get_cart_repo(
    client: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    controller: Annotated[ChaosController, Depends(get_chaos)],
) -> CartRepository:
    if controller.state.drop_redis:
        raise DependencyDown("redis")
    return CartRepository(client, settings.cart_ttl_seconds)


def get_job_queue(
    client: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    controller: Annotated[ChaosController, Depends(get_chaos)],
) -> JobQueue:
    if controller.state.drop_redis:
        raise DependencyDown("redis")
    return JobQueue(client, settings.queue_key, settings.dead_letter_key)


def get_readiness_probe(
    database: Annotated[Database, Depends(get_database)],
    client: Annotated[Redis, Depends(get_redis)],
    controller: Annotated[ChaosController, Depends(get_chaos)],
) -> ReadinessProbe:
    return ReadinessProbe(database, client, controller)


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
ChaosDep = Annotated[ChaosController, Depends(get_chaos)]
CartDep = Annotated[CartRepository, Depends(get_cart_repo)]
QueueDep = Annotated[JobQueue, Depends(get_job_queue)]
ProductsDep = Annotated[ProductRepository, Depends(get_product_repo)]
OrdersDep = Annotated[OrderRepository, Depends(get_order_repo)]
ReadinessDep = Annotated[ReadinessProbe, Depends(get_readiness_probe)]
