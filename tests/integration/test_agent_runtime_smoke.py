import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from stunsail_agent.store import MIGRATIONS, AgentStore, utcnow

SCRIPT = Path(__file__).resolve().parents[2] / "deployment" / "installer" / "agent_runtime_smoke.py"
spec = importlib.util.spec_from_file_location("agent_runtime_smoke", SCRIPT)
assert spec and spec.loader
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


@pytest.fixture
def agent_data(tmp_path):
    config = tmp_path / "agent.yaml"
    config.write_text(
        json.dumps(
            {
                "deployment_mode": "agent_only",
                "agent": {
                    "agent_id": "printer-1",
                    "local_buffer_url": "sqlite:////var/lib/stunsail/agent/printer-1/buffer.db",
                    "core_url": "https://core.local",
                    "moonraker": {"instances": [{"name": "printer-1", "url": "http://printer"}]},
                },
            }
        )
    )
    buffer = tmp_path / "buffer.db"
    store = AgentStore(buffer)
    store.agent_id("printer-1")
    store.append_event("printer-1", "job.started", utcnow(), {"job_id": "job-1"})
    store.close()
    return config, buffer


def test_candidate_opens_buffer_and_retains_pending_events(agent_data):
    config, buffer = agent_data
    smoke.check(config, buffer, "printer-1")
    store = AgentStore(buffer)
    try:
        assert store.agent_id() == "printer-1"
        assert store.pending_counts() == (1, 0)
    finally:
        store.close()


def test_rejects_mismatched_buffer_identity(agent_data):
    config, buffer = agent_data
    with sqlite3.connect(buffer) as db:
        db.execute("UPDATE kv SET value='other' WHERE key='agent_id'")
    with pytest.raises(ValueError, match="buffer belongs"):
        smoke.check(config, buffer, "printer-1")


def test_rejects_future_buffer_schema(agent_data):
    config, buffer = agent_data
    with sqlite3.connect(buffer) as db:
        db.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")
    with pytest.raises(ValueError, match="newer"):
        smoke.check(config, buffer, "printer-1")


def test_rejects_configuration_buffer_path(agent_data):
    config, buffer = agent_data
    values = json.loads(config.read_text())
    values["agent"]["local_buffer_url"] = "sqlite:////elsewhere/buffer.db"
    config.write_text(json.dumps(values))
    with pytest.raises(ValueError, match="buffer path"):
        smoke.check(config, buffer, "printer-1")


def test_candidate_upgrades_older_buffer_copy(agent_data):
    config, buffer = agent_data
    buffer.unlink()
    with sqlite3.connect(buffer) as db:
        db.executescript(MIGRATIONS[0])
        db.execute("PRAGMA user_version = 1")
        db.execute("INSERT INTO kv VALUES ('agent_id', 'printer-1')")
    smoke.check(config, buffer, "printer-1")
    with sqlite3.connect(buffer) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
