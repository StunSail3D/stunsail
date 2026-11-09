import asyncio

import httpx
import pytest
from alembic import command
from conftest import alembic_config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from stunsail_agent.store import AgentStore, utcnow
from stunsail_agent.sync import Syncer
from stunsail_api.app import create_app
from stunsail_core.settings import CoreSettings


def test_revocation_preserves_buffer_and_records_until_token_reset(db_url):
    app = create_app(CoreSettings(db_url, "test-admin-token-123"))
    admin = TestClient(app)
    auth = {"Authorization": "Bearer test-admin-token-123"}
    registered = admin.post(
        "/api/v1/agents", headers=auth, json={"agent_id": "agent-1", "name": "Printer host"}
    )
    assert registered.status_code == 201
    old_token = registered.json()["token"]
    printer = admin.post(
        "/api/v1/printers", headers=auth, json={"agent_id": "agent-1", "name": "Printer"}
    ).json()
    store = AgentStore(":memory:")
    store.append_sample(utcnow(), None, "ok", {"status": {}})
    assert admin.post("/api/v1/agents/agent-1/revoke").status_code == 401
    assert admin.post("/api/v1/agents/absent/revoke", headers=auth).status_code == 404
    response = admin.post("/api/v1/agents/agent-1/revoke", headers=auth)
    assert response.status_code == 200 and response.json()["revoked"] is True
    assert admin.get("/api/v1/agents", headers=auth).json()[0]["revoked"] is True

    async def sync(token):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://core/api/v1",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            await Syncer(store, "agent-1", client).drain()

    with pytest.raises(httpx.HTTPStatusError) as error:
        asyncio.run(sync(old_token))
    assert error.value.response.status_code == 401
    assert store.pending_counts() == (0, 1)
    assert admin.get("/api/v1/printers", headers=auth).json()[0]["id"] == printer["id"]
    reset = admin.post("/api/v1/agents/agent-1/reset-token", headers=auth)
    assert reset.status_code == 200
    assert admin.get("/api/v1/agents", headers=auth).json()[0]["revoked"] is False
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(sync(old_token))
    asyncio.run(sync(reset.json()["token"]))
    assert store.pending_counts() == (0, 0)


def test_agent_revocation_migration_preserves_existing_credentials(db_url):
    config = alembic_config(db_url)
    command.downgrade(config, "0003_currency_settings")
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agents (id, name, token_hash, created_at) "
                "VALUES (:id, :name, :token_hash, :created_at)"
            ),
            {
                "id": "existing",
                "name": "Existing",
                "token_hash": "a" * 64,
                "created_at": "2026-01-01 00:00:00",
            },
        )
    command.upgrade(config, "head")
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT token_hash, revoked FROM agents WHERE id = 'existing'")
        ).one()
        assert row.token_hash == "a" * 64
        assert not row.revoked
    engine.dispose()
