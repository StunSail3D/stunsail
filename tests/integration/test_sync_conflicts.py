from copy import deepcopy

from fastapi.testclient import TestClient

from stunsail_api.app import create_app
from stunsail_core.settings import CoreSettings


def test_conflicting_replay_is_rejected_without_partial_ingest(db_url):
    client = TestClient(create_app(CoreSettings(db_url, None)))
    token = client.post("/api/v1/agents", json={"agent_id": "a", "name": "A"}).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    sample = {
        "sequence": 1,
        "observed_at": "2026-01-01T00:00:00Z",
        "job_id": None,
        "quality": "ok",
        "payload": {"status": {"extruder": {"temperature": 200}}},
    }
    event = {
        "contract_version": 1,
        "event_id": "e1",
        "agent_id": "a",
        "sequence": 1,
        "event_type": "job.started",
        "observed_at": "2026-01-01T00:00:00Z",
        "payload": {"job_id": "original", "state": "printing"},
    }
    path = "/api/v1/agents/a/sync"
    original = {"samples": [sample], "events": [event]}
    assert client.post(path, headers=auth, json=original).status_code == 200
    replay = client.post(path, headers=auth, json=original).json()
    assert replay["duplicate_samples"] == replay["duplicate_events"] == 1

    changed = deepcopy(original)
    changed["samples"][0]["payload"]["status"]["extruder"]["temperature"] = 220
    response = client.post(path, headers=auth, json=changed)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "sample_conflict"

    changed = deepcopy(original)
    changed["events"][0]["payload"]["job_id"] = "wrong"
    changed["samples"].append({**sample, "sequence": 2})
    response = client.post(path, headers=auth, json=changed)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "event_conflict"
    later = client.post(path, headers=auth, json={"samples": [changed["samples"][1]], "events": []})
    assert later.status_code == 200
    assert later.json()["duplicate_samples"] == 0
    assert len(client.get("/api/v1/jobs").json()) == 1
