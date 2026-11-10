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
        import install_fresh
        import maintenance_backup
        import rehearse_upgrade
        import remove_services
        import verify_backup
        import verify_release
    finally:
        sys.path.remove(str(INSTALLER))

pytestmark = pytest.mark.skipif(os.name != "posix", reason="requires POSIX installation tools")


@pytest.fixture(params=[True, False], ids=["standalone", "agent-only"])
def host(tmp_path, monkeypatch, request):
    root = tmp_path / "host"
    opt, etc, data = root / "opt", root / "etc", root / "data"
    current, candidate = opt / "releases" / "old", opt / "releases" / "new"
    current.mkdir(parents=True)
    candidate.mkdir(parents=True)
    (opt / "current").symlink_to(current)
    etc.mkdir()
    data.mkdir()
    if request.param:
        (etc / "core.env").write_text("private")
    units = root / "units"
    units.mkdir()
    for name in (install_fresh.AGENT_UNIT, install_fresh.CORE_UNIT):
        (units / name).write_text(name)
        path = candidate / "deployment" / "systemd" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    binary = candidate / ".venv" / "bin"
    binary.mkdir(parents=True)
    for name in ("python", "uvicorn", "stunsail-agent", "alembic"):
        path = binary / name
        path.write_text("test")
        path.chmod(0o755)
    monkeypatch.setattr(backup_installation, "OPT", opt)
    monkeypatch.setattr(backup_installation, "ETC", etc)
    monkeypatch.setattr(backup_installation, "DATA", data)
    monkeypatch.setattr(rehearse_upgrade.os, "geteuid", lambda: 0)
    monkeypatch.setattr(maintenance_backup, "_trusted_directory", lambda path: None)
    monkeypatch.setattr(maintenance_backup, "_validate_template", lambda name: units / name)
    monkeypatch.setattr(maintenance_backup, "_managed_unit", lambda unit, path: None)
    monkeypatch.setattr(maintenance_backup, "_loaded_agents", lambda: set())
    monkeypatch.setattr(backup_installation, "_agent_unit", lambda agent: agent)
    monkeypatch.setattr(backup_installation, "_no_active_agents", lambda: None)
    monkeypatch.setattr(backup_installation, "_stopped", lambda unit: None)
    monkeypatch.setattr(remove_services, "_reject_remaining_links", lambda core: None)
    events = []
    monkeypatch.setattr(maintenance_backup, "create", lambda path: events.append(("backup", path)))
    monkeypatch.setattr(
        verify_backup,
        "verify",
        lambda path: {
            "core": request.param,
            "release_path": str(current),
            "agents": ["printer-1"],
            "files": {"data/core/stunsail.db": "hash"},
        },
    )
    monkeypatch.setattr(verify_release, "verify", lambda path, release: None)
    monkeypatch.setattr(
        rehearse_upgrade, "_migration", lambda *args: events.append(("migrate", *args))
    )
    monkeypatch.setattr(rehearse_upgrade, "_smoke", lambda *args: events.append(("smoke", *args)))
    monkeypatch.setattr(rehearse_upgrade, "_agents", lambda *args: events.append(("agents", *args)))
    return root, current, candidate, tmp_path / "backup", events, request.param


def test_rehearsal_never_activates_or_migrates_live_data(host):
    root, current, candidate, backup, events, core = host
    rehearse_upgrade.rehearse(candidate, backup)
    assert events[0] == ("backup", backup)
    assert (root / "opt" / "current").resolve() == current
    if core:
        assert events[1] == (
            "migrate",
            candidate,
            backup,
            "hash",
            root / "data.upgrade-rehearsal",
        )
        assert events[2] == ("smoke", candidate, root / "data.upgrade-rehearsal")
    else:
        assert len(events) == 2
    assert events[-1][0] == "agents"
    assert events[-1][-1] == root / "data.upgrade-rehearsal-agents"


def test_unexpected_service_unit_fails_before_backup(host):
    root, _, candidate, backup, events, _ = host
    (candidate / "deployment" / "systemd" / install_fresh.AGENT_UNIT).write_text("different")
    with pytest.raises(ValueError, match="service unit differs"):
        rehearse_upgrade.rehearse(candidate, backup)
    assert events == []
    assert (root / "opt" / "current").is_symlink()


