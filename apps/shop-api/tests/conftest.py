from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.chaos import chaos
from app.deps import (
    ReadinessProbe,
    get_database,
    get_order_repo,
    get_product_repo,
    get_readiness_probe,
    get_redis,
)
from app.errors import DependencyDown
from app.main import create_app
from app.models import Order, OrderItem, Product

CART_TTL = 1800


class FakeRedis:
    """Just enough of redis-py asyncio for the cart, the queue and the probe."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.values[key] = value
        return True

    async def delete(self, key: str) -> int:
        return 1 if self.values.pop(key, None) is not None else 0

    async def lpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    async def brpop(self, keys: Sequence[str], timeout: int = 0) -> tuple[str, str] | None:
        for key in keys:
            queue = self.lists.get(key)
            if queue:
                return key, queue.pop()
        return None

    async def llen(self, key: str) -> int:
        return len(self.lists.get(key, []))

    async def ping(self) -> bool:
        return True


class FakeDatabase:
    async def ping(self) -> bool:
        return True

    def pool_stats(self) -> tuple[int, int]:
        return 0, 0


class FakeProductRepository:
    def __init__(self, products: Sequence[Product]) -> None:
        self._products = list(products)

    async def list_products(self, limit: int, offset: int) -> Sequence[Product]:
        return self._products[offset : offset + limit]

    async def by_ids(self, product_ids: Sequence[int]) -> dict[int, Product]:
        wanted = set(product_ids)
        return {p.id: p for p in self._products if p.id in wanted}


class FakeOrderRepository:
    def __init__(self, storage: dict[str, Order]) -> None:
        self._storage = storage

    async def create(self, user_id: str, items: Sequence[tuple[int, int, int]]) -> Order:
        order = Order(
            id=str(uuid.uuid4()),
            user_id=user_id,
            total_rubles=sum(quantity * price for _, quantity, price in items),
            status="created",
            created_at=datetime.now(UTC),
            items=[
                OrderItem(product_id=product_id, quantity=quantity, price_rubles=price)
                for product_id, quantity, price in items
            ],
        )
        self._storage[order.id] = order
        return order

    async def get(self, order_id: str) -> Order | None:
        return self._storage.get(order_id)


@pytest.fixture(autouse=True)
def reset_chaos() -> Any:
    chaos.reset()
    yield
    chaos.reset()


@pytest.fixture
def products() -> list[Product]:
    return [
        Product(
            id=index,
            sku=f"SKU-{index:05d}",
            name=f"product {index}",
            category="test",
            price_rubles=100 * index,
            stock=10,
        )
        for index in range(1, 6)
    ]


@pytest.fixture
def redis_client() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
async def client(
    products: list[Product], redis_client: FakeRedis
) -> AsyncIterator[AsyncClient]:
    app = create_app()
    orders: dict[str, Order] = {}

    def product_repo() -> FakeProductRepository:
        if chaos.state.drop_postgres:
            raise DependencyDown("postgres")
        return FakeProductRepository(products)

    def order_repo() -> FakeOrderRepository:
        if chaos.state.drop_postgres:
            raise DependencyDown("postgres")
        return FakeOrderRepository(orders)

    app.dependency_overrides[get_redis] = lambda: redis_client
    app.dependency_overrides[get_database] = FakeDatabase
    app.dependency_overrides[get_product_repo] = product_repo
    app.dependency_overrides[get_order_repo] = order_repo
    app.dependency_overrides[get_readiness_probe] = lambda: ReadinessProbe(
        FakeDatabase(),  # type: ignore[arg-type]
        redis_client,  # type: ignore[arg-type]
        chaos,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://shop-api") as http_client:
        yield http_client
