import random

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models import Base, Product

CATEGORIES = ("electronics", "books", "grocery", "clothing", "toys", "garden")
NOUNS = ("lamp", "mug", "chair", "router", "kettle", "bag", "sensor", "mat", "cable", "clock")
ADJECTIVES = ("compact", "premium", "matte", "retro", "smart", "eco", "heavy", "slim")


async def run_migrations(
    engine: AsyncEngine, sessionmaker: async_sessionmaker[AsyncSession], seed_products: int
) -> int:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with sessionmaker() as session:
        existing = await session.scalar(select(func.count()).select_from(Product))
        if existing:
            return 0
        rng = random.Random(20240501)
        session.add_all(
            [
                Product(
                    id=index,
                    sku=f"SKU-{index:05d}",
                    name=f"{rng.choice(ADJECTIVES)} {rng.choice(NOUNS)} {index}",
                    category=rng.choice(CATEGORIES),
                    price_rubles=rng.choice([199, 349, 590, 1290, 2490, 4990, 9900, 19900]),
                    stock=rng.randint(5, 500),
                )
                for index in range(1, seed_products + 1)
            ]
        )
        await session.commit()
        return seed_products
