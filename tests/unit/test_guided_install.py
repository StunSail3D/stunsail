import os
import sys
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[2] / "deployment" / "installer"
if os.name == "posix":
    sys.path.insert(0, str(INSTALLER))
    try:
        import guided_install
    finally:
        sys.path.remove(str(INSTALLER))

pytestmark = pytest.mark.skipif(os.name != "posix", reason="requires POSIX installation tools")


@pytest.mark.parametrize("confirmation", ["", "install", "no"])
def test_cancel_after_configuration_never_installs(tmp_path, monkeypatch, capsys, confirmation):
    bundle = tmp_path / "bundle"
    monkeypatch.setattr(guided_install.os, "geteuid", lambda: 0)
    monkeypatch.setattr(guided_install, "validate_bundle_destination", lambda path: None)
    responses = iter(["standalone", "printer-1", "http://localhost:7125", "", confirmation])
    monkeypatch.setattr("builtins.input", lambda prompt: next(responses))
    monkeypatch.setattr(guided_install.configure.getpass, "getpass", lambda prompt: "")
    calls = []
    monkeypatch.setattr(guided_install.install_fresh, "main", lambda args: calls.append(args))
    assert guided_install.main([str(tmp_path / "release"), str(bundle)]) == 1
    assert not calls
    assert (bundle / "core.env").is_file()
    assert "cancelled" in capsys.readouterr().out


def test_agent_only_confirmation_passes_bundle_and_propagates_error(tmp_path, monkeypatch, capsys):
    bundle = tmp_path / "bundle"
    source = tmp_path / "release"
    monkeypatch.setattr(guided_install.os, "geteuid", lambda: 0)
    monkeypatch.setattr(guided_install, "validate_bundle_destination", lambda path: None)
    responses = iter(
        ["agent_only", "printer-1", "http://printer:7125", "https://core.local", "", "INSTALL"]
    )
    monkeypatch.setattr("builtins.input", lambda prompt: next(responses))
    token = "agent_token_123456789"
    monkeypatch.setattr(guided_install.configure.getpass, "getpass", lambda prompt: token)
    calls = []
    monkeypatch.setattr(guided_install.install_fresh, "main", lambda args: calls.append(args) or 1)
    assert guided_install.main([str(source), str(bundle)]) == 1
    assert calls == [[str(source), str(bundle), "--confirm-fresh-install"]]
    assert token not in capsys.readouterr().out
    assert token in (bundle / "agent.env").read_text()


def test_standalone_confirmation_calls_shared_installer(tmp_path, monkeypatch, capsys):
    bundle = tmp_path / "bundle"
    source = tmp_path / "release"
    monkeypatch.setattr(guided_install.os, "geteuid", lambda: 0)
    monkeypatch.setattr(guided_install, "validate_bundle_destination", lambda path: None)
    responses = iter(["standalone", "printer-1", "http://printer:7125", "", "INSTALL"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(responses))
    monkeypatch.setattr(guided_install.configure.getpass, "getpass", lambda prompt: "")
    calls = []
    monkeypatch.setattr(guided_install.install_fresh, "main", lambda args: calls.append(args) or 0)
    assert guided_install.main([str(source), str(bundle)]) == 0
    assert calls == [[str(source), str(bundle), "--confirm-fresh-install"]]
    admin = (bundle / "core.env").read_text().split("STUNSAIL_ADMIN_TOKEN=")[1].strip()
    captured = capsys.readouterr()
    assert admin not in captured.out + captured.err


def test_bundle_path_checks_before_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(guided_install.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        guided_install.configure, "main", lambda args: pytest.fail("must not create bundle")
    )
    assert guided_install.main(["source", "relative"]) == 1
    existing = tmp_path / "existing"
    existing.mkdir()
    assert guided_install.main(["source", str(existing)]) == 1
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    assert guided_install.main(["source", str(link / "new")]) == 1


def test_configuration_failure_never_runs_installer(tmp_path, monkeypatch):
    monkeypatch.setattr(guided_install.os, "geteuid", lambda: 0)
    monkeypatch.setattr(guided_install, "validate_bundle_destination", lambda path: None)
    monkeypatch.setattr(guided_install.configure, "main", lambda args: 1)
    monkeypatch.setattr(
        guided_install.install_fresh, "main", lambda args: pytest.fail("must not install")
    )
    assert guided_install.main(["source", str(tmp_path / "bundle")]) == 1
