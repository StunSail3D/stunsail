import httpx
import pytest

from stunsail_api.main import app


@pytest.mark.anyio
async def test_versioned_health_endpoint() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "api_version": "v1"}
