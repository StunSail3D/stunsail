import asyncio
import importlib.util
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from stunsail_agent.store import AgentStore, utcnow
from stunsail_agent.sync import Syncer
from stunsail_api.app import create_app
from stunsail_core.settings import CoreSettings

MODULE = Path(__file__).resolve().parents[2] / "deployment" / "installer" / "sqlite_snapshot.py"
spec = importlib.util.spec_from_file_location("sqlite_snapshot", MODULE)
assert spec and spec.loader
snapshot_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot_module)
snapshot = snapshot_module.snapshot


def test_snapshot_includes_uncheckpointed_wal_and_restores_to_new_file(tmp_path):
    database = tmp_path / "live.db"
    backup = tmp_path / "backup.db"
    restored = tmp_path / "restore.db"
    store = AgentStore(database)
    store.agent_id("original-agent")
    store.append_event("original-agent", "job.started", utcnow(), {"job_id": "j"})
    store.append_sample(utcnow(), "j", "ok", {"status": {"extruder": {"temperature": 210}}})
    assert Path(str(database) + "-wal").stat().st_size > 0

    snapshot(database, backup)
    store.append_event("original-agent", "job.completed", utcnow(), {"job_id": "j"})
    snapshot(backup, restored)
    reopened = AgentStore(restored)
    assert reopened.agent_id() == "original-agent"
    assert reopened.pending_counts() == (1, 1)
    assert reopened.list_events("original-agent")[0]["payload"]["job_id"] == "j"
    assert store.pending_counts() == (2, 1)
    reopened.close()
    store.close()
    if os.name == "posix":
        assert backup.stat().st_mode & 0o777 == 0o600


def test_snapshot_refuses_existing_destination_and_invalid_source(tmp_path):
    source = tmp_path / "valid.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE example (value TEXT)")
    existing = tmp_path / "existing.db"
    existing.write_bytes(b"do not replace")
    with pytest.raises(FileExistsError):
        snapshot(source, existing)
    assert existing.read_bytes() == b"do not replace"
    with pytest.raises(FileExistsError):
        snapshot(source, source)
    invalid = tmp_path / "invalid.db"
    invalid.write_bytes(b"not sqlite")
    target = tmp_path / "new.db"
    with pytest.raises(ValueError, match="not a SQLite"):
        snapshot(invalid, target)
    assert not target.exists()


def test_corrupt_database_does_not_leave_snapshot(tmp_path):
    corrupt = tmp_path / "broken.db"
    corrupt.write_bytes(b"SQLite format 3\x00" + bytes(100))
    destination = tmp_path / "copy.db"
    with pytest.raises(sqlite3.DatabaseError):
        snapshot(corrupt, destination)
    assert not destination.exists()


def test_core_database_backup_restores_auth_and_records(db_url, tmp_path):
    source = tmp_path / "core.db"
    backup = tmp_path / "core-backup.db"
    restored = tmp_path / "core-restored.db"
    token = "test-admin-token-123"
    headers = {"Authorization": f"Bearer {token}"}
    client = TestClient(create_app(CoreSettings(db_url, token)))
    response = client.post(
        "/api/v1/agents", headers=headers, json={"agent_id": "printer", "name": "Agent"}
    )
    assert response.status_code == 201
    agent_token = response.json()["token"]
    assert (
        client.post(
            "/api/v1/printers", headers=headers, json={"agent_id": "printer", "name": "Printer"}
        ).status_code
        == 201
    )
    assert (
        client.put(
            "/api/v1/settings/currency", headers=headers, json={"currency": "USD", "symbol": "$"}
        ).status_code
        == 200
    )
    snapshot(source, backup)
    snapshot(backup, restored)
    restored_client = TestClient(
        create_app(CoreSettings(f"sqlite:///{restored.as_posix()}", token))
    )
    assert restored_client.get("/api/v1/health/ready").status_code == 200
    assert restored_client.get("/api/v1/settings/currency", headers=headers).json() == {
        "currency": "USD",
        "symbol": "$",
    }
    assert restored_client.get("/api/v1/printers", headers=headers).json()[0]["name"] == "Printer"
    response = restored_client.post(
        "/api/v1/agents/printer/sync",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"samples": [], "events": []},
    )
    assert response.status_code == 200


def test_restored_agent_buffer_replays_safely_after_core_ack(db_url, tmp_path):
    app = create_app(CoreSettings(db_url, None))
    client = TestClient(app)
    token = client.post("/api/v1/agents", json={"agent_id": "printer", "name": "Agent"}).json()[
        "token"
    ]
    store = AgentStore(tmp_path / "agent.db")
    store.agent_id("printer")
    store.append_event("printer", "job.started", utcnow(), {"job_id": "print-1"})
    store.append_sample(utcnow(), "print-1", "ok", {"status": {}})
    backup = tmp_path / "agent-backup.db"
    snapshot(tmp_path / "agent.db", backup)

    async def sync(buffer):
        async with httpx.AsyncClient(
            base_url="http://core/api/v1",
            headers={"Authorization": f"Bearer {token}"},
            transport=httpx.ASGITransport(app=app),
        ) as transport:
            await Syncer(buffer, "printer", transport).drain()

    asyncio.run(sync(store))
    store.close()
    restored = tmp_path / "restored-agent.db"
    snapshot(backup, restored)
    recovered = AgentStore(restored)
    assert recovered.agent_id() == "printer"
    assert recovered.pending_counts() == (1, 1)
    asyncio.run(sync(recovered))
    assert recovered.pending_counts() == (0, 0)
    assert len(client.get("/api/v1/jobs").json()) == 1
    recovered.close()


def test_snapshot_cli_refuses_to_replace_existing_file(tmp_path):
    source = tmp_path / "source.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE example (value TEXT)")
    output = tmp_path / "output.db"
    command = [sys.executable, str(MODULE), str(source), str(output)]
    success = subprocess.run(command, capture_output=True, text=True, check=False)
    assert success.returncode == 0
    assert "created and verified" in success.stdout
    failure = subprocess.run(command, capture_output=True, text=True, check=False)
    assert failure.returncode == 1
    assert "snapshot failed" in failure.stderr
