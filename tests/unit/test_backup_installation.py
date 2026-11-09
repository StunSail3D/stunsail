import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

INSTALLER = Path(__file__).resolve().parents[2] / "deployment" / "installer"
if os.name == "posix":
    sys.path.insert(0, str(INSTALLER))
    try:
        import backup_installation
        import configure
        import install_fresh
        import maintenance_backup
        import release_fingerprint
        import remove_services
        import stage_restore
        import verify_backup
        import verify_release
    finally:
        sys.path.remove(str(INSTALLER))

pytestmark = pytest.mark.skipif(os.name != "posix", reason="requires POSIX installation tools")


@pytest.fixture
def installation(tmp_path, monkeypatch):
    root = tmp_path / "host"
    etc, data, opt = (root / name for name in ("etc", "data", "opt"))
    for path in (etc / "agent", data / "agent", opt / "releases" / "initial"):
        path.mkdir(parents=True)
    release = opt / "releases" / "initial"
    (release / "pyproject.toml").write_text('[project]\nversion="0.1.0"\n')
    (release / "uv.lock").write_text("locked")
    (opt / "current").symlink_to(release)
    (etc / "core.env").write_text(
        "STUNSAIL_DATABASE_URL=sqlite:////var/lib/stunsail/core/stunsail.db\n"
        "STUNSAIL_ADMIN_TOKEN=private_admin_token\n"
    )
    (data / "core").mkdir()
    databases = [data / "core" / "stunsail.db"]
    for agent_id in ("printer-1", "printer-2"):
        config, token, _ = configure.build_configuration(
            "agent_only",
            agent_id,
            "http://printer",
            "https://core.local",
            "test_token_123456789",
        )
        agent_config = etc / "agent" / agent_id
        agent_config.mkdir()
        (agent_config / "agent.yaml").write_text(json.dumps(config))
        (agent_config / "agent.env").write_text(f"STUNSAIL_AGENT_TOKEN={token}\n")
        agent_data = data / "agent" / agent_id
        agent_data.mkdir()
        databases.append(agent_data / "buffer.db")
    connections = []
    for database in databases:
        db = sqlite3.connect(database)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE example (value TEXT)")
        db.execute("INSERT INTO example VALUES ('committed')")
        db.commit()
        connections.append(db)
    monkeypatch.setattr(backup_installation, "ETC", etc)
    monkeypatch.setattr(backup_installation, "DATA", data)
    monkeypatch.setattr(backup_installation, "OPT", opt)
    monkeypatch.setattr(backup_installation.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        backup_installation.guided_install, "validate_bundle_destination", lambda path: None
    )
    stopped = []
    monkeypatch.setattr(backup_installation, "_stopped", stopped.append)
    monkeypatch.setattr(backup_installation, "_agent_unit", lambda agent_id: "agent:" + agent_id)
    monkeypatch.setattr(backup_installation, "_no_active_agents", lambda: None)
    yield etc, data, opt, stopped
    for db in connections:
        db.close()


def test_backup_all_databases_and_secrets_into_private_new_directory(installation, tmp_path):
    etc, data, opt, stopped = installation
    output = tmp_path / "backup"
    backup_installation.backup(output)
    assert stopped == ["agent:printer-1", "agent:printer-2", "stunsail-core.service"] * 2
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["agents"] == ["printer-1", "printer-2"]
    assert manifest["version"] == "0.1.0"
    assert manifest["core"] is True
    assert manifest["format"] == 3
    assert manifest["release_sha256"] == release_fingerprint.fingerprint(
        opt / "releases" / "initial"
    )
    assert verify_backup.verify(output) == manifest
    assert manifest["release_path"] == str((opt / "releases" / "initial").resolve())
    assert (output / "config" / "core.env").read_bytes() == (etc / "core.env").read_bytes()
    for db in (
        output / "data" / "core" / "stunsail.db",
        output / "data" / "agent" / "printer-1" / "buffer.db",
        output / "data" / "agent" / "printer-2" / "buffer.db",
    ):
        with sqlite3.connect(db) as connection:
            assert connection.execute("SELECT value FROM example").fetchone() == ("committed",)
        assert db.stat().st_mode & 0o777 == 0o600
    assert output.stat().st_mode & 0o777 == 0o700
    assert (output / "config" / "core.env").stat().st_mode & 0o777 == 0o600


