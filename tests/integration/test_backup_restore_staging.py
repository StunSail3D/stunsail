import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from stunsail_agent.store import AgentStore, utcnow
from stunsail_agent.sync import Syncer
from stunsail_api.app import create_app
from stunsail_core.settings import CoreSettings

INSTALLER = Path(__file__).resolve().parents[2] / "deployment" / "installer"
if os.name == "posix":
    sys.path.insert(0, str(INSTALLER))
    try:
        import backup_installation
        import configure
        import stage_restore
    finally:
        sys.path.remove(str(INSTALLER))


@pytest.mark.skipif(os.name != "posix", reason="backup staging requires POSIX file permissions")
def test_staged_core_auth_and_agent_buffer_replay(db_url, tmp_path, monkeypatch):
    etc, data, opt = (tmp_path / name for name in ("etc", "data", "opt"))
    agent_dir = etc / "agent" / "printer-1"
    agent_dir.mkdir(parents=True)
    agent_data = data / "agent" / "printer-1"
    agent_data.mkdir(parents=True)
    release = opt / "releases" / "initial"
    release.mkdir(parents=True)
    (release / "pyproject.toml").write_text('[project]\nversion="0.1.0"\n')
    (release / "uv.lock").write_text("locked")
    (opt / "current").symlink_to(release)
    admin = "test_admin_token_123456"
    (etc / "core.env").write_text(
        "STUNSAIL_DATABASE_URL=sqlite:////var/lib/stunsail/core/stunsail.db\n"
        f"STUNSAIL_ADMIN_TOKEN={admin}\n"
    )
    (data / "core").mkdir()
    original_db = tmp_path / "core.db"
    original_db.rename(data / "core" / "stunsail.db")
    db_url = f"sqlite:///{(data / 'core' / 'stunsail.db').as_posix()}"
    app = create_app(CoreSettings(db_url, admin))
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {admin}"}
    response = client.post(
        "/api/v1/agents", headers=headers, json={"agent_id": "printer-1", "name": "Printer"}
    )
    assert response.status_code == 201
    token = response.json()["token"]
    config, _, _ = configure.build_configuration(
        "standalone", "printer-1", "http://printer", "http://127.0.0.1:8000", token
    )
    (agent_dir / "agent.yaml").write_text(json.dumps(config))
    (agent_dir / "agent.env").write_text(f"STUNSAIL_AGENT_TOKEN={token}\n")
    store = AgentStore(agent_data / "buffer.db")
    store.agent_id("printer-1")
    store.append_event("printer-1", "job.started", utcnow(), {"job_id": "job-1"})
    store.close()
    monkeypatch.setattr(backup_installation, "ETC", etc)
    monkeypatch.setattr(backup_installation, "DATA", data)
    monkeypatch.setattr(backup_installation, "OPT", opt)
    monkeypatch.setattr(backup_installation.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        backup_installation.guided_install, "validate_bundle_destination", lambda path: None
    )
    monkeypatch.setattr(backup_installation, "_stopped", lambda unit: None)
    monkeypatch.setattr(backup_installation, "_agent_unit", lambda agent: agent)
    monkeypatch.setattr(backup_installation, "_no_active_agents", lambda: None)
    backup = tmp_path / "backup"
    staged = tmp_path / "staged"
    backup_installation.backup(backup)
    stage_restore.stage(backup, staged)

    staged_url = f"sqlite:///{(staged / 'data/core/stunsail.db').as_posix()}"
    restored_app = create_app(CoreSettings(staged_url, admin))
    restored_client = TestClient(restored_app)
    assert restored_client.get("/api/v1/health/ready").status_code == 200
    assert restored_client.get("/api/v1/agents", headers=headers).json()[0]["id"] == "printer-1"
    restored_store = AgentStore(staged / "data/agent/printer-1/buffer.db")
    assert restored_store.agent_id() == "printer-1"
    assert restored_store.pending_counts() == (1, 0)

    async def sync():
        async with httpx.AsyncClient(
            base_url="http://core/api/v1",
            headers={"Authorization": f"Bearer {token}"},
            transport=httpx.ASGITransport(app=restored_app),
        ) as transport:
            await Syncer(restored_store, "printer-1", transport).drain()

    asyncio.run(sync())
    assert restored_store.pending_counts() == (0, 0)
    assert len(restored_client.get("/api/v1/jobs", headers=headers).json()) == 1
    restored_store.close()
