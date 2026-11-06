from fastapi.testclient import TestClient

from stunsail_api.app import create_app
from stunsail_core.settings import CoreSettings


def test_reset_agent_token_preserves_data_and_revokes_old_credential(db_url):
    admin = {"Authorization": "Bearer admin-token-123456"}
    client = TestClient(create_app(CoreSettings(db_url, "admin-token-123456")))
    registered = client.post(
        "/api/v1/agents", json={"agent_id": "ender", "name": "Ender"}, headers=admin
    )
    assert registered.status_code == 201
    assert registered.headers["cache-control"] == "no-store"
    old_token = registered.json()["token"]
    printer = client.post(
        "/api/v1/printers", json={"agent_id": "ender", "name": "Printer"}, headers=admin
    ).json()
    sync_url = "/api/v1/agents/ender/sync"
    body = {
        "samples": [
            {
                "sequence": 1,
                "observed_at": "2026-11-06T12:00:00Z",
                "quality": "ok",
                "payload": {"status": {"extruder": {"temperature": 200}}},
            }
        ]
    }
    old_auth = {"Authorization": f"Bearer {old_token}"}
    assert client.post(sync_url, json=body, headers=old_auth).status_code == 200
    reset_url = "/api/v1/agents/ender/reset-token"
    assert client.post(reset_url).status_code == 401
    assert client.post(reset_url, headers=old_auth).status_code == 401
    assert client.post("/api/v1/agents/missing/reset-token", headers=admin).status_code == 404
    reset = client.post(reset_url, headers=admin)
    assert reset.status_code == 200
    assert reset.headers["cache-control"] == "no-store"
    assert reset.json()["agent_id"] == "ender"
    new_token = reset.json()["token"]
    assert new_token and new_token != old_token
    assert client.post(sync_url, json=body, headers=old_auth).status_code == 401
    new_auth = {"Authorization": f"Bearer {new_token}"}
    replay = client.post(sync_url, json=body, headers=new_auth)
    assert replay.status_code == 200
    assert replay.json()["duplicate_samples"] == 1
    assert client.get("/api/v1/printers", headers=admin).json()[0]["id"] == printer["id"]
    live = client.get(f"/api/v1/printers/{printer['id']}/live", headers=admin).json()
    assert live["status"]["extruder"]["temperature"] == 200
    second_token = client.post(reset_url, headers=admin).json()["token"]
    assert client.post(sync_url, json={}, headers=new_auth).status_code == 401
    assert (
        client.post(
            sync_url, json={}, headers={"Authorization": f"Bearer {second_token}"}
        ).status_code
        == 200
    )
