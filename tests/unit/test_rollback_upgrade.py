import json
import os
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

INSTALLER = Path(__file__).resolve().parents[2] / "deployment" / "installer"
if os.name == "posix":
    sys.path.insert(0, str(INSTALLER))
    try:
        import apply_restore
        import apply_upgrade
        import backup_installation
        import configure
        import install_fresh
        import maintenance_backup
        import rehearse_upgrade
        import rollback_upgrade
        import verify_backup
        import verify_release
    finally:
        sys.path.remove(str(INSTALLER))

pytestmark = pytest.mark.skipif(os.name != "posix", reason="requires POSIX installation tools")


@pytest.fixture(params=[True, False], ids=["standalone", "agent-only"])
def host(tmp_path, monkeypatch, request):
    root = tmp_path / "host"
    opt, data, etc = root / "opt", root / "data", root / "etc"
    old, new = opt / "releases" / "old", opt / "releases" / "new"
    old.mkdir(parents=True)
    new.mkdir()
    (opt / "current").symlink_to(new)
    data.mkdir()
    etc.mkdir()
    units = root / "units"
    units.mkdir()
    for name in (install_fresh.AGENT_UNIT, install_fresh.CORE_UNIT):
        (units / name).write_text(name)
        path = old / "deployment" / "systemd" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    binary = old / ".venv" / "bin"
    binary.mkdir(parents=True)
    for name in ("python", "uvicorn", "stunsail-agent", "alembic"):
        path = binary / name
        path.write_text("test")
        path.chmod(0o755)
    source = tmp_path / "backup"
    source.mkdir()
    files = {"config/agent/printer-1/agent.env": "test"}
    if request.param:
        (data / "core").mkdir()
        (source / "data" / "core").mkdir(parents=True)
        for path, value in (
            (data / "core" / "stunsail.db", "newer"),
            (source / "data" / "core" / "stunsail.db", "original"),
        ):
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE example(value TEXT)")
                db.execute("INSERT INTO example VALUES (?)", (value,))
        files["data/core/stunsail.db"] = verify_backup.digest(source / "data/core/stunsail.db")
    original = {
        "agents": ["printer-1"],
        "core": request.param,
        "release_path": str(old),
        "files": files,
    }
    current = {
        "agents": ["printer-1"],
        "core": request.param,
        "release_path": str(new),
        "files": dict(files),
    }
    for name, value in (("ETC", etc), ("DATA", data), ("OPT", opt)):
        monkeypatch.setattr(backup_installation, name, value)
    monkeypatch.setattr(rollback_upgrade.os, "geteuid", lambda: 0)
    monkeypatch.setattr(rollback_upgrade.os, "chown", lambda *args: None)
    monkeypatch.setattr(
        rollback_upgrade.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=42, pw_gid=43)
    )
    monkeypatch.setattr(apply_restore, "_trusted_backup", lambda path: None)
    monkeypatch.setattr(maintenance_backup, "_trusted_directory", lambda path: None)
    monkeypatch.setattr(maintenance_backup, "_validate_template", lambda name: units / name)
    monkeypatch.setattr(
        verify_backup, "verify", lambda path: original if path == source else current
    )
    monkeypatch.setattr(verify_release, "verify", lambda path, release: None)
    events = []
    monkeypatch.setattr(maintenance_backup, "create", lambda path: events.append(("backup", path)))
    monkeypatch.setattr(rehearse_upgrade, "_smoke", lambda *args: events.append(("smoke",)))
    monkeypatch.setattr(rehearse_upgrade, "_agents", lambda *args: events.append(("agents",)))
    monkeypatch.setattr(
        apply_upgrade, "_check_services", lambda manifest: events.append(("check",))
    )
    return root, old, new, source, tmp_path / "safety", events, original, current


def value(path):
    with sqlite3.connect(path) as db:
        return db.execute("SELECT value FROM example").fetchone()[0]


