import importlib.util
import json
import os
from pathlib import Path

import pytest

from stunsail_agent.config import load_config

path = Path(__file__).resolve().parents[2] / "deployment" / "installer" / "configure.py"
spec = importlib.util.spec_from_file_location("stunsail_configure", path)
assert spec and spec.loader
configure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)


def test_agent_only_bundle_is_valid_runtime_configuration(tmp_path, monkeypatch):
    settings, token, admin = configure.build_configuration(
        "agent_only",
        "printer-1",
        "http://localhost:7125",
        "https://core.local:8443",
        "test_token_123456789",
        "/etc/stunsail/ca.pem",
    )
    output = tmp_path / "bundle"
    configure.write_bundle(output, settings, token, admin)
    monkeypatch.setenv("STUNSAIL_AGENT_TOKEN", token)
    config = load_config(output / "agent.yaml")
    assert config.agent_id == "printer-1"
    assert config.buffer_path == "/var/lib/stunsail/agent/printer-1/buffer.db"
    assert config.core_url == "https://core.local:8443/api/v1"
    assert config.core_ca_file == "/etc/stunsail/ca.pem"
    assert config.core_token == token
    assert not (output / "core.env").exists()
    assert token not in (output / "agent.yaml").read_text(encoding="utf-8")
    if os.name == "posix":
        assert output.stat().st_mode & 0o777 == 0o700
        assert (output / "agent.env").stat().st_mode & 0o777 == 0o600


def test_standalone_can_be_prepared_before_registration(tmp_path, monkeypatch):
    settings, token, admin = configure.build_configuration(
        "standalone", "printer", "http://localhost:7125", "http://127.0.0.1:8000", ""
    )
    output = tmp_path / "new"
    configure.write_bundle(output, settings, token, admin)
    monkeypatch.delenv("STUNSAIL_AGENT_TOKEN", raising=False)
    config = load_config(output / "agent.yaml")
    assert config.core_token is None
    assert config.core_url == "http://127.0.0.1:8000/api/v1"
    assert admin and len(admin) >= 16
    assert f"STUNSAIL_ADMIN_TOKEN={admin}" in (output / "core.env").read_text()
    assert (output / "agent.env").read_text() == "STUNSAIL_AGENT_TOKEN=\n"


@pytest.mark.parametrize(
    ("mode", "agent", "moonraker", "core", "token", "ca"),
    [
        ("bad", "a", "http://host", "https://core", "safe_token_123456", None),
        ("agent_only", "../x", "http://host", "https://core", "safe_token_123456", None),
        ("agent_only", "..", "http://host", "https://core", "safe_token_123456", None),
        ("agent_only", "a", "http://host", "http://core", "safe_token_123456", None),
        ("agent_only", "a", "http://user:pass@host", "https://core", "safe_token_123456", None),
        ("agent_only", "a", "http://host", "https://core", "bad\nx", None),
        ("agent_only", "a", "http://host", "https://core", "", None),
        ("agent_only", "a", "http://host", "https://core", "safe_token_123456", "../ca"),
        ("standalone", "a", "http://host", "http://other", "", None),
    ],
)
def test_rejects_invalid_or_unsafe_inputs(mode, agent, moonraker, core, token, ca):
    with pytest.raises(ValueError):
        configure.build_configuration(mode, agent, moonraker, core, token, ca)


def test_existing_bundle_is_never_overwritten(tmp_path):
    output = tmp_path / "bundle"
    output.mkdir()
    existing = output / "agent.yaml"
    existing.write_text("existing", encoding="utf-8")
    config, token, admin = configure.build_configuration(
        "standalone", "a", "http://host", "http://127.0.0.1:8000", ""
    )
    with pytest.raises(FileExistsError):
        configure.write_bundle(output, config, token, admin)
    assert existing.read_text(encoding="utf-8") == "existing"
    assert sorted(p.name for p in output.iterdir()) == ["agent.yaml"]


def test_bundle_contains_no_json_secret_values_in_other_files(tmp_path):
    config, token, admin = configure.build_configuration(
        "standalone", "a", "http://host", "http://127.0.0.1:8000", "test_token_123456"
    )
    output = tmp_path / "bundle"
    configure.write_bundle(output, config, token, admin)
    raw = (output / "agent.yaml").read_text(encoding="utf-8")
    assert json.loads(raw)["agent"]["agent_id"] == "a"
    assert token not in raw and admin not in raw


def test_interactive_configuration_does_not_print_secrets(tmp_path, monkeypatch, capsys):
    responses = iter(["standalone", "my-printer", "http://127.0.0.1:7125", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))
    monkeypatch.setattr(configure.getpass, "getpass", lambda _prompt: "")
    output = tmp_path / "bundle"
    assert configure.main([str(output)]) == 0
    printed = capsys.readouterr()
    admin = (output / "core.env").read_text().split("STUNSAIL_ADMIN_TOKEN=")[1].strip()
    assert admin not in printed.out + printed.err
    assert "register this Agent" in printed.out


def test_interactive_configuration_failure_does_not_create_directory(tmp_path, monkeypatch, capsys):
    responses = iter(["agent_only", "my-printer", "http://printer", "http://core", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))
    monkeypatch.setattr(configure.getpass, "getpass", lambda _prompt: "test_token_123456")
    output = tmp_path / "bundle"
    assert configure.main([str(output)]) == 1
    assert not output.exists()
    assert "failed" in capsys.readouterr().err
