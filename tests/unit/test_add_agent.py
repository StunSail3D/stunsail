import json
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
        import add_agent
        import configure
        import install_fresh
    finally:
        sys.path.remove(str(INSTALLER))

pytestmark = pytest.mark.skipif(os.name != "posix", reason="requires POSIX installation tools")


@pytest.fixture
def host(tmp_path, monkeypatch):
    root = tmp_path / "host"
    opt, etc, data, units = (root / name for name in ("opt", "etc", "data", "units"))
    for path in (opt / "releases" / "initial", etc / "agent", data / "agent", units):
        path.mkdir(parents=True)
    release = opt / "releases" / "initial"
    (opt / "current").symlink_to(release)
    executable = release / ".venv" / "bin" / "stunsail-agent"
    executable.parent.mkdir(parents=True)
    executable.write_text("test")
    executable.chmod(0o755)
    template = release / "deployment" / "systemd" / install_fresh.AGENT_UNIT
    template.parent.mkdir(parents=True)
    template.write_text("template")
    installed = units / install_fresh.AGENT_UNIT
    installed.write_text("template")
    first = data / "agent" / "first"
    first.mkdir()
    (first / "buffer.db").write_text("existing data")
    for name, value in (("OPT", opt), ("ETC", etc), ("DATA", data), ("UNITS", units)):
        monkeypatch.setattr(install_fresh, name, value)
    real_uid = os.geteuid()
    monkeypatch.setattr(install_fresh.os, "geteuid", lambda: 0)
    monkeypatch.setattr(install_fresh.os, "chown", lambda *args: None)
    monkeypatch.setattr(install_fresh.os, "fchown", lambda *args: None)
    monkeypatch.setattr(add_agent, "_trusted_directory", lambda path: None)
    monkeypatch.setattr(
        add_agent.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=42, pw_gid=43)
    )
    monkeypatch.setattr(add_agent.preflight, "check_systemd", lambda name: SimpleNamespace(ok=True))
    read_bundle = install_fresh._read_bundle

    def read_as_bundle_owner(path, **kwargs):
        with monkeypatch.context() as context:
            context.setattr(install_fresh.os, "geteuid", lambda: real_uid)
            return read_bundle(path, **kwargs)

    monkeypatch.setattr(install_fresh, "_read_bundle", read_as_bundle_owner)
    calls = []

    def run(command, **kwargs):
        calls.append(tuple(command))
        if command[0] == "systemd-escape":
            return subprocess.CompletedProcess(
                command, 0, stdout=r"stunsail-agent@printer\x2d1.service" + "\n"
            )
        if command[:2] == ["systemctl", "show"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=f"LoadState=loaded\nActiveState=inactive\nUnitFileState=disabled\nFragmentPath={installed}\n",
            )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(add_agent, "_unit_is_trusted", lambda path: None)
    return root, etc, data, installed, calls


def bundle(tmp_path, mode):
    core = "http://127.0.0.1:8000" if mode == "standalone" else "https://core.local"
    config, token, admin = configure.build_configuration(
        mode, "printer-1", "http://printer:7125", core, "test_token_123456789"
    )
    output = tmp_path / "bundle"
    configure.write_bundle(output, config, token, admin)
    return output


@pytest.mark.parametrize("mode", ["standalone", "agent_only"])
def test_add_agent_keeps_existing_buffers_and_uses_escaped_unit(host, tmp_path, mode):
    root, etc, data, _, calls = host
    add_agent.add(bundle(tmp_path, mode))
    assert (data / "agent" / "first" / "buffer.db").read_text() == "existing data"
    config = json.loads((etc / "agent" / "printer-1" / "agent.yaml").read_text())
    assert config["agent"]["agent_id"] == "printer-1"
    assert config["agent"]["local_buffer_url"].endswith("/agent/printer-1/buffer.db")
    assert (etc / "agent" / "printer-1" / "agent.env").stat().st_mode & 0o777 == 0o600
    assert (data / "agent" / "printer-1").stat().st_mode & 0o777 == 0o700
    assert [call[:2] for call in calls[-3:]] == [
        ("systemctl", "start"),
        ("systemctl", "is-active"),
        ("systemctl", "enable"),
    ]
    assert calls[-1][-1] == r"stunsail-agent@printer\x2d1.service"


def test_existing_agent_or_unit_is_never_overwritten(host, tmp_path):
    _, etc, data, installed, calls = host
    config = bundle(tmp_path, "standalone")
    (data / "agent" / "printer-1").mkdir()
    marker = data / "agent" / "printer-1" / "buffer.db"
    marker.write_text("retain")
    with pytest.raises(FileExistsError):
        add_agent.add(config)
    assert marker.read_text() == "retain"
    assert not calls
    marker.unlink()
    (data / "agent" / "printer-1").rmdir()
    installed.write_text("different")
    with pytest.raises(ValueError, match="does not match"):
        add_agent.add(config)
    assert not (etc / "agent" / "printer-1").exists()


def test_unregistered_agent_is_rejected(host, tmp_path):
    config, token, admin = configure.build_configuration(
        "standalone", "printer-1", "http://printer:7125", "http://127.0.0.1:8000", ""
    )
    directory = tmp_path / "bundle"
    configure.write_bundle(directory, config, token, admin)
    with pytest.raises(ValueError, match="registered Agent token"):
        add_agent.add(directory)
    assert not (host[1] / "agent" / "printer-1").exists()


@pytest.mark.parametrize(
    ("state", "unit_file"),
    [("active", "disabled"), ("inactive", "enabled"), ("activating", "disabled")],
)
def test_existing_active_or_enabled_unit_is_rejected(host, tmp_path, monkeypatch, state, unit_file):
    _, etc, data, installed, _ = host

    def run(command, **kwargs):
        if command[0] == "systemd-escape":
            return subprocess.CompletedProcess(
                command, 0, stdout="stunsail-agent@printer.service\n"
            )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                f"LoadState=loaded\nActiveState={state}\nUnitFileState={unit_file}\n"
                f"FragmentPath={installed}\n"
            ),
        )

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(RuntimeError, match="already active, enabled, or unexpected"):
        add_agent.add(bundle(tmp_path, "standalone"))
    assert not (etc / "agent" / "printer-1").exists()
    assert not (data / "agent" / "printer-1").exists()


def test_start_failure_leaves_partial_files_and_never_enables(host, tmp_path, monkeypatch):
    _, etc, data, installed, _ = host
    calls = []

    def run(command, **kwargs):
        calls.append(tuple(command))
        if command[0] == "systemd-escape":
            return subprocess.CompletedProcess(
                command, 0, stdout="stunsail-agent@printer.service\n"
            )
        if command[:2] == ["systemctl", "show"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    "LoadState=loaded\nActiveState=inactive\nUnitFileState=disabled\n"
                    f"FragmentPath={installed}\n"
                ),
            )
        if command[:2] == ["systemctl", "start"]:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        add_agent.add(bundle(tmp_path, "standalone"))
    assert (etc / "agent" / "printer-1" / "agent.env").exists()
    assert (data / "agent" / "printer-1").exists()
    assert not any(command[:2] == ("systemctl", "enable") for command in calls)
    assert (data / "agent" / "first" / "buffer.db").read_text() == "existing data"
