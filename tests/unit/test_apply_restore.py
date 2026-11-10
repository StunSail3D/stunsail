import json
import os
import shutil
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
        import backup_installation
        import configure
        import maintenance_backup
        import remove_services
        import verify_backup
    finally:
        sys.path.remove(str(INSTALLER))

pytestmark = pytest.mark.skipif(os.name != "posix", reason="requires POSIX installation tools")


@pytest.fixture(params=[True, False], ids=["standalone", "agent-only"])
def host(tmp_path, monkeypatch, request):
    root = tmp_path / "host"
    etc, data, opt = (root / name for name in ("etc", "data", "opt"))
    agent_config, agent_data = etc / "agent" / "printer-1", data / "agent" / "printer-1"
    agent_config.mkdir(parents=True)
    agent_data.mkdir(parents=True)
    release = opt / "releases" / "initial"
    release.mkdir(parents=True)
    (opt / "current").symlink_to(release)
    (release / "pyproject.toml").write_text('[project]\nversion="0.1.0"\n')
    (release / "uv.lock").write_text("locked")
    config, token, _ = configure.build_configuration(
        "agent_only", "printer-1", "http://printer", "https://core.local", "test_token_123456789"
    )
    (agent_config / "agent.yaml").write_text(json.dumps(config))
    (agent_config / "agent.env").write_text(f"STUNSAIL_AGENT_TOKEN={token}\n")
    databases = [agent_data / "buffer.db"]
    if request.param:
        (etc / "core.env").write_text(
            "STUNSAIL_DATABASE_URL=sqlite:////var/lib/stunsail/core/stunsail.db\n"
        )
        (data / "core").mkdir()
        databases.append(data / "core" / "stunsail.db")
    for path in databases:
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE example (value TEXT)")
            db.execute("INSERT INTO example VALUES ('original')")
    for name, value in (("ETC", etc), ("DATA", data), ("OPT", opt)):
        monkeypatch.setattr(backup_installation, name, value)
    monkeypatch.setattr(backup_installation.os, "geteuid", lambda: 0)
    monkeypatch.setattr(backup_installation.os, "chown", lambda *args: None)
    monkeypatch.setattr(
        apply_restore.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=123, pw_gid=456)
    )
    monkeypatch.setattr(apply_restore, "_trusted_backup", lambda _: None)
    monkeypatch.setattr(maintenance_backup, "_trusted_directory", lambda _: None)
    monkeypatch.setattr(
        backup_installation.guided_install, "validate_bundle_destination", lambda path: None
    )
    monkeypatch.setattr(backup_installation, "_stopped", lambda unit: None)
    monkeypatch.setattr(backup_installation, "_agent_unit", lambda agent: f"agent:{agent}")
    monkeypatch.setattr(backup_installation, "_no_active_agents", lambda: None)
    monkeypatch.setattr(maintenance_backup, "create", backup_installation.backup)
    monkeypatch.setattr(maintenance_backup, "_loaded_agents", lambda: set())
    monkeypatch.setattr(maintenance_backup, "_validate_template", lambda name: Path(name))
    monkeypatch.setattr(maintenance_backup, "_managed_unit", lambda unit, path: None)
    monkeypatch.setattr(remove_services, "_reject_remaining_links", lambda core: None)
    source = tmp_path / "source-backup"
    backup_installation.backup(source)
    for path in databases:
        with sqlite3.connect(path) as db:
            db.execute("UPDATE example SET value='newer'")
    return etc, data, opt, source, tmp_path / "safety-backup", databases


def _value(path):
    with sqlite3.connect(path) as db:
        return db.execute("SELECT value FROM example").fetchone()[0]


def test_restores_backup_and_preserves_current_installation(host):
    etc, data, _, source, safety, databases = host
    apply_restore.apply(source, safety)
    assert verify_backup.verify(safety)["agents"] == ["printer-1"]
    for original in databases:
        assert _value(original) == "original"
        previous = data.with_name(data.name + ".restore-previous") / original.relative_to(data)
        assert _value(previous) == "newer"
    assert (etc.with_name(etc.name + ".restore-previous") / "agent" / "printer-1").is_dir()
    assert (etc / "agent" / "printer-1" / "agent.env").stat().st_mode & 0o777 == 0o600
    assert (etc / "agent" / "printer-1" / "agent.yaml").stat().st_mode & 0o777 == 0o440
    assert (data / "agent" / "printer-1" / "buffer.db").stat().st_mode & 0o777 == 0o600


def test_mismatched_release_is_rejected_before_backup(host):
    etc, data, opt, source, safety, databases = host
    (opt / "releases" / "initial" / "uv.lock").write_text("different")
    with pytest.raises(ValueError, match="do not match"):
        apply_restore.apply(source, safety)
    assert not safety.exists()
    assert etc.exists() and data.exists()
    assert all(_value(path) == "newer" for path in databases)


def test_mismatched_topology_does_not_swap_directories(host):
    etc, data, _, source, safety, databases = host
    shutil.copytree(etc / "agent" / "printer-1", etc / "agent" / "printer-2")
    shutil.copytree(data / "agent" / "printer-1", data / "agent" / "printer-2")
    config = etc / "agent" / "printer-2" / "agent.yaml"
    values = json.loads(config.read_text())
    values["agent"]["agent_id"] = "printer-2"
    values["agent"]["local_buffer_url"] = "sqlite:////var/lib/stunsail/agent/printer-2/buffer.db"
    config.write_text(json.dumps(values))
    with pytest.raises(ValueError, match="topology does not match"):
        apply_restore.apply(source, safety)
    assert verify_backup.verify(safety)["agents"] == ["printer-1", "printer-2"]
    assert etc.exists() and data.exists()
    assert all(_value(path) == "newer" for path in databases)