def test_rollback_preserves_new_data_and_leaves_existing_upgrade_recovery(host):
    root, old, new, source, safety, events, original, _ = host
    (root / "data.upgrade-core-previous").mkdir()
    rollback_upgrade.rollback(source, safety)
    assert (root / "opt" / "current").resolve() == old
    assert new.is_dir()
    assert (root / "data.upgrade-core-previous").is_dir()
    assert events[0] == ("backup", safety)
    assert events[-2:] == [("agents",), ("check",)]
    if original["core"]:
        assert value(root / "data" / "core" / "stunsail.db") == "original"
        assert value(root / "data.rollback-core-previous" / "stunsail.db") == "newer"
        assert ("smoke",) in events


def test_rejects_configuration_changes_after_safety_backup(host):
    root, _, new, source, safety, events, _, current = host
    current["files"]["config/agent/printer-1/agent.env"] = "different"
    with pytest.raises(ValueError, match="configuration changed"):
        rollback_upgrade.rollback(source, safety)
    assert events == [("backup", safety)]
    assert (root / "opt" / "current").resolve() == new


def test_rejects_changed_topology_and_unavailable_old_unit(host):
    root, old, new, source, safety, events, _, current = host
    current["agents"] = ["other"]
    with pytest.raises(ValueError, match="topology"):
        rollback_upgrade.rollback(source, safety)
    assert (root / "opt" / "current").resolve() == new
    current["agents"] = ["printer-1"]
    (old / "deployment" / "systemd" / install_fresh.AGENT_UNIT).write_text("different")
    with pytest.raises(ValueError, match="service unit differs"):
        rollback_upgrade.rollback(source, safety)
    assert len(events) == 1


def test_smoke_or_service_failure_leaves_current_untouched(host, monkeypatch):
    root, _, new, source, safety, _, _, _ = host

    def fail(*args):
        raise RuntimeError("agent rehearsal failed")

    monkeypatch.setattr(rehearse_upgrade, "_agents", fail)
    with pytest.raises(RuntimeError, match="agent rehearsal failed"):
        rollback_upgrade.rollback(source, safety)
    assert (root / "opt" / "current").resolve() == new
    assert not (root / "data.rollback-core-previous").exists()


def test_interrupted_swap_preserves_both_databases(host, monkeypatch):
    root, _, new, source, safety, _, original, _ = host
    if not original["core"]:
        pytest.skip("Agent-only hosts have no Core swap")
    rename = os.rename

    def fail(src, dst):
        if src == root / "data.rollback-core-new":
            raise OSError("test interruption")
        rename(src, dst)

    monkeypatch.setattr(rollback_upgrade.os, "rename", fail)
    with pytest.raises(RuntimeError, match="original Core directory restored"):
        rollback_upgrade.rollback(source, safety)
    assert (root / "opt" / "current").resolve() == new
    assert value(root / "data" / "core" / "stunsail.db") == "newer"
    assert value(root / "data.rollback-core-new" / "stunsail.db") == "original"


def test_link_switch_failure_preserves_rollback_recovery(host, monkeypatch):
    root, old, new, source, safety, _, original, _ = host

    def fail(*args):
        raise OSError("link switch failed")

    monkeypatch.setattr(rollback_upgrade.os, "replace", fail)
    expected_error = RuntimeError if original["core"] else OSError
    with pytest.raises(expected_error, match="link switch failed"):
        rollback_upgrade.rollback(source, safety)
    assert (root / "opt" / "current").resolve() == new
    assert (root / "opt" / "current.rollback-new").resolve() == old
    if original["core"]:
        assert value(root / "data" / "core" / "stunsail.db") == "newer"
        assert value(root / "data.rollback-core-new" / "stunsail.db") == "original"


def test_existing_recovery_paths_refuse_before_safety_backup(host):
    root, _, new, source, safety, events, _, _ = host
    (root / "data.rollback-core-previous").mkdir()
    with pytest.raises(FileExistsError):
        rollback_upgrade.rollback(source, safety)
    assert events == []
    assert (root / "opt" / "current").resolve() == new


