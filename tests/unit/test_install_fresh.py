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
        import configure
        import install_fresh
    finally:
        sys.path.remove(str(INSTALLER))

pytestmark = pytest.mark.skipif(os.name != "posix", reason="requires POSIX installation tools")


def test_bundle_validation_rejects_modified_paths_and_nonempty_standalone_token(tmp_path):
    config, token, admin = configure.build_configuration(
        "standalone", "printer-1", "http://localhost:7125", "http://127.0.0.1:8000", ""
    )
    bundle = tmp_path / "bundle"
    configure.write_bundle(bundle, config, token, admin)
    validated, _, _ = install_fresh._read_bundle(bundle)
    assert validated == config
    config["agent"]["local_buffer_url"] = "sqlite:////other/path.db"
    (bundle / "agent.yaml").write_text(json.dumps(config))
    with pytest.raises(ValueError, match="unmodified"):
        install_fresh._read_bundle(bundle)
    config["agent"]["local_buffer_url"] = "sqlite:////var/lib/stunsail/agent/printer-1/buffer.db"
    (bundle / "agent.yaml").write_text(json.dumps(config))
    (bundle / "agent.env").write_text("STUNSAIL_AGENT_TOKEN=token_123456789012345\n")
    with pytest.raises(ValueError, match="empty Agent token"):
        install_fresh._read_bundle(bundle)
    (bundle / "agent.env").write_text("STUNSAIL_AGENT_TOKEN=\n")
    (bundle / ".agent.env.pending").write_text("keep")
    with pytest.raises(FileExistsError):
        install_fresh._read_bundle(bundle)


@pytest.mark.parametrize(
    ("disk", "confirmed", "other_failure", "message"),
    [
        ("low", False, False, "low-space confirmation"),
        ("low", True, False, "required command not found"),
        ("low", True, True, "unsupported OS"),
        ("insufficient", True, False, "insufficient installation reserve"),
    ],
)
def test_fresh_install_low_disk_confirmation_is_limited(
    isolated_host, monkeypatch, disk, confirmed, other_failure, message
):
    root, source, actions = isolated_host
    config, token, _ = configure.build_configuration(
        "agent_only",
        "printer-1",
        "http://localhost:7125",
        "https://core.local",
        "token_123456789012345",
    )
    monkeypatch.setattr(
        install_fresh, "_read_bundle", lambda _: (config, f"STUNSAIL_AGENT_TOKEN={token}\n", None)
    )
    detail = "low-space confirmation" if disk == "low" else "insufficient installation reserve"
    checks = [
        install_fresh.preflight.Check("disk space", False, detail, disk == "low"),
    ]
    if other_failure:
        checks.append(install_fresh.preflight.Check("operating system", False, "unsupported OS"))
    monkeypatch.setattr(install_fresh.preflight, "run_checks", lambda _: checks)
    monkeypatch.setattr(install_fresh.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match=message):
        install_fresh.install(source, root, confirm_low_disk_space=confirmed)
    assert actions == []


def test_cli_passes_low_space_confirmation(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        install_fresh, "install", lambda source, bundle, **kwargs: calls.append(kwargs)
    )
    assert (
        install_fresh.main(
            [str(tmp_path), str(tmp_path), "--confirm-fresh-install", "--confirm-low-disk-space"]
        )
        == 0
    )
    assert calls == [{"confirm_low_disk_space": True, "confirm_experimental_platform": False}]


@pytest.mark.parametrize(
    ("low", "platform", "confirmed", "message"),
    [
        (True, False, False, "operating system"),
        (False, True, False, "disk space"),
        (True, True, False, "required command not found"),
        (True, True, True, "architecture"),
    ],
)
def test_platform_confirmation_never_bypasses_other_checks(
    isolated_host, monkeypatch, low, platform, confirmed, message
):
    root, source, actions = isolated_host
    config = {"deployment_mode": "agent_only", "agent": {"agent_id": "printer-1"}}
    monkeypatch.setattr(install_fresh, "_read_bundle", lambda _: (config, "", None))
    checks = [
        install_fresh.preflight.Check("disk space", False, "low disk", True),
        install_fresh.preflight.Check("operating system", False, "experimental", True),
    ]
    if confirmed:
        checks.append(install_fresh.preflight.Check("architecture", False, "unsupported"))
    monkeypatch.setattr(install_fresh.preflight, "run_checks", lambda _: checks)
    monkeypatch.setattr(install_fresh.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match=message):
        install_fresh.install(
            source, root, confirm_low_disk_space=low, confirm_experimental_platform=platform
        )
    assert not actions