def test_service_failure_never_swaps_directories(host, monkeypatch):
    etc, data, _, source, safety, databases = host

    def reject(unit):
        raise RuntimeError("unit active")

    monkeypatch.setattr(backup_installation, "_stopped", reject)
    with pytest.raises(RuntimeError, match="unit active"):
        apply_restore.apply(source, safety)
    assert etc.exists() and data.exists()
    assert all(_value(path) == "newer" for path in databases)


def test_post_backup_service_failure_never_swaps_directories(host, monkeypatch):
    etc, data, _, source, safety, databases = host
    calls = 0

    def reject_after_backup(unit):
        nonlocal calls
        calls += 1
        if calls > len(databases) * 2:
            raise RuntimeError("unit restarted")

    monkeypatch.setattr(backup_installation, "_stopped", reject_after_backup)
    with pytest.raises(RuntimeError, match="unit restarted"):
        apply_restore.apply(source, safety)
    assert verify_backup.verify(safety)
    assert etc.exists() and data.exists()
    assert all(_value(path) == "newer" for path in databases)


def test_corrupt_copy_never_swaps_directories(host, monkeypatch):
    etc, data, _, source, safety, databases = host
    original = backup_installation._private_copy

    def corrupt(src, dst):
        original(src, dst)
        if dst.name == "agent.yaml" and ".restore-new" in str(dst):
            dst.write_text("corrupted")

    monkeypatch.setattr(backup_installation, "_private_copy", corrupt)
    with pytest.raises(ValueError, match="does not match"):
        apply_restore.apply(source, safety)
    assert verify_backup.verify(safety)
    assert etc.exists() and data.exists()
    assert all(_value(path) == "newer" for path in databases)


def test_existing_recovery_path_prevents_any_changes(host):
    etc, _, _, source, safety, _ = host
    etc.with_name(etc.name + ".restore-previous").mkdir()
    with pytest.raises(FileExistsError):
        apply_restore.apply(source, safety)
    assert not safety.exists()


def test_failure_during_swap_keeps_previous_directories(host, monkeypatch):
    etc, data, _, source, safety, _ = host
    original = os.rename

    def rename(src, dst):
        if src == data:
            raise OSError("simulated failure")
        original(src, dst)

    monkeypatch.setattr(apply_restore.os, "rename", rename)
    with pytest.raises(OSError, match="simulated failure"):
        apply_restore.apply(source, safety)
    assert (etc.with_name(etc.name + ".restore-previous") / "agent").is_dir()
    assert (data.with_name(data.name + ".restore-new") / "agent").is_dir()
    assert data.exists()
    assert verify_backup.verify(safety)


def test_original_database_sidecars_are_preserved_without_copying_into_restore(host, monkeypatch):
    _, data, _, source, safety, _ = host
    directory = data / "agent" / "printer-1"

    def create_sidecars(_):
        (directory / "buffer.db-wal").write_bytes(b"old wal")
        (directory / "buffer.db-shm").write_bytes(b"old shm")

    monkeypatch.setattr(remove_services, "_reject_remaining_links", create_sidecars)
    apply_restore.apply(source, safety)
    previous = data.with_name(data.name + ".restore-previous") / "agent" / "printer-1"
    assert (previous / "buffer.db-wal").read_bytes() == b"old wal"
    assert (previous / "buffer.db-shm").read_bytes() == b"old shm"
    assert not (data / "agent" / "printer-1" / "buffer.db-wal").exists()
    assert not (data / "agent" / "printer-1" / "buffer.db-shm").exists()


def test_cli_requires_both_confirmations(tmp_path, monkeypatch):
    monkeypatch.setattr(apply_restore, "apply", lambda *args: pytest.fail("must not run"))
    for flags in ([], ["--confirm-restore"], ["--confirm-writers-stopped"]):
        with pytest.raises(SystemExit) as error:
            apply_restore.main([str(tmp_path / "backup"), str(tmp_path / "safety"), *flags])
        assert error.value.code == 2


@pytest.mark.skipif(os.name != "posix" or os.getuid() != 0, reason="requires root-owned test files")
def test_private_backup_validation_rejects_bad_permissions_and_symlinks(tmp_path, monkeypatch):
    monkeypatch.setattr(maintenance_backup, "_trusted_directory", lambda path: None)
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    secret = source / "secret"
    secret.write_text("private")
    secret.chmod(0o600)
    apply_restore._trusted_backup(source)
    secret.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        apply_restore._trusted_backup(source)
    secret.chmod(0o600)
    (source / "link").symlink_to(secret)
    with pytest.raises(ValueError, match="private|non-regular"):
        apply_restore._trusted_backup(source)


@pytest.mark.skipif(os.name != "posix" or os.getuid() != 0, reason="requires root for ownership")
def test_restored_file_and_directory_ownership_on_linux(tmp_path):
    source = tmp_path / "source"
    source.write_text("database")
    directory = tmp_path / "restored"
    apply_restore._new_directory(directory, 0o700, 65534, 65534)
    target = directory / "buffer.db"
    apply_restore._copy(source, target, verify_backup.digest(source), 0o600, 65534, 65534)
    assert (directory.stat().st_uid, directory.stat().st_gid) == (65534, 65534)
    assert (target.stat().st_uid, target.stat().st_gid) == (65534, 65534)
    assert target.stat().st_mode & 0o777 == 0o600
