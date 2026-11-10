import os
import sys
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[2] / "deployment" / "installer"
if os.name == "posix":
    sys.path.insert(0, str(INSTALLER))
    try:
        import backup_installation
        import install_fresh
        import maintenance_backup
        import remove_services
        import verify_backup
    finally:
        sys.path.remove(str(INSTALLER))

pytestmark = pytest.mark.skipif(os.name != "posix", reason="requires POSIX installation tools")


@pytest.fixture
def managed(tmp_path, monkeypatch):
    root = tmp_path / "host"
    etc, opt, units = root / "etc", root / "opt", root / "units"
    (etc / "agent" / "printer-1").mkdir(parents=True)
    (opt / "releases" / "initial").mkdir(parents=True)
    (opt / "releases" / "initial" / "uv.lock").write_text("locked")
    (opt / "current").symlink_to(opt / "releases" / "initial")
    (etc / "core.env").write_text("private")
    data = root / "data"
    data.mkdir()
    (data / "important").write_text("retained")
    units.mkdir()
    for name in (install_fresh.AGENT_UNIT, install_fresh.CORE_UNIT):
        (units / name).write_text(name)
    monkeypatch.setattr(backup_installation, "ETC", etc)
    monkeypatch.setattr(backup_installation, "OPT", opt)
    monkeypatch.setattr(install_fresh, "UNITS", units)
    monkeypatch.setattr(remove_services, "OTHER_UNIT_DIRS", ())
    monkeypatch.setattr(remove_services.os, "geteuid", lambda: 0)
    events = []
    monkeypatch.setattr(maintenance_backup, "create", lambda path: events.append(("backup", path)))
    monkeypatch.setattr(
        verify_backup,
        "verify",
        lambda path: {
            "agents": ["printer-1"],
            "format": 2,
            "core": True,
            "release_path": str((opt / "current").resolve()),
            "lock_sha256": verify_backup.digest(opt / "current" / "uv.lock"),
        },
    )
    monkeypatch.setattr(backup_installation, "_agent_unit", lambda agent: "agent:" + agent)
    monkeypatch.setattr(backup_installation, "_no_active_agents", lambda: None)
    monkeypatch.setattr(
        backup_installation, "_stopped", lambda unit: events.append(("check", unit))
    )
    monkeypatch.setattr(maintenance_backup, "_loaded_agents", lambda: {"agent:printer-1"})
    monkeypatch.setattr(maintenance_backup, "_validate_template", lambda name: units / name)
    monkeypatch.setattr(maintenance_backup, "_managed_unit", lambda unit, path: None)
    monkeypatch.setattr(install_fresh, "_run", lambda *command: events.append(command))
    return root, etc, data, opt, units, events


def test_removes_only_units_after_verified_backup(managed, tmp_path):
    _, etc, data, opt, units, events = managed
    backup = tmp_path / "backup"
    remove_services.remove(backup)
    assert events[0] == ("backup", backup)
    assert events[-1] == ("systemctl", "daemon-reload")
    assert not (units / install_fresh.AGENT_UNIT).exists()
    assert not (units / install_fresh.CORE_UNIT).exists()
    assert (etc / "core.env").read_text() == "private"
    assert (data / "important").read_text() == "retained"
    assert (opt / "current").is_symlink()


@pytest.mark.parametrize("kind", ["unexpected", "alias", "dropin", "vendor"])
def test_conflicting_units_are_never_removed(managed, tmp_path, monkeypatch, kind):
    _, _, _, _, units, events = managed
    if kind == "unexpected":
        (units / "multi-user.target.wants").mkdir()
        (units / "multi-user.target.wants" / "stunsail-agent@other.service").symlink_to(
            units / install_fresh.AGENT_UNIT
        )
    elif kind == "alias":
        (units / "alias.service").symlink_to(units / install_fresh.CORE_UNIT)
    elif kind == "dropin":
        (units / "stunsail-core.service.d").mkdir()
    else:
        vendor = tmp_path / "vendor"
        vendor.mkdir()
        (vendor / install_fresh.AGENT_UNIT).write_text("other")
        monkeypatch.setattr(remove_services, "OTHER_UNIT_DIRS", (vendor,))
    with pytest.raises(ValueError):
        remove_services.remove(tmp_path / "backup")
    assert (units / install_fresh.AGENT_UNIT).is_file()
    assert (units / install_fresh.CORE_UNIT).is_file()
    assert not any(event[:2] == ("systemctl", "daemon-reload") for event in events)