def test_changed_candidate_or_running_agent_prevents_migration(host, monkeypatch):
    _, _, candidate, backup, events, _ = host

    def create(path):
        events.append(("backup", path))
        (candidate / "changed").write_text("new")

    monkeypatch.setattr(maintenance_backup, "create", create)
    with pytest.raises(RuntimeError, match="candidate release changed"):
        rehearse_upgrade.rehearse(candidate, backup)
    assert len(events) == 1
    (candidate / "changed").unlink()
    monkeypatch.setattr(maintenance_backup, "create", lambda path: None)
    monkeypatch.setattr(maintenance_backup, "_loaded_agents", lambda: {"unexpected"})
    with pytest.raises(RuntimeError, match="unexpected loaded"):
        rehearse_upgrade.rehearse(candidate, backup)
    assert len(events) == 1


def test_changed_current_release_prevents_migration(host, monkeypatch):
    root, _, candidate, backup, events, _ = host
    alternate = root / "opt" / "releases" / "other"
    alternate.mkdir()

    def create(path):
        events.append(("backup", path))
        current_link = root / "opt" / "current"
        current_link.unlink()
        current_link.symlink_to(alternate)

    monkeypatch.setattr(maintenance_backup, "create", create)
    with pytest.raises(RuntimeError, match="current release changed"):
        rehearse_upgrade.rehearse(candidate, backup)
    assert events == [("backup", backup)]


def test_rejects_unprepared_or_existing_current_candidate(host):
    root, current, candidate, backup, events, _ = host
    with pytest.raises(ValueError, match="separate"):
        rehearse_upgrade.rehearse(current, backup)
    (candidate / ".venv" / "bin" / "alembic").unlink()
    with pytest.raises(ValueError, match="missing executable"):
        rehearse_upgrade.rehearse(candidate, backup)
    assert events == []
    assert (root / "opt" / "current").resolve() == current


def test_migration_uses_separate_copy_and_sanitized_environment(tmp_path, monkeypatch):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    backup = tmp_path / "backup"
    (backup / "data" / "core").mkdir(parents=True)
    source = backup / "data" / "core" / "stunsail.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE example (value TEXT)")
        db.execute("INSERT INTO example VALUES ('original')")
    monkeypatch.setattr(
        rehearse_upgrade.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=42, pw_gid=43)
    )
    monkeypatch.setattr(rehearse_upgrade.os, "chown", lambda *args: None)
    events = []

    def run(command, **kwargs):
        events.append((command, kwargs))
        if command[-2:] == ["upgrade", "head"]:
            with sqlite3.connect(tmp_path / "rehearsal" / "stunsail.db") as db:
                db.execute("UPDATE example SET value='migrated'")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(rehearse_upgrade.subprocess, "run", run)
    rehearse_upgrade._migration(
        candidate, backup, verify_backup.digest(source), tmp_path / "rehearsal"
    )
    assert events[0][0][-2:] == ["upgrade", "head"]
    assert events[1][0][-2:] == ["current", "--check-heads"]
    assert events[0][1]["cwd"] == candidate
    assert set(events[0][1]["env"]) == {"PATH", "HOME", "STUNSAIL_DATABASE_URL"}
    with sqlite3.connect(source) as db:
        assert db.execute("SELECT value FROM example").fetchone()[0] == "original"
    with sqlite3.connect(tmp_path / "rehearsal" / "stunsail.db") as db:
        assert db.execute("SELECT value FROM example").fetchone()[0] == "migrated"


def test_migration_failure_preserves_backup_and_partial_rehearsal(tmp_path, monkeypatch):
    backup = tmp_path / "backup"
    (backup / "data" / "core").mkdir(parents=True)
    source = backup / "data" / "core" / "stunsail.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE example (value TEXT)")
    monkeypatch.setattr(
        rehearse_upgrade.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=42, pw_gid=43)
    )
    monkeypatch.setattr(rehearse_upgrade.os, "chown", lambda *args: None)

    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(rehearse_upgrade.subprocess, "run", fail)
    digest = verify_backup.digest(source)
    with pytest.raises(subprocess.CalledProcessError):
        rehearse_upgrade._migration(tmp_path, backup, digest, tmp_path / "rehearsal")
    assert verify_backup.digest(source) == digest
    assert (tmp_path / "rehearsal" / "stunsail.db").is_file()