@pytest.fixture
def isolated_host(tmp_path, monkeypatch):
    root = tmp_path / "host"
    root.mkdir()
    units = root / "units"
    units.mkdir()
    source = tmp_path / "release"
    unit_source = source / "deployment" / "systemd"
    unit_source.mkdir(parents=True)
    for name in (install_fresh.CORE_UNIT, install_fresh.AGENT_UNIT):
        (unit_source / name).write_text("[Service]\nExecStart=/bin/true\n")
    for name, path in (
        ("OPT", root / "opt"),
        ("ETC", root / "etc"),
        ("DATA", root / "data"),
        ("UNITS", units),
    ):
        monkeypatch.setattr(install_fresh, name, path)
    monkeypatch.setattr(install_fresh.os, "geteuid", lambda: 0)
    monkeypatch.setattr(install_fresh.os, "chown", lambda *args: None)
    monkeypatch.setattr(install_fresh.os, "fchown", lambda *args: None)
    monkeypatch.setattr(install_fresh.preflight, "run_checks", lambda *args: [])
    monkeypatch.setattr(
        install_fresh.preflight,
        "check_core_port",
        lambda: SimpleNamespace(name="port", ok=True, detail="available"),
    )
    monkeypatch.setattr(install_fresh.shutil, "which", lambda name: name)
    monkeypatch.setattr(install_fresh.prepare_runtime, "validate_source", lambda path: path)
    monkeypatch.setattr(install_fresh, "_account_absent", lambda name: None)
    monkeypatch.setattr(
        install_fresh.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=42, pw_gid=43)
    )
    actions = []

    def run(command, **kwargs):
        actions.append(tuple(command))
        if command[:2] == ["systemctl", "show"]:
            return subprocess.CompletedProcess(command, 0, stdout="not-found\n")
        if command[0] == "systemd-escape":
            return subprocess.CompletedProcess(
                command, 0, stdout=r"stunsail-agent@printer\x2d1.service" + "\n"
            )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(install_fresh.subprocess, "run", run)

    def prepare(source, destination):
        destination.mkdir()
        actions.append(("prepare", str(destination)))

    monkeypatch.setattr(install_fresh.prepare_runtime, "prepare", prepare)
    monkeypatch.setattr(install_fresh, "_ready", lambda: actions.append(("ready",)))
    return root, source, actions


def test_standalone_initial_install_orders_registration_and_service_start(
    isolated_host, tmp_path, monkeypatch
):
    root, source, actions = isolated_host
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    config, _, admin = configure.build_configuration(
        "standalone", "printer-1", "http://localhost:7125", "http://127.0.0.1:8000", ""
    )
    core_env = (
        "STUNSAIL_DATABASE_URL=sqlite:////var/lib/stunsail/core/stunsail.db\n"
        "STUNSAIL_WEB_DIR=/opt/stunsail/current/apps/web/dist\n"
        f"STUNSAIL_ADMIN_TOKEN={admin}\n"
    )
    monkeypatch.setattr(
        install_fresh,
        "_read_bundle",
        lambda _: (config, "STUNSAIL_AGENT_TOKEN=\n", core_env),
    )

    def register(_):
        actions.append(("register",))

    monkeypatch.setattr(install_fresh.register_local_agent, "register", register)
    monkeypatch.setattr(
        install_fresh.register_local_agent,
        "read_private",
        lambda _: ("STUNSAIL_AGENT_TOKEN=token_123456789012345\n", None),
    )
    install_fresh.install(source, bundle)
    agent_dir = root / "etc" / "agent" / "printer-1"
    assert (agent_dir / "agent.env").read_text() == "STUNSAIL_AGENT_TOKEN=token_123456789012345\n"
    assert (agent_dir / "agent.env").stat().st_mode & 0o777 == 0o600
    assert (agent_dir / "agent.yaml").stat().st_mode & 0o777 == 0o440
    assert (root / "etc" / "core.env").stat().st_mode & 0o777 == 0o600
    assert (root / "opt" / "current").is_symlink()
    start_core = actions.index(("systemctl", "start", install_fresh.CORE_UNIT))
    registration = actions.index(("register",))
    agent_start = next(
        i
        for i, action in enumerate(actions)
        if action[:2] == ("systemctl", "start") and action[-1] != install_fresh.CORE_UNIT
    )
    assert start_core < actions.index(("ready",)) < registration < agent_start
    assert actions[-1][0:2] == ("systemctl", "enable")


def test_conflicting_path_is_rejected_before_accounts_or_services(isolated_host, monkeypatch):
    root, source, actions = isolated_host
    config, token, _ = configure.build_configuration(
        "agent_only",
        "printer-1",
        "http://localhost:7125",
        "https://core.local",
        "token_123456789012345",
    )
    monkeypatch.setattr(
        install_fresh, "_read_bundle", lambda _: (config, f"STUNSAIL_AGENT_TOKEN={token}\n", None)
    )
    (root / "data").mkdir()
    marker = root / "data" / "existing"
    marker.write_text("untouched")
    with pytest.raises(FileExistsError):
        install_fresh.install(source, root)
    assert marker.read_text() == "untouched"
    assert not actions