def test_failed_backup_never_removes_units(managed, tmp_path, monkeypatch):
    units = managed[4]

    def fail(_):
        raise ValueError("damaged backup")

    monkeypatch.setattr(verify_backup, "verify", fail)
    with pytest.raises(ValueError, match="damaged backup"):
        remove_services.remove(tmp_path / "backup")
    assert (units / install_fresh.CORE_UNIT).exists()
    assert (units / install_fresh.AGENT_UNIT).exists()


def test_agent_only_removes_only_agent_unit(managed, tmp_path, monkeypatch):
    _, etc, data, opt, units, events = managed
    (etc / "core.env").unlink()
    (units / install_fresh.CORE_UNIT).unlink()
    monkeypatch.setattr(
        verify_backup,
        "verify",
        lambda path: {
            "agents": ["printer-1"],
            "format": 2,
            "core": False,
            "release_path": str((opt / "current").resolve()),
            "lock_sha256": verify_backup.digest(opt / "current" / "uv.lock"),
        },
    )
    remove_services.remove(tmp_path / "backup")
    assert not (units / install_fresh.AGENT_UNIT).exists()
    assert (data / "important").read_text() == "retained"
    assert not any(install_fresh.CORE_UNIT in event for event in events)


def test_changed_agent_list_or_active_service_prevents_removal(managed, tmp_path, monkeypatch):
    _, etc, _, _, units, _ = managed
    (etc / "agent" / "new").mkdir()
    with pytest.raises(RuntimeError, match="Agent list changed"):
        remove_services.remove(tmp_path / "backup")
    (etc / "agent" / "new").rmdir()

    def active(unit):
        raise RuntimeError(f"{unit} active")

    monkeypatch.setattr(backup_installation, "_stopped", active)
    with pytest.raises(RuntimeError, match="active"):
        remove_services.remove(tmp_path / "backup")
    assert (units / install_fresh.CORE_UNIT).exists()
    assert (units / install_fresh.AGENT_UNIT).exists()


def test_changed_release_or_unexpected_loaded_agent_prevents_removal(
    managed, tmp_path, monkeypatch
):
    _, _, _, opt, units, _ = managed
    lock_digest = verify_backup.digest(opt / "current" / "uv.lock")
    monkeypatch.setattr(
        verify_backup,
        "verify",
        lambda path: {
            "agents": ["printer-1"],
            "format": 2,
            "core": True,
            "release_path": str((opt / "current").resolve()),
            "lock_sha256": lock_digest,
        },
    )
    (opt / "current" / "uv.lock").write_text("changed")
    with pytest.raises(RuntimeError, match="lockfile changed"):
        remove_services.remove(tmp_path / "backup")
    (opt / "current" / "uv.lock").write_text("locked")
    monkeypatch.setattr(maintenance_backup, "_loaded_agents", lambda: {"agent:other"})
    with pytest.raises(RuntimeError, match="unexpected loaded"):
        remove_services.remove(tmp_path / "backup")
    assert (units / install_fresh.CORE_UNIT).exists()
    assert (units / install_fresh.AGENT_UNIT).exists()


def test_partial_unlink_failure_still_reloads_systemd(managed, tmp_path, monkeypatch):
    units, events = managed[4], managed[5]
    original = Path.unlink

    def unlink(path, *args, **kwargs):
        if path == units / install_fresh.CORE_UNIT:
            raise PermissionError("test failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    with pytest.raises(PermissionError, match="test failure"):
        remove_services.remove(tmp_path / "backup")
    assert not (units / install_fresh.AGENT_UNIT).exists()
    assert (units / install_fresh.CORE_UNIT).exists()
    assert events[-1] == ("systemctl", "daemon-reload")


def test_confirmation_is_required(tmp_path, monkeypatch):
    monkeypatch.setattr(remove_services, "remove", lambda path: pytest.fail("must not run"))
    with pytest.raises(SystemExit) as error:
        remove_services.main([str(tmp_path / "backup")])
    assert error.value.code == 2
