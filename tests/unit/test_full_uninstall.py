import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

INSTALLER = Path(__file__).resolve().parents[2] / "deployment" / "installer"
if os.name == "posix":
    sys.path.insert(0, str(INSTALLER))
    try:
        import full_uninstall
        import install_fresh
    finally:
        sys.path.remove(str(INSTALLER))

pytestmark = pytest.mark.skipif(os.name != "posix", reason="requires POSIX installation tools")


@pytest.fixture
def host(tmp_path, monkeypatch):
    root = tmp_path / "host"
    opt, etc, data, units = (root / name for name in ("opt", "etc", "data", "units"))
    for path in (opt, etc, data, units):
        path.mkdir(parents=True)
    (units / install_fresh.CORE_UNIT).write_text("core")
    (units / install_fresh.AGENT_UNIT).write_text("agent")
    (units / full_uninstall.FRONTEND_UNIT).write_text("frontend")
    wants = units / "multi-user.target.wants"
    wants.mkdir()
    (wants / "stunsail-agent@printer-1.service").symlink_to(units / install_fresh.AGENT_UNIT)
    (wants / install_fresh.CORE_UNIT).symlink_to(units / install_fresh.CORE_UNIT)
    (etc / "agent" / "printer-1").mkdir(parents=True)
    (etc / "core.env").write_text("secret")
    (etc / "certs").mkdir()
    (etc / "certs" / "server.key").write_text("key")
    (data / "core").mkdir()
    (data / "core" / "stunsail.db").write_text("db")
    (opt / "releases" / "initial").mkdir(parents=True)
    (opt / "current").symlink_to(opt / "releases" / "initial", target_is_directory=True)

    for name, value in (("OPT", opt), ("ETC", etc), ("DATA", data), ("UNITS", units)):
        monkeypatch.setattr(install_fresh, name, value)

    events = []
    accounts = {"stunsail-core", "stunsail-agent"}
    groups = {"stunsail-core", "stunsail-agent"}
    loaded = {"agent:printer-1"}

    def fake_run(*command):
        events.append(command)
        if command[0] == "userdel":
            accounts.discard(command[1])
        elif command[0] == "groupdel":
            groups.discard(command[1])
        elif command == ("systemctl", "daemon-reload"):
            loaded.clear()

    def getpwnam(name):
        if name not in accounts:
            raise KeyError(name)
        return SimpleNamespace(pw_uid=1, pw_gid=1)

    def getgrnam(name):
        if name not in groups:
            raise KeyError(name)
        return SimpleNamespace(gr_gid=1)

    monkeypatch.setattr(install_fresh, "_run", fake_run)
    monkeypatch.setattr(
        full_uninstall.maintenance_backup, "create", lambda dest: events.append(("backup", dest))
    )
    monkeypatch.setattr(
        full_uninstall.verify_backup, "verify", lambda dest: {"agents": ["printer-1"], "core": True}
    )
    monkeypatch.setattr(full_uninstall.maintenance_backup, "_loaded_agents", lambda: set(loaded))
    monkeypatch.setattr(full_uninstall.backup_installation, "_agent_unit", lambda a: "agent:" + a)
    monkeypatch.setattr(full_uninstall.pwd, "getpwnam", getpwnam)
    monkeypatch.setattr(full_uninstall.grp, "getgrnam", getgrnam)
    free_values = iter([1000, 2000])
    monkeypatch.setattr(full_uninstall, "_disk_free", lambda: next(free_values))
    return SimpleNamespace(
        opt=opt,
        etc=etc,
        data=data,
        units=units,
        events=events,
        accounts=accounts,
        groups=groups,
        loaded=loaded,
    )


def test_uninstall_backs_up_first_then_removes_everything(host, tmp_path):
    backup = tmp_path / "backup"
    report = full_uninstall.uninstall(backup)
    assert host.events[0] == ("backup", backup)
    assert ("systemctl", "disable", "--now", full_uninstall.FRONTEND_UNIT) in host.events
    assert ("systemctl", "disable", "agent:printer-1") in host.events
    assert ("systemctl", "stop", "agent:printer-1") in host.events
    assert ("systemctl", "disable", install_fresh.CORE_UNIT) in host.events
    assert ("systemctl", "stop", install_fresh.CORE_UNIT) in host.events
    assert ("userdel", "stunsail-core") in host.events
    assert ("groupdel", "stunsail-agent") in host.events
    assert not host.opt.exists()
    assert not host.etc.exists()
    assert not host.data.exists()
    remaining = [
        name
        for current, _, files in os.walk(host.units, followlinks=False)
        for name in files
        if name.startswith("stunsail-")
    ]
    assert remaining == []
    assert report["backup"] == str(backup)
    assert report["freed"] == 1000


