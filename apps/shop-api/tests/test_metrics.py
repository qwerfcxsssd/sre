import re

from httpx import AsyncClient


def sample_value(body: str, pattern: str) -> float:
    match = re.search(pattern, body, flags=re.MULTILINE)
    assert match is not None, f"no sample matching {pattern!r}"
    return float(match.group(1))


async def test_http_metrics_use_route_templates(client: AsyncClient) -> None:
    await client.get("/api/cart/metrics-user")

    body = (await client.get("/metrics")).text
    assert 'route="/api/cart/{user_id}"' in body
    assert "metrics-user" not in body
    bucket = 'http_request_duration_seconds_bucket'
    assert f'{bucket}{{le="0.005",method="GET",route="/api/cart/{{user_id}}"}}' in body
    assert "http_requests_in_flight" in body


async def test_counters_advance_with_traffic(client: AsyncClient) -> None:
    pattern = r'^http_requests_total\{method="GET",route="/api/products",status="200"\} (\S+)$'

    await client.get("/api/products")
    before = sample_value((await client.get("/metrics")).text, pattern)

    await client.get("/api/products")
    after = sample_value((await client.get("/metrics")).text, pattern)

    assert after == before + 1


async def test_business_metrics_are_exported(client: AsyncClient) -> None:
    await client.post("/api/cart/buyer/items", json={"product_id": 1, "quantity": 2})
    await client.post("/api/checkout/buyer")

    body = (await client.get("/metrics")).text
    assert 'app_orders_created_total{result="success"}' in body
    assert "app_order_amount_rubles_bucket" in body
    assert 'app_cache_operations_total{operation="get",result="miss"}' in body
    assert "app_build_info" in body