@pytest.mark.parametrize("low_space", [False, True])
def test_agent_only_does_not_create_core_or_register_locally(isolated_host, monkeypatch, low_space):
    root, source, actions = isolated_host
    config, token, _ = configure.build_configuration(
        "agent_only",
        "printer-1",
        "http://localhost:7125",
        "https://core.local",
        "token_123456789012345",
    )
    monkeypatch.setattr(
        install_fresh, "_read_bundle", lambda _: (config, f"STUNSAIL_AGENT_TOKEN={token}\n", None)
    )
    if low_space:
        monkeypatch.setattr(
            install_fresh.preflight,
            "run_checks",
            lambda _: [install_fresh.preflight.Check("disk space", False, "428 MiB free", True)],
        )
    install_fresh.install(source, root, confirm_low_disk_space=low_space)
    assert not (root / "etc" / "core.env").exists()
    assert not (root / "data" / "core").exists()
    assert not (root / "units" / install_fresh.CORE_UNIT).exists()
    assert ("register",) not in actions
    assert not any(
        action[:2] == ("systemctl", "start") and action[-1] == install_fresh.CORE_UNIT
        for action in actions
    )
    assert actions[-1][:2] == ("systemctl", "enable")


def test_core_readiness_failure_does_not_start_or_enable_agent(isolated_host, monkeypatch):
    root, source, actions = isolated_host
    config, _, _ = configure.build_configuration(
        "standalone", "printer-1", "http://localhost:7125", "http://127.0.0.1:8000", ""
    )
    monkeypatch.setattr(
        install_fresh, "_read_bundle", lambda _: (config, "STUNSAIL_AGENT_TOKEN=\n", "core")
    )

    def fail():
        raise RuntimeError("Core did not become ready")

    monkeypatch.setattr(install_fresh, "_ready", fail)
    with pytest.raises(RuntimeError, match="Core did not become ready"):
        install_fresh.install(source, root)
    assert (root / "etc" / "core.env").exists()
    assert not (root / "etc" / "agent" / "printer-1" / "agent.env").exists()
    assert not any(action[:2] == ("systemctl", "enable") for action in actions)
    assert not any(
        action[:2] == ("systemctl", "start") and action[-1] != install_fresh.CORE_UNIT
        for action in actions
    )


def test_existing_systemd_unit_is_not_replaced(isolated_host, monkeypatch):
    root, source, actions = isolated_host
    config, token, _ = configure.build_configuration(
        "agent_only",
        "printer-1",
        "http://localhost:7125",
        "https://core.local",
        "token_123456789012345",
    )
    monkeypatch.setattr(
        install_fresh, "_read_bundle", lambda _: (config, f"STUNSAIL_AGENT_TOKEN={token}\n", None)
    )
    unit = root / "units" / install_fresh.AGENT_UNIT
    unit.write_text("existing")
    with pytest.raises(FileExistsError):
        install_fresh.install(source, root)
    assert unit.read_text() == "existing"
    assert not actions


def test_invalid_release_is_rejected_before_creating_accounts(isolated_host, monkeypatch):
    root, source, actions = isolated_host
    config, token, _ = configure.build_configuration(
        "agent_only",
        "printer-1",
        "http://localhost:7125",
        "https://core.local",
        "token_123456789012345",
    )
    monkeypatch.setattr(
        install_fresh, "_read_bundle", lambda _: (config, f"STUNSAIL_AGENT_TOKEN={token}\n", None)
    )

    def invalid(_):
        raise ValueError("invalid release")

    monkeypatch.setattr(install_fresh.prepare_runtime, "validate_source", invalid)
    with pytest.raises(ValueError, match="invalid release"):
        install_fresh.install(source, root)
    assert not (root / "opt").exists()
    assert not any(action[0] in ("groupadd", "useradd") for action in actions)


def test_ca_bundle_with_private_key_is_never_copied(isolated_host, tmp_path, monkeypatch):
    root, source, actions = isolated_host
    ca = tmp_path / "ca.pem"
    ca.write_text("-----BEGIN PRIVATE KEY-----\nnot-a-real-key\n-----END PRIVATE KEY-----\n")
    config, token, _ = configure.build_configuration(
        "agent_only",
        "printer-1",
        "http://localhost:7125",
        "https://core.local",
        "token_123456789012345",
        str(ca),
    )
    monkeypatch.setattr(
        install_fresh, "_read_bundle", lambda _: (config, f"STUNSAIL_AGENT_TOKEN={token}\n", None)
    )
    with pytest.raises(ValueError, match="must not contain a private key"):
        install_fresh.install(source, root)
    assert not (root / "etc").exists()
    assert not any(action[0] in ("groupadd", "useradd") for action in actions)
