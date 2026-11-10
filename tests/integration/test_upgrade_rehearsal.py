import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from stunsail_agent.store import AgentStore, utcnow

ROOT = Path(__file__).resolve().parents[2]
if os.name == "posix":
    import pwd

    sys.path.insert(0, str(ROOT / "deployment" / "installer"))
    try:
        import rehearse_upgrade
        import verify_backup
    finally:
        sys.path.remove(str(ROOT / "deployment" / "installer"))


@pytest.mark.skipif(
    os.name != "posix" or os.getuid() != 0 or shutil.which("runuser") is None,
    reason="requires root and runuser for an isolated non-root migration",
)
def test_real_migration_runs_as_unprivileged_user_on_copy(monkeypatch):
    user = pwd.getpwnam("nobody")
    original_getpwnam = pwd.getpwnam
    monkeypatch.setattr(
        rehearse_upgrade.pwd,
        "getpwnam",
        lambda name: user if name == "stunsail-core" else original_getpwnam(name),
    )
    run = rehearse_upgrade.subprocess.run

    def run_as_nobody(command_line, **kwargs):
        assert command_line[:3] == ["runuser", "-u", "stunsail-core"]
        command_line[2] = "nobody"
        return run(command_line, **kwargs)

    monkeypatch.setattr(rehearse_upgrade.subprocess, "run", run_as_nobody)
    with tempfile.TemporaryDirectory(prefix="stunsail-migration-test-") as directory:
        root = Path(directory)
        root.chmod(0o755)
        backup = root / "backup"
        (backup / "data" / "core").mkdir(parents=True)
        db = backup / "data" / "core" / "stunsail.db"
        monkeypatch.setenv("STUNSAIL_DATABASE_URL", f"sqlite:///{db}")
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "database" / "migrations"))
        command.upgrade(config, "0003_currency_settings")
        db.chmod(0o600)
        candidate = root / "candidate"
        candidate.mkdir()
        shutil.copyfile(ROOT / "alembic.ini", candidate / "alembic.ini")
        shutil.copytree(ROOT / "database" / "migrations", candidate / "database" / "migrations")
        (candidate / ".venv").symlink_to(Path(sys.prefix), target_is_directory=True)
        rehearsal = root / "rehearsal"
        rehearse_upgrade._migration(candidate, backup, verify_backup.digest(db), rehearsal)
        rehearse_upgrade._smoke(candidate, rehearsal)
        with sqlite3.connect(db) as original:
            assert original.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "0003_currency_settings",
            )
        with sqlite3.connect(rehearsal / "stunsail.db") as migrated:
            assert migrated.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "0004_agent_revocation",
            )
        assert (rehearsal / "stunsail.db").stat().st_uid == user.pw_uid
        assert (rehearsal / "smoke.db").stat().st_uid == user.pw_uid


@pytest.mark.skipif(
    os.name != "posix" or os.getuid() != 0 or shutil.which("runuser") is None,
    reason="requires root and runuser for an isolated non-root Agent test",
)
def test_real_agent_rehearsal_runs_as_unprivileged_user_on_copy(monkeypatch):
    user = pwd.getpwnam("nobody")
    original_getpwnam = pwd.getpwnam
    monkeypatch.setattr(
        rehearse_upgrade.pwd,
        "getpwnam",
        lambda name: user if name == "stunsail-agent" else original_getpwnam(name),
    )
    run = rehearse_upgrade.subprocess.run

    def run_as_nobody(command_line, **kwargs):
        assert command_line[:3] == ["runuser", "-u", "stunsail-agent"]
        command_line[2] = "nobody"
        return run(command_line, **kwargs)

    monkeypatch.setattr(rehearse_upgrade.subprocess, "run", run_as_nobody)
    with tempfile.TemporaryDirectory(prefix="stunsail-agent-rehearsal-") as directory:
        root = Path(directory)
        root.chmod(0o755)
        backup = root / "backup"
        config = backup / "config" / "agent" / "printer-1" / "agent.yaml"
        buffer = backup / "data" / "agent" / "printer-1" / "buffer.db"
        config.parent.mkdir(parents=True)
        buffer.parent.mkdir(parents=True)
        config.write_text(
            '{"deployment_mode":"agent_only","agent":{"agent_id":"printer-1",'
            '"local_buffer_url":"sqlite:////var/lib/stunsail/agent/printer-1/buffer.db",'
            '"core_url":"https://core.local",'
            '"moonraker":{"instances":[{"url":"http://printer"}]}}}'
        )
        store = AgentStore(buffer)
        store.agent_id("printer-1")
        store.append_event("printer-1", "job.started", utcnow(), {"job_id": "job-1"})
        store.close()
        before = verify_backup.digest(buffer)
        manifest = {
            "agents": ["printer-1"],
            "files": {
                "config/agent/printer-1/agent.yaml": verify_backup.digest(config),
                "data/agent/printer-1/buffer.db": before,
            },
        }
        candidate = root / "candidate"
        candidate.mkdir()
        (candidate / ".venv").symlink_to(Path(sys.prefix), target_is_directory=True)
        destination = root / "rehearsal"
        rehearse_upgrade._agents(candidate, backup, manifest, destination)
        assert verify_backup.digest(buffer) == before
        copied = destination / "printer-1" / "buffer.db"
        assert copied.stat().st_uid == user.pw_uid
        store = AgentStore(copied)
        try:
            assert store.pending_counts() == (1, 0)
        finally:
            store.close()