def test_uninstall_requires_root(host, tmp_path, monkeypatch):
    monkeypatch.setattr(full_uninstall.os, "geteuid", lambda: 1000)
    with pytest.raises(RuntimeError, match="Linux root"):
        full_uninstall.uninstall(tmp_path / "backup")
    assert host.etc.exists() and host.opt.exists()
    assert host.events == []


def test_uninstall_rejects_unexpected_loaded_agent(host, tmp_path):
    host.loaded.add("agent:rogue")
    with pytest.raises(RuntimeError, match="unexpected loaded Agent"):
        full_uninstall.uninstall(tmp_path / "backup")
    assert host.etc.exists() and host.data.exists()


def test_uninstall_aborts_if_backup_fails(host, tmp_path, monkeypatch):
    def fail(dest):
        raise RuntimeError("backup failed")

    monkeypatch.setattr(full_uninstall.maintenance_backup, "create", fail)
    with pytest.raises(RuntimeError, match="backup failed"):
        full_uninstall.uninstall(tmp_path / "backup")
    assert host.etc.exists() and host.opt.exists() and host.data.exists()
    assert (host.units / full_uninstall.FRONTEND_UNIT).exists()


def test_uninstall_without_frontend(host, tmp_path):
    (host.units / full_uninstall.FRONTEND_UNIT).unlink()
    full_uninstall.uninstall(tmp_path / "backup")
    assert ("systemctl", "disable", "--now", full_uninstall.FRONTEND_UNIT) not in host.events
    assert not host.etc.exists()


def test_uninstall_agent_only_skips_core(host, tmp_path, monkeypatch):
    (host.units / install_fresh.CORE_UNIT).unlink()
    host.accounts.discard("stunsail-core")
    host.groups.discard("stunsail-core")
    monkeypatch.setattr(
        full_uninstall.verify_backup,
        "verify",
        lambda dest: {"agents": ["printer-1"], "core": False},
    )
    full_uninstall.uninstall(tmp_path / "backup")
    assert ("systemctl", "disable", install_fresh.CORE_UNIT) not in host.events
    assert ("userdel", "stunsail-core") not in host.events
    assert ("userdel", "stunsail-agent") in host.events
    assert not host.data.exists()


def test_main_requires_confirm_flag(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        full_uninstall.main([str(tmp_path / "backup")])
    assert excinfo.value.code == 2


def test_main_prints_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        full_uninstall,
        "uninstall",
        lambda dest, backup=True: {
            "backup": str(dest) if backup else None,
            "free_before": 1000,
            "free_after": 2000,
            "freed": 1000,
        },
    )
    code = full_uninstall.main([str(tmp_path / "backup"), "--confirm-full-uninstall"])
    assert code == 0
    out = capsys.readouterr().out
    assert str(tmp_path / "backup") in out
    assert "1000" in out


def test_uninstall_no_backup_skips_backup(host, monkeypatch):
    monkeypatch.setattr(
        full_uninstall.maintenance_backup,
        "stop_services",
        lambda: {"agents": ["printer-1"], "core": True},
    )
    report = full_uninstall.uninstall(None, backup=False)
    assert not any(event[0] == "backup" for event in host.events)
    assert report["backup"] is None
    assert not host.opt.exists()
    assert not host.etc.exists()
    assert not host.data.exists()


def test_main_no_backup_flag(tmp_path, monkeypatch, capsys):
    captured = {}
    monkeypatch.setattr(
        full_uninstall,
        "uninstall",
        lambda dest, backup=True: (
            captured.update(dest=dest, backup=backup)
            or {"backup": None, "free_before": 1000, "free_after": 2000, "freed": 1000}
        ),
    )
    code = full_uninstall.main(["--no-backup", "--confirm-full-uninstall"])
    assert code == 0
    assert captured == {"dest": None, "backup": False}
    assert "No backup was created" in capsys.readouterr().out


def test_main_rejects_backup_destination_with_no_backup(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        full_uninstall.main([str(tmp_path / "backup"), "--no-backup", "--confirm-full-uninstall"])
    assert excinfo.value.code == 2


def test_main_requires_backup_destination_without_no_backup(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        full_uninstall.main(["--confirm-full-uninstall"])
    assert excinfo.value.code == 2
