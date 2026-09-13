import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order, OrderItem, Product


class ProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_products(self, limit: int, offset: int) -> Sequence[Product]:
        stmt = select(Product).order_by(Product.id).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def by_ids(self, product_ids: Sequence[int]) -> dict[int, Product]:
        if not product_ids:
            return {}
        stmt = select(Product).where(Product.id.in_(product_ids))
        result = await self._session.execute(stmt)
        return {product.id: product for product in result.scalars().all()}


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, user_id: str, items: Sequence[tuple[int, int, int]]
    ) -> Order:
        order = Order(
            id=str(uuid.uuid4()),
            user_id=user_id,
            total_rubles=sum(quantity * price for _, quantity, price in items),
            status="created",
            items=[
                OrderItem(product_id=product_id, quantity=quantity, price_rubles=price)
                for product_id, quantity, price in items
            ],
        )
        self._session.add(order)
        await self._session.commit()
        return order

    async def get(self, order_id: str) -> Order | None:
        stmt = select(Order).where(Order.id == order_id)
        result = await self._session.execute(stmt)
        return result.scalars().first()
