import os
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
    finally:
        sys.path.remove(str(INSTALLER))

pytestmark = pytest.mark.skipif(os.name != "posix", reason="requires POSIX installation tools")


@pytest.fixture
def host(tmp_path, monkeypatch):
    root = tmp_path / "host"
    etc, data, opt, units = (root / name for name in ("etc", "data", "opt", "units"))
    for path in (etc / "agent", data / "agent", opt, units):
        path.mkdir(parents=True)
    for agent in ("printer-1", "printer-2"):
        (etc / "agent" / agent).mkdir()
        (data / "agent" / agent).mkdir()
        (data / "agent" / agent / "buffer.db").write_text("preserve")
    (etc / "core.env").write_text("preserve")
    for name in ("ETC", "DATA", "OPT"):
        monkeypatch.setattr(backup_installation, name, {"ETC": etc, "DATA": data, "OPT": opt}[name])
    monkeypatch.setattr(install_fresh, "UNITS", units)
    monkeypatch.setattr(maintenance_backup.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        maintenance_backup.guided_install, "validate_bundle_destination", lambda path: None
    )
    monkeypatch.setattr(
        maintenance_backup.preflight, "check_systemd", lambda _: SimpleNamespace(ok=True)
    )
    monkeypatch.setattr(backup_installation, "_agent_unit", lambda agent: f"agent:{agent}")
    monkeypatch.setattr(maintenance_backup, "_loaded_agents", lambda: {"agent:printer-1"})
    monkeypatch.setattr(maintenance_backup, "_managed_unit", lambda unit, path: None)
    monkeypatch.setattr(maintenance_backup, "_validate_template", lambda name: units / name)
    events = []
    monkeypatch.setattr(install_fresh, "_run", lambda *command: events.append(command))
    monkeypatch.setattr(backup_installation, "backup", lambda path: events.append(("backup", path)))
    # Avoid changing global stat behavior in tests; fixture paths are owned by the test user.
    monkeypatch.setattr(maintenance_backup, "_trusted_directory", lambda path: None)
    return root, etc, data, events


def test_stops_agents_before_core_and_backs_up_last(host, tmp_path):
    _, etc, data, events = host
    destination = tmp_path / "backup"
    maintenance_backup.create(destination)
    assert events == [
        ("systemctl", "disable", "agent:printer-1"),
        ("systemctl", "disable", "agent:printer-2"),
        ("systemctl", "disable", "stunsail-core.service"),
        ("systemctl", "stop", "agent:printer-1"),
        ("systemctl", "stop", "agent:printer-2"),
        ("systemctl", "stop", "stunsail-core.service"),
        ("backup", destination),
    ]
    assert (etc / "core.env").read_text() == "preserve"
    assert (data / "agent" / "printer-1" / "buffer.db").read_text() == "preserve"


def test_agent_only_does_not_stop_core(host, tmp_path):
    _, etc, _, events = host
    (etc / "core.env").unlink()
    maintenance_backup.create(tmp_path / "backup")
    assert not any("stunsail-core.service" in event for event in events)
    assert events[-1][0] == "backup"


def test_unexpected_or_mismatched_agents_fail_before_changes(host, tmp_path, monkeypatch):
    _, _, data, events = host
    monkeypatch.setattr(maintenance_backup, "_loaded_agents", lambda: {"agent:unknown"})
    with pytest.raises(ValueError, match="unexpected loaded"):
        maintenance_backup.create(tmp_path / "backup")
    assert not events
    monkeypatch.setattr(maintenance_backup, "_loaded_agents", lambda: set())
    (data / "agent" / "unknown").mkdir()
    with pytest.raises(ValueError, match="must match"):
        maintenance_backup.create(tmp_path / "backup")
    assert not events


def test_stop_failure_does_not_back_up_or_restart(host, tmp_path, monkeypatch):
    _, _, _, events = host

    def run(*command):
        events.append(command)
        if command[:2] == ("systemctl", "stop"):
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(install_fresh, "_run", run)
    with pytest.raises(subprocess.CalledProcessError):
        maintenance_backup.create(tmp_path / "backup")
    assert not any(event[0] == "backup" for event in events)
    assert not any(event[:2] == ("systemctl", "start") for event in events)


def test_missing_confirmation_does_not_touch_services(monkeypatch, tmp_path):
    monkeypatch.setattr(maintenance_backup, "create", lambda path: pytest.fail("must not run"))
    with pytest.raises(SystemExit) as error:
        maintenance_backup.main([str(tmp_path / "backup")])
    assert error.value.code == 2


def test_unexpected_service_template_is_rejected_before_disabling(host, tmp_path, monkeypatch):
    events = host[3]

    def reject(name):
        raise ValueError(f"unexpected template: {name}")

    monkeypatch.setattr(maintenance_backup, "_validate_template", reject)
    with pytest.raises(ValueError, match="unexpected template"):
        maintenance_backup.create(tmp_path / "backup")
    assert not events
