from datetime import datetime

from pydantic import BaseModel, Field


class CartItemIn(BaseModel):
    product_id: int = Field(ge=1)
    quantity: int = Field(default=1, ge=1, le=50)


class CartItem(BaseModel):
    product_id: int
    quantity: int


class CartOut(BaseModel):
    user_id: str
    items: list[CartItem]
    ttl_seconds: int


class OrderItemOut(BaseModel):
    product_id: int
    quantity: int
    price_rubles: int


class OrderOut(BaseModel):
    order_id: str
    user_id: str
    total_rubles: int
    status: str
    created_at: datetime
    items: list[OrderItemOut]


class CheckoutOut(BaseModel):
    order_id: str
    total_rubles: int
    items: int


class ProductOut(BaseModel):
    id: int
    sku: str
    name: str
    category: str
    price_rubles: int
    stock: int


class ChaosPatch(BaseModel):
    latency_ms: int | None = Field(default=None, ge=0, le=60_000)
    latency_jitter_ms: int | None = Field(default=None, ge=0, le=60_000)
    error_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    cpu_burn: bool | None = None
    mem_leak_mb_per_min: int | None = Field(default=None, ge=0, le=4096)
    drop_postgres: bool | None = None
    drop_redis: bool | None = None
    fail_readiness: bool | None = None
    high_cardinality: bool | None = None


class ChaosOut(BaseModel):
    latency_ms: int
    latency_jitter_ms: int
    error_rate: float
    cpu_burn: bool
    mem_leak_mb_per_min: int
    drop_postgres: bool
    drop_redis: bool
    fail_readiness: bool
    high_cardinality: bool
    leaked_mb: int