def test_smoke_uses_separate_database_and_temporary_admin_token(tmp_path, monkeypatch):
    database = tmp_path / "stunsail.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE example (value TEXT)")
        db.execute("INSERT INTO example VALUES ('original')")
    monkeypatch.setattr(
        rehearse_upgrade.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=42, pw_gid=43)
    )
    monkeypatch.setattr(rehearse_upgrade.os, "chown", lambda *args: None)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        with sqlite3.connect(tmp_path / "smoke.db") as db:
            db.execute("UPDATE example SET value='changed'")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(rehearse_upgrade.subprocess, "run", run)
    rehearse_upgrade._smoke(tmp_path, tmp_path)
    command, kwargs = calls[0]
    assert command[:4] == ["runuser", "-u", "stunsail-core", "--"]
    assert command[5] == "-I"
    assert kwargs["env"]["STUNSAIL_DATABASE_URL"] == f"sqlite:///{tmp_path / 'smoke.db'}"
    assert kwargs["env"]["STUNSAIL_ADMIN_TOKEN"] not in command
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT value FROM example").fetchone()[0] == "original"


def test_smoke_failure_propagates_and_keeps_migration_copy(host, monkeypatch):
    _, _, candidate, backup, events, core = host
    if not core:
        pytest.skip("Agent-only hosts have no Core smoke test")

    def fail(*args):
        raise subprocess.CalledProcessError(1, ["smoke"])

    monkeypatch.setattr(rehearse_upgrade, "_smoke", fail)
    with pytest.raises(subprocess.CalledProcessError):
        rehearse_upgrade.rehearse(candidate, backup)
    assert events[0] == ("backup", backup)
    assert events[1][0] == "migrate"


def test_agent_checks_copy_all_agents_without_tokens_or_network(tmp_path, monkeypatch):
    backup = tmp_path / "backup"
    files = {}
    for agent in ("printer-1", "printer-2"):
        for parent, name in (("config", "agent.yaml"), ("data", "buffer.db")):
            relative = f"{parent}/agent/{agent}/{name}"
            path = backup / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{agent}-{name}")
            files[relative] = verify_backup.digest(path)
    monkeypatch.setattr(
        rehearse_upgrade.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=42, pw_gid=43)
    )
    monkeypatch.setattr(rehearse_upgrade.os, "chown", lambda *args: None)
    calls = []
    monkeypatch.setattr(
        rehearse_upgrade.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )
    candidate = tmp_path / "candidate"
    destination = tmp_path / "rehearsal"
    rehearse_upgrade._agents(
        candidate, backup, {"agents": ["printer-1", "printer-2"], "files": files}, destination
    )
    assert len(calls) == 2
    for (command, kwargs), agent in zip(calls, ("printer-1", "printer-2"), strict=True):
        assert command[:4] == ["runuser", "-u", "stunsail-agent", "--"]
        assert command[-1] == agent
        assert kwargs["env"] == {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/nonexistent"}
        assert (destination / agent / "buffer.db").read_text() == f"{agent}-buffer.db"
        assert (destination / agent).stat().st_mode & 0o777 == 0o700


def test_agent_copy_digest_failure_prevents_execution(tmp_path, monkeypatch):
    backup = tmp_path / "backup"
    relative = "config/agent/printer-1/agent.yaml"
    source = backup / relative
    source.parent.mkdir(parents=True)
    source.write_text("changed")
    monkeypatch.setattr(
        rehearse_upgrade.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=42, pw_gid=43)
    )
    monkeypatch.setattr(rehearse_upgrade.os, "chown", lambda *args: None)
    monkeypatch.setattr(
        rehearse_upgrade.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not execute")
    )
    with pytest.raises(ValueError, match="does not match"):
        rehearse_upgrade._agents(
            tmp_path,
            backup,
            {"agents": ["printer-1"], "files": {relative: "0" * 64}},
            tmp_path / "rehearsal",
        )


def test_agent_failure_propagates_on_agent_only_host(host, monkeypatch):
    _, _, candidate, backup, events, core = host
    if core:
        pytest.skip("Agent-only path tested separately")

    def fail(*args):
        raise subprocess.CalledProcessError(1, ["agent-smoke"])

    monkeypatch.setattr(rehearse_upgrade, "_agents", fail)
    with pytest.raises(subprocess.CalledProcessError):
        rehearse_upgrade.rehearse(candidate, backup)
    assert events == [("backup", backup)]


def test_confirmation_required(tmp_path, monkeypatch):
    monkeypatch.setattr(rehearse_upgrade, "rehearse", lambda *args: pytest.fail("must not run"))
    for flags in ([], ["--confirm-stop-services"], ["--confirm-writers-stopped"]):
        with pytest.raises(SystemExit) as error:
            rehearse_upgrade.main([str(tmp_path / "candidate"), str(tmp_path / "backup"), *flags])
        assert error.value.code == 2
