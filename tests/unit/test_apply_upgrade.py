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
        import apply_upgrade
        import backup_installation
        import install_fresh
        import maintenance_backup
        import rehearse_upgrade
        import verify_backup
        import verify_release
    finally:
        sys.path.remove(str(INSTALLER))

pytestmark = pytest.mark.skipif(os.name != "posix", reason="requires POSIX installation tools")


@pytest.fixture(params=[True, False], ids=["standalone", "agent-only"])
def host(tmp_path, monkeypatch, request):
    root = tmp_path / "host"
    opt, data = root / "opt", root / "data"
    old, candidate = opt / "releases" / "old", opt / "releases" / "new"
    old.mkdir(parents=True)
    candidate.mkdir(parents=True)
    (old / "source").write_text("old")
    (candidate / "source").write_text("new")
    (opt / "current").symlink_to(old)
    data.mkdir()
    if request.param:
        (data / "core").mkdir()
        with sqlite3.connect(data / "core" / "stunsail.db") as db:
            db.execute("CREATE TABLE example (value TEXT)")
            db.execute("INSERT INTO example VALUES ('previous')")
    monkeypatch.setattr(backup_installation, "OPT", opt)
    monkeypatch.setattr(backup_installation, "DATA", data)
    monkeypatch.setattr(apply_upgrade.os, "geteuid", lambda: 0)
    monkeypatch.setattr(apply_upgrade.os, "chown", lambda *args: None)
    monkeypatch.setattr(
        apply_upgrade.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=42, pw_gid=43)
    )
    manifest = {"release_path": str(old), "core": request.param, "agents": ["printer-1"]}
    events = []

    def rehearse(path, backup):
        events.append(("rehearse", path, backup))
        if request.param:
            dest = data.with_name(data.name + ".upgrade-rehearsal")
            dest.mkdir()
            with sqlite3.connect(dest / "stunsail.db") as db:
                db.execute("CREATE TABLE example (value TEXT)")
                db.execute("INSERT INTO example VALUES ('migrated')")

    monkeypatch.setattr(rehearse_upgrade, "rehearse", rehearse)
    monkeypatch.setattr(verify_backup, "verify", lambda path: manifest)
    monkeypatch.setattr(verify_release, "verify", lambda path, release: None)
    monkeypatch.setattr(
        apply_upgrade, "_check_services", lambda manifest: events.append(("check",))
    )
    return root, old, candidate, tmp_path / "backup", events, request.param


def _value(path):
    with sqlite3.connect(path) as db:
        return db.execute("SELECT value FROM example").fetchone()[0]


def test_offline_upgrade_preserves_previous_data_and_release(host):
    root, old, candidate, backup, events, core = host
    if core:
        (root / "data" / "core" / "stunsail.db-wal").write_bytes(b"previous wal")
        (root / "data" / "core" / "stunsail.db-shm").write_bytes(b"previous shm")
    apply_upgrade.apply(candidate, backup)
    assert (root / "opt" / "current").resolve() == candidate
    assert old.is_dir()
    assert events == [("rehearse", candidate, backup), ("check",)]
    if core:
        data = root / "data"
        assert _value(data / "core" / "stunsail.db") == "migrated"
        assert (data / "core" / "stunsail.db").stat().st_mode & 0o777 == 0o600
        previous = root / "data.upgrade-core-previous"
        assert (previous / "stunsail.db-wal").read_bytes() == b"previous wal"
        assert (previous / "stunsail.db-shm").read_bytes() == b"previous shm"
        assert not (data / "core" / "stunsail.db-wal").exists()
    else:
        assert not (root / "data" / "core").exists()


def test_existing_recovery_path_prevents_rehearsal(host):
    root, old, candidate, backup, events, _ = host
    (root / "data.upgrade-core-previous").mkdir()
    with pytest.raises(FileExistsError):
        apply_upgrade.apply(candidate, backup)
    assert not events
    assert (root / "opt" / "current").resolve() == old