def test_real_backup_and_database_restore_with_mocked_services(tmp_path, monkeypatch):
    root = tmp_path / "host"
    opt, data, etc = root / "opt", root / "data", root / "etc"
    old, new = opt / "releases" / "old", opt / "releases" / "new"
    old.mkdir(parents=True)
    new.mkdir()
    (opt / "current").symlink_to(old)
    for release in (old, new):
        (release / "pyproject.toml").write_text('[project]\nversion="0.1.0"\n')
        (release / "uv.lock").write_text("locked")
    binary = old / ".venv" / "bin"
    binary.mkdir(parents=True)
    for name in ("python", "uvicorn", "stunsail-agent", "alembic"):
        path = binary / name
        path.write_text("test")
        path.chmod(0o755)
    units = root / "units"
    units.mkdir()
    for name in (install_fresh.AGENT_UNIT, install_fresh.CORE_UNIT):
        (units / name).write_text(name)
        path = old / "deployment" / "systemd" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    config = etc / "agent" / "printer-1"
    agent_data = data / "agent" / "printer-1"
    config.mkdir(parents=True)
    agent_data.mkdir(parents=True)
    values, token, _ = configure.build_configuration(
        "agent_only", "printer-1", "http://printer", "https://core.local", "test_token_123456789"
    )
    (config / "agent.yaml").write_text(json.dumps(values))
    (config / "agent.env").write_text(f"STUNSAIL_AGENT_TOKEN={token}\n")
    (etc / "core.env").write_text(
        "STUNSAIL_DATABASE_URL=sqlite:////var/lib/stunsail/core/stunsail.db\n"
    )
    (data / "core").mkdir()
    for path in (data / "core" / "stunsail.db", agent_data / "buffer.db"):
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE example(value TEXT)")
            db.execute("INSERT INTO example VALUES ('original')")
    for name, item in (("ETC", etc), ("DATA", data), ("OPT", opt)):
        monkeypatch.setattr(backup_installation, name, item)
    monkeypatch.setattr(rollback_upgrade.os, "geteuid", lambda: 0)
    monkeypatch.setattr(rollback_upgrade.os, "chown", lambda *args: None)
    monkeypatch.setattr(
        rollback_upgrade.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=42, pw_gid=43)
    )
    monkeypatch.setattr(apply_restore, "_trusted_backup", lambda path: None)
    monkeypatch.setattr(maintenance_backup, "_trusted_directory", lambda path: None)
    monkeypatch.setattr(maintenance_backup, "_validate_template", lambda name: units / name)
    monkeypatch.setattr(
        backup_installation.guided_install, "validate_bundle_destination", lambda path: None
    )
    monkeypatch.setattr(backup_installation, "_stopped", lambda unit: None)
    monkeypatch.setattr(backup_installation, "_agent_unit", lambda agent: agent)
    monkeypatch.setattr(backup_installation, "_no_active_agents", lambda: None)
    monkeypatch.setattr(maintenance_backup, "create", backup_installation.backup)
    monkeypatch.setattr(rehearse_upgrade, "_smoke", lambda *args: None)
    monkeypatch.setattr(rehearse_upgrade, "_agents", lambda *args: None)
    monkeypatch.setattr(apply_upgrade, "_check_services", lambda manifest: None)
    source, safety = tmp_path / "before", tmp_path / "safety"
    backup_installation.backup(source)
    (opt / "current").unlink()
    (opt / "current").symlink_to(new)
    with sqlite3.connect(data / "core" / "stunsail.db") as db:
        db.execute("UPDATE example SET value='newer'")
    rollback_upgrade.rollback(source, safety)
    assert verify_backup.verify(safety)["release_path"] == str(new)
    assert value(safety / "data" / "core" / "stunsail.db") == "newer"
    assert value(data / "core" / "stunsail.db") == "original"
    assert value(root / "data.rollback-core-previous" / "stunsail.db") == "newer"
    assert (opt / "current").resolve() == old
    after = tmp_path / "after"
    backup_installation.backup(after)
    assert verify_backup.verify(after)["release_path"] == str(old)


def test_cli_requires_all_confirmations(tmp_path, monkeypatch):
    monkeypatch.setattr(rollback_upgrade, "rollback", lambda *args: pytest.fail("must not run"))
    flags = ["--confirm-rollback", "--confirm-writers-stopped", "--confirm-data-loss"]
    for omitted in range(len(flags)):
        with pytest.raises(SystemExit) as error:
            rollback_upgrade.main(
                [
                    str(tmp_path / "backup"),
                    str(tmp_path / "safety"),
                    *[f for i, f in enumerate(flags) if i != omitted],
                ]
            )
        assert error.value.code == 2