def test_service_removal_uses_real_backup_and_verification(installation, tmp_path, monkeypatch):
    etc, data, _, _ = installation
    units = tmp_path / "units"
    units.mkdir()
    for name in (install_fresh.AGENT_UNIT, install_fresh.CORE_UNIT):
        (units / name).write_text(name)
    monkeypatch.setattr(install_fresh, "UNITS", units)
    monkeypatch.setattr(remove_services, "OTHER_UNIT_DIRS", ())
    monkeypatch.setattr(maintenance_backup, "_trusted_directory", lambda path: None)
    monkeypatch.setattr(
        maintenance_backup.preflight, "check_systemd", lambda _: SimpleNamespace(ok=True)
    )
    monkeypatch.setattr(maintenance_backup, "_loaded_agents", lambda: set())
    monkeypatch.setattr(maintenance_backup, "_managed_unit", lambda unit, path: None)
    monkeypatch.setattr(maintenance_backup, "_validate_template", lambda name: units / name)
    events = []
    monkeypatch.setattr(install_fresh, "_run", lambda *command: events.append(command))

    backup = tmp_path / "removal-backup"
    remove_services.remove(backup)
    assert verify_backup.verify(backup)["agents"] == ["printer-1", "printer-2"]
    assert not (units / install_fresh.AGENT_UNIT).exists()
    assert not (units / install_fresh.CORE_UNIT).exists()
    assert (etc / "core.env").is_file()
    with sqlite3.connect(data / "core" / "stunsail.db") as db:
        assert db.execute("SELECT value FROM example").fetchone() == ("committed",)
    assert events[-1] == ("systemctl", "daemon-reload")


def test_removal_rejects_source_changes_after_backup(installation, tmp_path, monkeypatch):
    _, _, opt, _ = installation
    units = tmp_path / "units"
    units.mkdir()
    for name in (install_fresh.AGENT_UNIT, install_fresh.CORE_UNIT):
        (units / name).write_text(name)
    monkeypatch.setattr(install_fresh, "UNITS", units)

    def create_backup(path):
        backup_installation.backup(path)
        (opt / "current" / "new-source.py").write_text("changed")

    monkeypatch.setattr(maintenance_backup, "create", create_backup)
    monkeypatch.setattr(maintenance_backup, "_loaded_agents", lambda: set())
    with pytest.raises(RuntimeError, match="release files changed"):
        remove_services.remove(tmp_path / "backup")
    assert (units / install_fresh.AGENT_UNIT).is_file()
    assert (units / install_fresh.CORE_UNIT).is_file()


def test_release_comparison_detects_changes_but_ignores_runtime_and_python_caches(
    installation, tmp_path
):
    _, _, opt, _ = installation
    release = opt / "releases" / "initial"
    (release / ".venv").mkdir()
    (release / ".venv" / "runtime").write_text("runtime 1")
    (release / "__pycache__").mkdir()
    (release / "__pycache__" / "module.pyc").write_text("cache 1")
    backup = tmp_path / "backup"
    backup_installation.backup(backup)
    verify_release.verify(backup, release)
    (release / ".venv" / "runtime").write_text("runtime 2")
    (release / "__pycache__" / "module.pyc").write_text("cache 2")
    verify_release.verify(backup, release)
    (release / "new-source.py").write_text("changed")
    with pytest.raises(ValueError, match="do not match"):
        verify_release.verify(backup, release)


def test_format_2_backups_remain_verifiable_but_cannot_prove_release_match(installation, tmp_path):
    _, _, opt, _ = installation
    backup = tmp_path / "backup"
    backup_installation.backup(backup)
    path = backup / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["format"] = 2
    manifest.pop("release_sha256")
    path.write_text(json.dumps(manifest))
    assert verify_backup.verify(backup)["format"] == 2
    with pytest.raises(ValueError, match="do not contain a release fingerprint"):
        verify_release.verify(backup, opt / "releases" / "initial")


@pytest.mark.parametrize("value", [None, "invalid", "A" * 64])
def test_format_3_requires_valid_release_fingerprint(installation, tmp_path, value):
    backup = tmp_path / "backup"
    backup_installation.backup(backup)
    path = backup / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["release_sha256"] = value
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="invalid release fingerprint"):
        verify_backup.verify(backup)


