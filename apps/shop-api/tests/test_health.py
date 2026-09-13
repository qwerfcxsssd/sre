from httpx import AsyncClient


async def test_healthz(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_ok(client: AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["checks"] == {"postgres": True, "redis": True}


async def test_readyz_reports_dropped_dependency(client: AsyncClient) -> None:
    await client.post("/admin/chaos", json={"drop_postgres": True})
    response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"]["postgres"] is False
