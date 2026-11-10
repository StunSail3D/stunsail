import json
import os
import shutil
import sqlite3
import subprocess
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
        import apply_restore
        import apply_upgrade
        import backup_installation
        import configure
        import install_fresh
        import maintenance_backup
        import rehearse_upgrade
        import remove_services
        import rollback_upgrade
        import verify_backup
    finally:
        sys.path.remove(str(ROOT / "deployment" / "installer"))


@pytest.mark.skipif(
    os.name != "posix" or os.getuid() != 0 or shutil.which("runuser") is None,
    reason="requires root and runuser for an isolated non-root upgrade",
)
@pytest.mark.parametrize("old_revision", ["0003_currency_settings", "0004_agent_revocation"])
def test_offline_upgrade_with_real_backup_migration_and_agent_rehearsal(monkeypatch, old_revision):
    user = pwd.getpwnam("nobody")
    original_user = pwd.getpwnam
    monkeypatch.setattr(
        apply_upgrade.pwd,
        "getpwnam",
        lambda name: user if name in {"stunsail-core", "stunsail-agent"} else original_user(name),
    )
    run = rehearse_upgrade.subprocess.run

    def run_as_nobody(command_line, **kwargs):
        assert command_line[:2] == ["runuser", "-u"]
        assert command_line[2] in {"stunsail-core", "stunsail-agent"}
        return run([*command_line[:2], "nobody", *command_line[3:]], **kwargs)

    monkeypatch.setattr(rehearse_upgrade.subprocess, "run", run_as_nobody)
    with tempfile.TemporaryDirectory(prefix="stunsail-upgrade-e2e-") as directory:
        root = Path(directory)
        root.chmod(0o755)
        opt, etc, data, units = (root / name for name in ("opt", "etc", "data", "units"))
        old, candidate = opt / "releases" / "old", opt / "releases" / "candidate"
        old.mkdir(parents=True)
        candidate.mkdir()
        (opt / "current").symlink_to(old)
        for release in (old, candidate):
            (release / "pyproject.toml").write_text('[project]\nversion="0.1.0"\n')
            (release / "uv.lock").write_text("locked")
        shutil.copytree(Path(sys.prefix), candidate / ".venv", symlinks=True)
        shutil.copytree(Path(sys.prefix), old / ".venv", symlinks=True)
        shutil.copyfile(ROOT / "alembic.ini", candidate / "alembic.ini")
        shutil.copytree(ROOT / "database" / "migrations", candidate / "database" / "migrations")
        units.mkdir()
        for name in (install_fresh.AGENT_UNIT, install_fresh.CORE_UNIT):
            (units / name).write_text(name)
            path = candidate / "deployment" / "systemd" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
            old_path = old / "deployment" / "systemd" / name
            old_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.write_text(name)
        agent_config = etc / "agent" / "printer-1"
        agent_data = data / "agent" / "printer-1"
        agent_config.mkdir(parents=True)
        agent_data.mkdir(parents=True)
        config, token, _ = configure.build_configuration(
            "agent_only",
            "printer-1",
            "http://printer",
            "https://core.local",
            "test_token_123456789",
        )
        (agent_config / "agent.yaml").write_text(json.dumps(config))
        (agent_config / "agent.env").write_text(f"STUNSAIL_AGENT_TOKEN={token}\n")
        (etc / "core.env").write_text(
            "STUNSAIL_DATABASE_URL=sqlite:////var/lib/stunsail/core/stunsail.db\n"
        )
        (data / "core").mkdir()
        database = data / "core" / "stunsail.db"
        monkeypatch.setenv("STUNSAIL_DATABASE_URL", f"sqlite:///{database}")
        alembic = Config(str(ROOT / "alembic.ini"))
        alembic.set_main_option("script_location", str(ROOT / "database" / "migrations"))
        command.upgrade(alembic, old_revision)
        store = AgentStore(agent_data / "buffer.db")
        store.agent_id("printer-1")
        store.append_event("printer-1", "job.started", utcnow(), {"job_id": "job-1"})
        store.close()
        for name, value in (("ETC", etc), ("DATA", data), ("OPT", opt)):
            monkeypatch.setattr(backup_installation, name, value)
        monkeypatch.setattr(
            backup_installation.guided_install, "validate_bundle_destination", lambda path: None
        )
        monkeypatch.setattr(maintenance_backup, "_trusted_directory", lambda path: None)
        monkeypatch.setattr(maintenance_backup, "_validate_template", lambda name: units / name)
        monkeypatch.setattr(maintenance_backup, "_managed_unit", lambda unit, path: None)
        monkeypatch.setattr(maintenance_backup, "_loaded_agents", lambda: set())
        monkeypatch.setattr(backup_installation, "_agent_unit", lambda agent: agent)
        monkeypatch.setattr(backup_installation, "_no_active_agents", lambda: None)
        monkeypatch.setattr(backup_installation, "_stopped", lambda unit: None)
        monkeypatch.setattr(maintenance_backup, "create", backup_installation.backup)
        monkeypatch.setattr(remove_services, "_reject_remaining_links", lambda core: None)
        backup = root / "backup"
        apply_upgrade.apply(candidate, backup)
        assert (opt / "current").resolve() == candidate
        assert verify_backup.verify(backup)["agents"] == ["printer-1"]
        with sqlite3.connect(data / "core" / "stunsail.db") as db:
            assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == (
                "0004_agent_revocation"
            )
        with sqlite3.connect(root / "data.upgrade-core-previous" / "stunsail.db") as db:
            assert (
                db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == old_revision
            )
        backup_after = root / "backup-after"
        backup_installation.backup(backup_after)
        assert verify_backup.verify(backup_after)["release_path"] == str(candidate)
        assert (data / "core" / "stunsail.db").stat().st_uid == user.pw_uid
        store = AgentStore(agent_data / "buffer.db")
        try:
            assert store.pending_counts() == (1, 0)
        finally:
            store.close()
        monkeypatch.setattr(apply_restore, "_trusted_backup", lambda path: None)
        safety = root / "rollback-safety"
        if old_revision == "0003_currency_settings":
            with pytest.raises(subprocess.CalledProcessError):
                rollback_upgrade.rollback(backup, safety)
            assert (opt / "current").resolve() == candidate
            assert verify_backup.verify(safety)["release_path"] == str(candidate)
        else:
            rollback_upgrade.rollback(backup, safety)
            assert (opt / "current").resolve() == old
            assert verify_backup.verify(safety)["release_path"] == str(candidate)
            with sqlite3.connect(data / "core" / "stunsail.db") as db:
                assert (
                    db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                    == old_revision
                )
            assert (root / "data.rollback-core-previous" / "stunsail.db").is_file()