def test_release_comparison_cli_reports_match_and_mismatch(installation, tmp_path):
    _, _, opt, _ = installation
    release = opt / "releases" / "initial"
    backup = tmp_path / "backup"
    backup_installation.backup(backup)
    command = [sys.executable, str(INSTALLER / "verify_release.py"), str(backup), str(release)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "match the backup fingerprint" in result.stdout
    (release / "uv.lock").write_text("different")
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "do not match" in result.stderr


def test_release_change_during_backup_leaves_no_completion_manifest(
    installation, tmp_path, monkeypatch
):
    _, _, opt, _ = installation
    original = backup_installation.sqlite_snapshot.snapshot

    def snapshot(source, destination):
        original(source, destination)
        (opt / "releases" / "initial" / "added.py").write_text("changed")

    monkeypatch.setattr(backup_installation.sqlite_snapshot, "snapshot", snapshot)
    backup = tmp_path / "backup"
    with pytest.raises(RuntimeError, match="release files changed"):
        backup_installation.backup(backup)
    assert not (backup / "manifest.json").exists()


def test_release_fingerprint_rejects_symlinked_files_and_directories(installation):
    _, _, opt, _ = installation
    release = opt / "releases" / "initial"
    symlink = release / "alias"
    symlink.symlink_to(release / "uv.lock")
    with pytest.raises(ValueError, match="non-regular"):
        release_fingerprint.fingerprint(release)
    symlink.unlink()
    symlink.symlink_to(release, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        release_fingerprint.fingerprint(release)


def test_active_service_prevents_any_backup(installation, tmp_path, monkeypatch):
    def active(unit):
        raise RuntimeError(f"{unit} is active")

    monkeypatch.setattr(backup_installation, "_stopped", active)
    output = tmp_path / "backup"
    with pytest.raises(RuntimeError, match="active"):
        backup_installation.backup(output)
    assert not output.exists()


def test_rejects_mismatched_agent_data_and_external_ca(installation, tmp_path):
    etc, data, _, _ = installation
    extra = data / "agent" / "unknown"
    extra.mkdir()
    with pytest.raises(ValueError, match="must match"):
        backup_installation.backup(tmp_path / "backup")
    extra.rmdir()
    path = etc / "agent" / "printer-1" / "agent.yaml"
    config = json.loads(path.read_text())
    config["agent"]["core_ca_file"] = "/outside/ca.pem"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="external or missing"):
        backup_installation.backup(tmp_path / "backup")
    assert not (tmp_path / "backup").exists()


def test_refuses_symlinked_database_without_creating_backup(installation, tmp_path):
    _, data, _, _ = installation
    database = data / "agent" / "printer-1" / "buffer.db"
    database.rename(database.with_suffix(".original"))
    database.symlink_to(data / "core" / "stunsail.db")
    with pytest.raises(ValueError, match="regular file"):
        backup_installation.backup(tmp_path / "backup")
    assert not (tmp_path / "backup").exists()


def test_started_service_during_backup_leaves_no_completion_manifest(
    installation, tmp_path, monkeypatch
):
    calls = 0

    def check(unit):
        nonlocal calls
        calls += 1
        if calls > 3:
            raise RuntimeError(f"{unit} was started")

    monkeypatch.setattr(backup_installation, "_stopped", check)
    output = tmp_path / "backup"
    with pytest.raises(RuntimeError, match="was started"):
        backup_installation.backup(output)
    assert output.exists()
    assert not (output / "manifest.json").exists()


@pytest.mark.parametrize(
    ("load", "state", "valid"),
    [
        ("loaded", "inactive", True),
        ("loaded", "failed", True),
        ("loaded", "active", False),
        ("loaded", "activating", False),
        ("not-found", "inactive", False),
    ],
)
def test_stopped_check_requires_loaded_and_inactive_unit(monkeypatch, load, state, valid):
    def run(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 0, stdout=f"LoadState={load}\nActiveState={state}\n"
        )

    monkeypatch.setattr(backup_installation.subprocess, "run", run)
    if valid:
        backup_installation._stopped("stunsail-core.service")
    else:
        with pytest.raises(RuntimeError, match="not loaded and stopped"):
            backup_installation._stopped("stunsail-core.service")


def test_additional_active_agent_blocks_backup(monkeypatch):
    monkeypatch.setattr(
        backup_installation.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, stdout="stunsail-agent@other.service loaded active running\n"
        ),
    )
    with pytest.raises(RuntimeError, match="additional Agent service"):
        backup_installation._no_active_agents()


@pytest.mark.parametrize("change", ["modify", "missing", "extra", "symlink", "old-format"])
def test_verification_rejects_damaged_or_incomplete_backup(installation, tmp_path, change):
    output = tmp_path / "backup"
    backup_installation.backup(output)
    target = output / "config" / "agent" / "printer-1" / "agent.env"
    if change == "modify":
        target.write_text("changed")
    elif change == "missing":
        target.unlink()
    elif change == "extra":
        (output / "extra").write_text("extra")
    elif change == "symlink":
        target.unlink()
        target.symlink_to(output / "config" / "core.env")
    else:
        manifest_path = output / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["format"] = 1
        manifest_path.write_text(json.dumps(manifest))
    with pytest.raises((ValueError, OSError)):
        verify_backup.verify(output)


