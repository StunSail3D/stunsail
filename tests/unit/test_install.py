import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

INSTALLER = Path(__file__).resolve().parents[2] / "deployment" / "installer"
if os.name == "posix":
    sys.path.insert(0, str(INSTALLER))
    try:
        import install
        import preflight
    finally:
        sys.path.remove(str(INSTALLER))

pytestmark = pytest.mark.skipif(os.name != "posix", reason="requires POSIX installation tools")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(install.os, "geteuid", lambda: 0)
    calls = []
    monkeypatch.setattr(
        install.guided_install, "main", lambda argv: calls.append(("guided", argv)) or 0
    )
    monkeypatch.setattr(
        install.check_running, "main", lambda argv: calls.append(("check", argv)) or 0
    )
    monkeypatch.setattr(
        install.provision_tls, "main", lambda argv: calls.append(("provision", argv)) or 0
    )
    monkeypatch.setattr(
        install.maintenance_backup, "main", lambda argv: calls.append(("backup", argv)) or 0
    )
    monkeypatch.setattr(
        install.full_uninstall, "main", lambda argv: calls.append(("uninstall", argv)) or 0
    )
    monkeypatch.setattr(
        install.preflight, "run_checks", lambda path: [preflight.Check("disk space", True, "ok")]
    )
    monkeypatch.setattr(
        install.preflight, "check_core_port", lambda: preflight.Check("Core port", True, "ok")
    )
    source = tmp_path / "source"
    source.mkdir()
    return SimpleNamespace(calls=calls, source=source, monkeypatch=monkeypatch)


def _answers(env, *values):
    answers = iter(values)
    env.monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))


def _names(calls):
    return [name for name, _ in calls]


def test_menu_exit(env):
    _answers(env, "0")
    assert install.main([str(env.source)]) == 0
    assert env.calls == []


def test_invalid_option_then_exit(env):
    _answers(env, "9", "0")
    assert install.main([str(env.source)]) == 0
    assert env.calls == []


def test_install_standalone_runs_check_and_skips_tls(env, tmp_path):
    bundle = tmp_path / "bundle"
    _answers(env, "1", str(bundle), "n", "0")
    assert install.main([str(env.source)]) == 0
    assert _names(env.calls) == ["guided", "check"]
    guided_argv = dict(env.calls)["guided"]
    assert guided_argv[guided_argv.index("--mode") + 1] == "standalone"
    assert dict(env.calls)["check"] == ["--mode", "standalone"]


def test_install_agent_only_skips_tls_offer(env, tmp_path):
    bundle = tmp_path / "bundle"
    _answers(env, "2", str(bundle), "0")
    assert install.main([str(env.source)]) == 0
    assert _names(env.calls) == ["guided", "check"]
    guided_argv = dict(env.calls)["guided"]
    assert guided_argv[guided_argv.index("--mode") + 1] == "agent_only"
    assert dict(env.calls)["check"] == ["--mode", "agent-only"]


def test_install_with_tls_provisions(env, tmp_path):
    bundle = tmp_path / "bundle"
    _answers(env, "1", str(bundle), "y", "192.0.2.10", "0")
    env.monkeypatch.setattr(install.shutil, "which", lambda name: "/usr/local/bin/uv")
    env.monkeypatch.setattr(
        install.subprocess, "run", lambda command, **kw: SimpleNamespace(returncode=0)
    )
    assert install.main([str(env.source)]) == 0
    assert _names(env.calls) == ["guided", "check", "provision"]
    provision_argv = dict(env.calls)["provision"]
    assert provision_argv[provision_argv.index("--ip-address") + 1] == "192.0.2.10"
    assert "--confirm-provision-tls" in provision_argv


def test_install_requires_source(env):
    _answers(env, "1", "0")
    assert install.main([]) == 0
    assert env.calls == []


def test_preflight_hard_failure_aborts_install(env, tmp_path):
    env.monkeypatch.setattr(
        install.preflight,
        "run_checks",
        lambda path: [preflight.Check("architecture", False, "unsupported")],
    )
    _answers(env, "1", str(tmp_path / "bundle"), "0")
    assert install.main([str(env.source)]) == 0
    assert env.calls == []


def test_backup_confirmed(env, tmp_path):
    destination = tmp_path / "backup"
    _answers(env, "4", "BACKUP", str(destination), "0")
    assert install.main([]) == 0
    assert _names(env.calls) == ["backup"]
    assert dict(env.calls)["backup"] == [str(destination), "--confirm-stop-services"]


def test_backup_cancelled(env):
    _answers(env, "4", "", "0")
    assert install.main([]) == 0
    assert env.calls == []


def test_uninstall_confirmed(env, tmp_path):
    destination = tmp_path / "backup"
    _answers(env, "5", "UNINSTALL", "y", str(destination), str(tmp_path / "nobundle"))
    assert install.main([]) == 0
    assert _names(env.calls) == ["uninstall"]
    assert dict(env.calls)["uninstall"] == [str(destination), "--confirm-full-uninstall"]


def test_uninstall_cancelled(env):
    _answers(env, "5", "", "0")
    assert install.main([]) == 0
    assert env.calls == []


def test_uninstall_no_backup(env, tmp_path):
    _answers(env, "5", "UNINSTALL", "n", str(tmp_path / "nobundle"))
    assert install.main([]) == 0
    assert _names(env.calls) == ["uninstall"]
    assert dict(env.calls)["uninstall"] == ["--no-backup", "--confirm-full-uninstall"]


def test_uninstall_removes_bundle_and_exits(env, tmp_path):
    bundle = tmp_path / "stunsail-setup"
    bundle.mkdir()
    (bundle / "agent.yaml").write_text("{}")
    _answers(env, "5", "UNINSTALL", "n", str(bundle))
    assert install.main([]) == 0
    assert not bundle.exists()


def test_uninstall_failure_returns_to_menu(env, tmp_path):
    env.monkeypatch.setattr(install.full_uninstall, "main", lambda argv: 1)
    _answers(env, "5", "UNINSTALL", "n", "0")
    assert install.main([]) == 0
    assert _names(env.calls) == []


def test_install_certificate_option(env):
    generator_dir = env.source / "deployment" / "installer"
    generator_dir.mkdir(parents=True)
    (generator_dir / "generate_ca_and_cert.py").write_text("")
    _answers(env, "3", "192.0.2.10", "0")
    env.monkeypatch.setattr(install.shutil, "which", lambda name: "/usr/local/bin/uv")
    env.monkeypatch.setattr(
        install.subprocess, "run", lambda command, **kw: SimpleNamespace(returncode=0)
    )
    assert install.main([str(env.source)]) == 0
    assert _names(env.calls) == ["provision"]
    provision_argv = dict(env.calls)["provision"]
    assert provision_argv[provision_argv.index("--ip-address") + 1] == "192.0.2.10"


def test_install_certificate_missing_generator(env):
    _answers(env, "3", "0")
    assert install.main([str(env.source)]) == 0
    assert env.calls == []