def test_rehearsal_failure_never_changes_active_release(host, monkeypatch):
    root, old, candidate, backup, _, _ = host

    def fail(*args):
        raise RuntimeError("rehearsal failed")

    monkeypatch.setattr(rehearse_upgrade, "rehearse", fail)
    with pytest.raises(RuntimeError, match="rehearsal failed"):
        apply_upgrade.apply(candidate, backup)
    assert (root / "opt" / "current").resolve() == old
    assert not (root / "data.upgrade-core-previous").exists()


def test_changed_candidate_or_service_failure_prevents_switch(host, monkeypatch):
    root, old, candidate, backup, events, _ = host
    original = rehearse_upgrade.rehearse

    def changed(*args):
        original(*args)
        (candidate / "source").write_text("changed")

    monkeypatch.setattr(rehearse_upgrade, "rehearse", changed)
    with pytest.raises(RuntimeError, match="candidate release changed"):
        apply_upgrade.apply(candidate, backup)
    assert (root / "opt" / "current").resolve() == old
    assert events[0][0] == "rehearse"


def test_service_failure_after_preparation_never_switches(host, monkeypatch):
    root, old, candidate, backup, _, _ = host

    def fail(manifest):
        raise RuntimeError("service active")

    monkeypatch.setattr(apply_upgrade, "_check_services", fail)
    with pytest.raises(RuntimeError, match="service active"):
        apply_upgrade.apply(candidate, backup)
    assert (root / "opt" / "current").resolve() == old
    assert not (root / "data.upgrade-core-previous").exists()


def test_failure_between_database_swaps_preserves_recovery_files(host, monkeypatch):
    root, old, candidate, backup, _, core = host
    if not core:
        pytest.skip("Agent-only hosts have no Core database swap")
    original = os.rename

    def rename(source, destination):
        if source == root / "data.upgrade-core-new":
            raise OSError("simulated rename failure")
        return original(source, destination)

    monkeypatch.setattr(apply_upgrade.os, "rename", rename)
    with pytest.raises(RuntimeError, match="original Core directory restored"):
        apply_upgrade.apply(candidate, backup)
    assert (root / "opt" / "current").resolve() == old
    assert _value(root / "data" / "core" / "stunsail.db") == "previous"
    assert not (root / "data.upgrade-core-previous").exists()
    assert _value(root / "data.upgrade-core-new" / "stunsail.db") == "migrated"


def test_link_switch_failure_preserves_previous_database(host, monkeypatch):
    root, old, candidate, backup, _, core = host
    if not core:
        pytest.skip("Agent-only hosts have no Core database swap")

    def fail(*args):
        raise OSError("simulated link failure")

    monkeypatch.setattr(apply_upgrade.os, "replace", fail)
    with pytest.raises(RuntimeError, match="original Core directory restored"):
        apply_upgrade.apply(candidate, backup)
    assert (root / "opt" / "current").resolve() == old
    assert _value(root / "data" / "core" / "stunsail.db") == "previous"
    assert _value(root / "data.upgrade-core-new" / "stunsail.db") == "migrated"
    assert (root / "opt" / "current.upgrade-new").resolve() == candidate


def test_recovery_refused_if_services_changed(host, monkeypatch):
    root, old, candidate, backup, _, core = host
    if not core:
        pytest.skip("Agent-only hosts have no Core database swap")
    checks = 0

    def check(_):
        nonlocal checks
        checks += 1
        if checks == 2:
            raise RuntimeError("service became active")

    def fail(*args):
        raise OSError("link switch failed")

    monkeypatch.setattr(apply_upgrade, "_check_services", check)
    monkeypatch.setattr(apply_upgrade.os, "replace", fail)
    with pytest.raises(RuntimeError, match="automatic Core recovery failed or was refused"):
        apply_upgrade.apply(candidate, backup)
    assert (root / "opt" / "current").resolve() == old
    assert _value(root / "data.upgrade-core-previous" / "stunsail.db") == "previous"
    assert _value(root / "data" / "core" / "stunsail.db") == "migrated"


