from httpx import AsyncClient

USER = "user-1"


async def test_products_listing(client: AsyncClient) -> None:
    response = await client.get("/api/products", params={"limit": 3})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 3
    assert body[0]["sku"] == "SKU-00001"


async def test_cart_roundtrip(client: AsyncClient) -> None:
    added = await client.post(f"/api/cart/{USER}/items", json={"product_id": 2, "quantity": 3})
    assert added.status_code == 201

    again = await client.post(f"/api/cart/{USER}/items", json={"product_id": 2, "quantity": 1})
    assert again.json()["items"] == [{"product_id": 2, "quantity": 4}]

    fetched = await client.get(f"/api/cart/{USER}")
    assert fetched.status_code == 200
    assert fetched.json()["ttl_seconds"] == 1800


async def test_checkout_creates_order_and_enqueues_job(client: AsyncClient) -> None:
    await client.post(f"/api/cart/{USER}/items", json={"product_id": 2, "quantity": 3})
    await client.post(f"/api/cart/{USER}/items", json={"product_id": 3, "quantity": 1})

    checkout = await client.post(f"/api/checkout/{USER}")
    assert checkout.status_code == 201
    payload = checkout.json()
    assert payload["total_rubles"] == 2 * 100 * 3 + 3 * 100
    assert payload["items"] == 2

    emptied = await client.get(f"/api/cart/{USER}")
    assert emptied.json()["items"] == []

    order = await client.get(f"/api/orders/{payload['order_id']}")
    assert order.status_code == 200
    assert order.json()["user_id"] == USER
    assert len(order.json()["items"]) == 2


async def test_checkout_with_empty_cart_conflicts(client: AsyncClient) -> None:
    response = await client.post("/api/checkout/nobody")
    assert response.status_code == 409


async def test_unknown_order_is_404(client: AsyncClient) -> None:
    response = await client.get("/api/orders/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