def test_verification_checks_database_integrity_even_if_hash_is_recomputed(installation, tmp_path):
    output = tmp_path / "backup"
    backup_installation.backup(output)
    relative = "data/agent/printer-1/buffer.db"
    target = output.joinpath(*relative.split("/"))
    target.write_bytes(b"SQLite format 3\x00" + bytes(100))
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][relative] = verify_backup.digest(target)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(sqlite3.DatabaseError):
        verify_backup.verify(output)


def test_verification_rejects_agent_path_traversal_and_missing_ca(installation, tmp_path):
    output = tmp_path / "backup"
    backup_installation.backup(output)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["agents"][0] = "../other"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="invalid Agent list"):
        verify_backup.verify(output)
    manifest["agents"][0] = "printer-1"
    config = output / "config" / "agent" / "printer-1" / "agent.yaml"
    raw = json.loads(config.read_text())
    raw["agent"]["core_ca_file"] = "/etc/stunsail/agent/printer-1/ca.pem"
    config.write_text(json.dumps(raw))
    manifest["files"]["config/agent/printer-1/agent.yaml"] = verify_backup.digest(config)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="CA bundle is missing"):
        verify_backup.verify(output)


def test_verifier_is_read_only_and_returns_nonzero_on_incomplete_backup(installation, tmp_path):
    output = tmp_path / "backup"
    backup_installation.backup(output)
    files_before = {p.relative_to(output).as_posix() for p in output.rglob("*")}
    command = [sys.executable, str(INSTALLER / "verify_backup.py"), str(output)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "Backup verified" in result.stdout
    assert {p.relative_to(output).as_posix() for p in output.rglob("*")} == files_before
    (output / "manifest.json").unlink()
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "verification failed" in result.stderr


def test_stages_independent_verified_copy_without_modifying_live_or_backup(installation, tmp_path):
    _, data, _, _ = installation
    source = tmp_path / "backup"
    destination = tmp_path / "restored"
    backup_installation.backup(source)
    stage_restore.stage(source, destination)
    assert verify_backup.verify(destination) == verify_backup.verify(source)
    assert destination.stat().st_mode & 0o777 == 0o700
    assert (destination / "config" / "core.env").stat().st_mode & 0o777 == 0o600
    original = data / "core" / "stunsail.db"
    with sqlite3.connect(destination / "data" / "core" / "stunsail.db") as copy:
        copy.execute("INSERT INTO example VALUES ('restored-only')")
        copy.commit()
    with sqlite3.connect(original) as live:
        assert live.execute("SELECT COUNT(*) FROM example").fetchone() == (1,)
    assert verify_backup.verify(source)


def test_maintenance_workflow_creates_verifiable_backup(installation, tmp_path, monkeypatch):
    _, _, _, stopped = installation
    actions = []
    monkeypatch.setattr(maintenance_backup, "_trusted_directory", lambda path: None)
    monkeypatch.setattr(maintenance_backup, "_validate_template", lambda name: Path(name))
    monkeypatch.setattr(maintenance_backup, "_managed_unit", lambda unit, path: None)
    monkeypatch.setattr(maintenance_backup, "_loaded_agents", lambda: set())
    monkeypatch.setattr(
        maintenance_backup.preflight,
        "check_systemd",
        lambda name: type("Check", (), {"ok": True})(),
    )
    monkeypatch.setattr(install_fresh, "_run", lambda *command: actions.append(command))
    output = tmp_path / "backup"
    maintenance_backup.create(output)
    manifest = verify_backup.verify(output)
    assert manifest["agents"] == ["printer-1", "printer-2"]
    assert len(stopped) == 6
    assert actions[-1] == ("systemctl", "stop", "stunsail-core.service")
    assert not any(command[:2] == ("systemctl", "start") for command in actions)


def test_restore_refuses_damaged_backup_and_existing_destination(installation, tmp_path):
    source = tmp_path / "backup"
    backup_installation.backup(source)
    output = tmp_path / "restore"
    output.mkdir()
    marker = output / "keep"
    marker.write_text("unchanged")
    with pytest.raises(FileExistsError):
        stage_restore.stage(source, output)
    assert marker.read_text() == "unchanged"
    (source / "config" / "core.env").write_text("damaged")
    with pytest.raises(ValueError, match="checksum mismatch"):
        stage_restore.stage(source, tmp_path / "new")
    assert not (tmp_path / "new").exists()
