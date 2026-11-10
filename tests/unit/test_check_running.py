import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

INSTALLER = Path(__file__).resolve().parents[2] / "deployment" / "installer"
if os.name == "posix":
    sys.path.insert(0, str(INSTALLER))
    try:
        import backup_installation
        import check_running
        import install_fresh
        import maintenance_backup
    finally:
        sys.path.remove(str(INSTALLER))

pytestmark = pytest.mark.skipif(os.name != "posix", reason="requires POSIX installation tools")


@pytest.fixture(params=[True, False], ids=["standalone", "agent-only"])
def host(tmp_path, monkeypatch, request):
    etc, data = tmp_path / "etc", tmp_path / "data"
    for path in (etc / "agent" / "printer-1", data / "agent" / "printer-1"):
        path.mkdir(parents=True)
    if request.param:
        (etc / "core.env").write_text("private")
        (data / "core").mkdir()
    monkeypatch.setattr(backup_installation, "ETC", etc)
    monkeypatch.setattr(backup_installation, "DATA", data)
    monkeypatch.setattr(check_running.os, "geteuid", lambda: 0)
    monkeypatch.setattr(maintenance_backup, "_trusted_directory", lambda path: None)
    monkeypatch.setattr(maintenance_backup, "_loaded_agents", lambda: {"agent:printer-1"})
    monkeypatch.setattr(backup_installation, "_agent_unit", lambda agent: f"agent:{agent}")
    monkeypatch.setattr(maintenance_backup, "_validate_template", lambda unit: Path(unit))
    events = []
    monkeypatch.setattr(check_running, "_active", lambda unit, template: events.append(unit))
    monkeypatch.setattr(check_running, "_core", lambda: events.append("core HTTP"))
    return etc, data, events, request.param


def test_checks_expected_running_services(host):
    _, _, events, core = host
    assert check_running.check("standalone" if core else "agent-only") == (core, ["printer-1"])
    expected = ["agent:printer-1"]
    if core:
        expected = [install_fresh.CORE_UNIT, "core HTTP", install_fresh.CORE_UNIT, *expected]
    assert events == expected


def test_rejects_unexpected_or_missing_agents(host, monkeypatch):
    etc, data, events, _ = host
    monkeypatch.setattr(maintenance_backup, "_loaded_agents", lambda: {"unexpected.service"})
    with pytest.raises(RuntimeError, match="unexpected loaded Agent"):
        check_running.check("standalone" if host[3] else "agent-only")
    assert not events
    monkeypatch.setattr(maintenance_backup, "_loaded_agents", lambda: set())
    (data / "agent" / "printer-1").rename(data / "agent" / "other")
    with pytest.raises(ValueError, match="directories must match"):
        check_running.check("standalone" if host[3] else "agent-only")
    assert not events


def test_rejects_incomplete_core(host):
    etc, data, _, core = host
    if core:
        (data / "core").rmdir()
    else:
        (data / "core").mkdir()
    with pytest.raises(ValueError, match="Core configuration and data"):
        check_running.check("standalone" if core else "agent-only")


def test_rejects_unexpected_core_presence(host):
    _, _, _, core = host
    with pytest.raises(ValueError, match="does not match expected"):
        check_running.check("agent-only" if core else "standalone")


@pytest.mark.parametrize(
    "output, passes",
    [
        ("ActiveState=active\nSubState=running\n", True),
        ("ActiveState=active\nSubState=exited\n", False),
        ("ActiveState=activating\nSubState=auto-restart\n", False),
        ("ActiveState=active\n", False),
    ],
)
def test_active_requires_running_substate(monkeypatch, output, passes):
    calls = []
    monkeypatch.setattr(maintenance_backup, "_managed_unit", lambda unit, path: calls.append(unit))
    monkeypatch.setattr(
        check_running.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=output),
    )
    if passes:
        check_running._active("unit", Path("template"))
    else:
        with pytest.raises(RuntimeError, match="not active and running"):
            check_running._active("unit", Path("template"))
    assert calls == ["unit"]


def test_failure_is_reported_without_success(monkeypatch, capsys):
    def fail(mode):
        raise RuntimeError("service failed")

    monkeypatch.setattr(check_running, "check", fail)
    assert check_running.main(["--mode", "standalone"]) == 1
    captured = capsys.readouterr()
    assert "service failed" in captured.err
    assert not captured.out


def test_success_does_not_claim_connectivity(monkeypatch, capsys):
    monkeypatch.setattr(check_running, "check", lambda mode: (False, ["one"]))
    assert check_running.main(["--mode", "agent-only"]) == 0
    captured = capsys.readouterr()
    assert "No local Core was checked" in captured.out
    assert "synchronization and printer health were not checked" in captured.out


def test_cli_requires_explicit_mode(monkeypatch):
    monkeypatch.setattr(check_running, "check", lambda mode: pytest.fail("must not run"))
    with pytest.raises(SystemExit) as error:
        check_running.main([])
    assert error.value.code == 2
