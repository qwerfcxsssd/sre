import time

import structlog
from fastapi import APIRouter, HTTPException, Query, status

from app.deps import CartDep, OrdersDep, ProductsDep, QueueDep
from app.metrics import ORDER_AMOUNT, ORDERS_CREATED
from app.schemas import (
    CartItem,
    CartItemIn,
    CartOut,
    CheckoutOut,
    OrderItemOut,
    OrderOut,
    ProductOut,
)

router = APIRouter(prefix="/api", tags=["shop"])
log = structlog.get_logger(__name__)


@router.post(
    "/cart/{user_id}/items", response_model=CartOut, status_code=status.HTTP_201_CREATED
)
async def add_cart_item(user_id: str, payload: CartItemIn, cart: CartDep) -> CartOut:
    items = await cart.add(user_id, payload.product_id, payload.quantity)
    return CartOut(
        user_id=user_id,
        items=[CartItem(**item) for item in items],
        ttl_seconds=cart.ttl_seconds,
    )


@router.get("/cart/{user_id}", response_model=CartOut)
async def get_cart(user_id: str, cart: CartDep) -> CartOut:
    items = await cart.get(user_id)
    return CartOut(
        user_id=user_id,
        items=[CartItem(**item) for item in items],
        ttl_seconds=cart.ttl_seconds,
    )


@router.post(
    "/checkout/{user_id}", response_model=CheckoutOut, status_code=status.HTTP_201_CREATED
)
async def checkout(
    user_id: str, cart: CartDep, products: ProductsDep, orders: OrdersDep, queue: QueueDep
) -> CheckoutOut:
    try:
        cart_items = await cart.get(user_id)
        if not cart_items:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="cart is empty"
            )

        catalog = await products.by_ids([item["product_id"] for item in cart_items])
        priced = [
            (item["product_id"], item["quantity"], catalog[item["product_id"]].price_rubles)
            for item in cart_items
            if item["product_id"] in catalog
        ]
        if not priced:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="no known products in cart",
            )

        order = await orders.create(user_id, priced)
    except Exception:
        ORDERS_CREATED.labels(result="failed").inc()
        raise

    ORDERS_CREATED.labels(result="success").inc()
    ORDER_AMOUNT.observe(float(order.total_rubles))

    await cart.clear(user_id)
    await queue.push(
        {
            "order_id": order.id,
            "user_id": user_id,
            "attempt": 1,
            "enqueued_at": time.time(),
        }
    )
    log.info("checkout.completed", order_id=order.id, total_rubles=order.total_rubles)

    return CheckoutOut(
        order_id=order.id, total_rubles=order.total_rubles, items=len(priced)
    )


@router.get("/orders/{order_id}", response_model=OrderOut)
async def get_order(order_id: str, orders: OrdersDep) -> OrderOut:
    order = await orders.get(order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order not found")
    return OrderOut(
        order_id=order.id,
        user_id=order.user_id,
        total_rubles=order.total_rubles,
        status=order.status,
        created_at=order.created_at,
        items=[
            OrderItemOut(
                product_id=item.product_id,
                quantity=item.quantity,
                price_rubles=item.price_rubles,
            )
            for item in order.items
        ],
    )


@router.get("/products", response_model=list[ProductOut])
async def list_products(
    products: ProductsDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ProductOut]:
    rows = await products.list_products(limit=limit, offset=offset)
    return [
        ProductOut(
            id=row.id,
            sku=row.sku,
            name=row.name,
            category=row.category,
            price_rubles=row.price_rubles,
            stock=row.stock,
        )
        for row in rows
    ]
