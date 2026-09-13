from functools import lru_cache
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SHOP_", env_file=".env", extra="ignore")

    version: str = "0.0.0"
    commit: str = "unknown"
    log_level: str = "INFO"

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str = "shop"
    postgres_password: str = "shop"
    postgres_db: str = "shop"
    postgres_pool_size: int = 10
    postgres_max_overflow: int = 5

    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None

    cart_ttl_seconds: int = 1800
    queue_key: str = "shop:jobs"
    dead_letter_key: str = "shop:jobs:dead"

    worker_poll_seconds: float = 1.0
    worker_failure_rate: float = 0.03
    worker_max_attempts: int = 3
    worker_min_delay_ms: int = 50
    worker_max_delay_ms: int = 400

    seed_products: int = 200
    queue_depth_interval_seconds: float = 5.0
    dependency_probe_interval_seconds: float = 10.0
    db_pool_interval_seconds: float = 5.0

    @property
    def postgres_dsn(self) -> str:
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password)
        return (
            f"postgresql+asyncpg://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        auth = f":{quote_plus(self.redis_password)}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
