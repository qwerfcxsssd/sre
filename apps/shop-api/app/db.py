from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        self.engine: AsyncEngine = create_async_engine(
            settings.postgres_dsn,
            pool_size=settings.postgres_pool_size,
            max_overflow=settings.postgres_max_overflow,
            pool_pre_ping=True,
        )
        self.sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    async def ping(self) -> bool:
        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception:
            return False
        return True

    def pool_stats(self) -> tuple[int, int]:
        pool = self.engine.sync_engine.pool
        checked_out = getattr(pool, "checkedout", None)
        checked_in = getattr(pool, "checkedin", None)
        in_use = int(checked_out()) if callable(checked_out) else 0
        idle = int(checked_in()) if callable(checked_in) else 0
        return in_use, idle

    async def dispose(self) -> None:
        await self.engine.dispose()
