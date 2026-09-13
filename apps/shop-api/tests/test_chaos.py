import time

from httpx import AsyncClient

DEFAULTS = {
    "latency_ms": 0,
    "latency_jitter_ms": 0,
    "error_rate": 0.0,
    "cpu_burn": False,
    "mem_leak_mb_per_min": 0,
    "drop_postgres": False,
    "drop_redis": False,
    "fail_readiness": False,
    "high_cardinality": False,
}


async def test_default_state(client: AsyncClient) -> None:
    state = (await client.get("/admin/chaos")).json()
    assert {key: state[key] for key in DEFAULTS} == DEFAULTS


async def test_latency_is_injected_into_api_routes(client: AsyncClient) -> None:
    await client.post("/admin/chaos", json={"latency_ms": 250})

    started = time.perf_counter()
    await client.get("/api/products")
    slowed = time.perf_counter() - started

    started = time.perf_counter()
    await client.get("/healthz")
    untouched = time.perf_counter() - started

    assert slowed >= 0.25
    assert untouched < 0.25


async def test_error_rate_turns_api_into_failures(client: AsyncClient) -> None:
    await client.post("/admin/chaos", json={"error_rate": 1.0})

    response = await client.get("/api/products")
    assert response.status_code == 500
    assert response.json()["source"] == "chaos"

    assert (await client.get("/healthz")).status_code == 200


async def test_drop_redis_breaks_cart(client: AsyncClient) -> None:
    await client.post("/admin/chaos", json={"drop_redis": True})

    response = await client.get("/api/cart/someone")
    assert response.status_code == 503
    assert response.json()["dependency"] == "redis"


async def test_drop_postgres_breaks_products(client: AsyncClient) -> None:
    await client.post("/admin/chaos", json={"drop_postgres": True})

    response = await client.get("/api/products")
    assert response.status_code == 503
    assert response.json()["dependency"] == "postgres"


async def test_fail_readiness_keeps_liveness_green(client: AsyncClient) -> None:
    await client.post("/admin/chaos", json={"fail_readiness": True})

    assert (await client.get("/readyz")).status_code == 503
    assert (await client.get("/healthz")).status_code == 200


async def test_high_cardinality_adds_user_id_label(client: AsyncClient) -> None:
    await client.get("/api/cart/before-chaos")
    body = (await client.get("/metrics")).text
    assert "user_id=" not in body

    await client.post("/admin/chaos", json={"high_cardinality": True})
    await client.get("/api/cart/after-chaos")

    body = (await client.get("/metrics")).text
    assert 'user_id="after-chaos"' in body


async def test_reset_restores_defaults(client: AsyncClient) -> None:
    await client.post("/admin/chaos", json={"latency_ms": 500, "error_rate": 0.5})
    state = (await client.delete("/admin/chaos")).json()

    assert {key: state[key] for key in DEFAULTS} == DEFAULTS
    assert (await client.get("/api/products")).status_code == 200