def test_recovery_refused_after_release_switch(host, monkeypatch):
    root, _, candidate, backup, _, core = host
    if not core:
        pytest.skip("Agent-only hosts have no Core database swap")
    sync = apply_upgrade.apply_restore._sync_directory
    opt_syncs = 0

    def fail_after_switch(path):
        nonlocal opt_syncs
        if path == root / "opt":
            opt_syncs += 1
            if opt_syncs == 2:
                raise OSError("final sync failed")
        sync(path)

    monkeypatch.setattr(apply_upgrade.apply_restore, "_sync_directory", fail_after_switch)
    with pytest.raises(RuntimeError, match="release link changed; automatic recovery refused"):
        apply_upgrade.apply(candidate, backup)
    assert (root / "opt" / "current").resolve() == candidate
    assert _value(root / "data.upgrade-core-previous" / "stunsail.db") == "previous"
    assert _value(root / "data" / "core" / "stunsail.db") == "migrated"


def test_recovery_failure_preserves_remaining_paths(host, monkeypatch):
    root, old, candidate, backup, _, core = host
    if not core:
        pytest.skip("Agent-only hosts have no Core database swap")
    rename = os.rename

    def fail_recovery(source, destination):
        if source == root / "data.upgrade-core-previous":
            raise OSError("recovery rename failed")
        return rename(source, destination)

    def fail_switch(*args):
        raise OSError("link switch failed")

    monkeypatch.setattr(apply_upgrade.os, "rename", fail_recovery)
    monkeypatch.setattr(apply_upgrade.os, "replace", fail_switch)
    with pytest.raises(RuntimeError, match="recovery rename failed"):
        apply_upgrade.apply(candidate, backup)
    assert (root / "opt" / "current").resolve() == old
    assert _value(root / "data.upgrade-core-previous" / "stunsail.db") == "previous"
    assert _value(root / "data.upgrade-core-new" / "stunsail.db") == "migrated"
    assert not (root / "data" / "core").exists()


def test_recovery_refused_if_core_directory_was_replaced(host, monkeypatch):
    root, old, candidate, backup, _, core = host
    if not core:
        pytest.skip("Agent-only hosts have no Core database swap")
    rename = os.rename

    def replace_core_then_fail(*args):
        rename(root / "data" / "core", root / "unexpected-core")
        (root / "data" / "core").mkdir()
        raise OSError("link switch failed")

    monkeypatch.setattr(apply_upgrade.os, "replace", replace_core_then_fail)
    with pytest.raises(RuntimeError, match="Core paths changed; automatic recovery refused"):
        apply_upgrade.apply(candidate, backup)
    assert (root / "opt" / "current").resolve() == old
    assert _value(root / "data.upgrade-core-previous" / "stunsail.db") == "previous"
    assert _value(root / "unexpected-core" / "stunsail.db") == "migrated"
    assert (root / "data" / "core").is_dir()


def test_service_checks_validate_all_units(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(backup_installation, "_agent_unit", lambda agent: f"agent:{agent}")
    monkeypatch.setattr(maintenance_backup, "_loaded_agents", lambda: {"agent:a"})
    monkeypatch.setattr(backup_installation, "_no_active_agents", lambda: calls.append("active"))
    monkeypatch.setattr(maintenance_backup, "_validate_template", lambda unit: tmp_path / unit)
    monkeypatch.setattr(
        maintenance_backup, "_managed_unit", lambda unit, path: calls.append(("managed", unit))
    )
    monkeypatch.setattr(
        backup_installation, "_stopped", lambda unit: calls.append(("stopped", unit))
    )
    monkeypatch.setattr(apply_upgrade.remove_services, "_reject_remaining_links", lambda core: None)
    apply_upgrade._check_services({"agents": ["a", "b"], "core": True})
    for unit in ("agent:a", "agent:b", install_fresh.CORE_UNIT):
        assert ("managed", unit) in calls
        assert ("stopped", unit) in calls
    monkeypatch.setattr(maintenance_backup, "_loaded_agents", lambda: {"agent:unknown"})
    with pytest.raises(RuntimeError, match="unexpected loaded"):
        apply_upgrade._check_services({"agents": ["a"], "core": False})


def test_cli_requires_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr(apply_upgrade, "apply", lambda *args: pytest.fail("must not run"))
    for flags in ([], ["--confirm-upgrade"], ["--confirm-writers-stopped"]):
        with pytest.raises(SystemExit) as error:
            apply_upgrade.main([str(tmp_path / "candidate"), str(tmp_path / "backup"), *flags])
        assert error.value.code == 2
