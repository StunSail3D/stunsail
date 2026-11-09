#!/usr/bin/env python3
"""Add a separately registered Agent to an existing StunSail installation."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import stat
import subprocess
import sys
from pathlib import Path

import install_fresh
import preflight


def _trusted_directory(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError(f"expected root-owned non-writable directory without symlinks: {path}")


def _unit_is_trusted(path: Path) -> None:
    info = path.stat()
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError("Agent unit must be root-owned and not group/world writable")


def add(bundle: Path) -> None:
    if os.name != "posix" or os.geteuid() != 0:
        raise RuntimeError("adding an Agent requires Linux root")
    config, agent_env, _ = install_fresh._read_bundle(bundle, additional_agent=True)
    agent = config["agent"]
    agent_id = agent["agent_id"]
    for path in (
        install_fresh.OPT,
        install_fresh.OPT / "releases",
        install_fresh.ETC,
        install_fresh.ETC / "agent",
        install_fresh.DATA,
        install_fresh.DATA / "agent",
    ):
        _trusted_directory(path)
    current = install_fresh.OPT / "current"
    if not current.is_symlink():
        raise ValueError("current runtime must be an installer-managed symlink")
    release = current.resolve(strict=True)
    if release.parent != (install_fresh.OPT / "releases").resolve(strict=True):
        raise ValueError("current runtime is outside the releases directory")
    executable = release / ".venv" / "bin" / "stunsail-agent"
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("current runtime is missing the Agent executable")
    installed_unit = install_fresh.UNITS / install_fresh.AGENT_UNIT
    expected_unit = release / "deployment" / "systemd" / install_fresh.AGENT_UNIT
    if (
        installed_unit.is_symlink()
        or expected_unit.is_symlink()
        or not installed_unit.is_file()
        or not expected_unit.is_file()
        or installed_unit.read_bytes() != expected_unit.read_bytes()
    ):
        raise ValueError("installed Agent unit does not match the current release")
    _unit_is_trusted(installed_unit)
    config_dir = install_fresh.ETC / "agent" / agent_id
    data_dir = install_fresh.DATA / "agent" / agent_id
    install_fresh._absent(config_dir)
    install_fresh._absent(data_dir)
    ca_content = install_fresh._read_ca(agent)
    user = pwd.getpwnam("stunsail-agent")
    check = preflight.check_systemd("systemctl")
    if not check.ok:
        raise RuntimeError(f"systemd manager unavailable: {check.detail}")
    unit = subprocess.run(
        ["systemd-escape", "--template=stunsail-agent@.service", "--", agent_id],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    state = subprocess.run(
        [
            "systemctl",
            "show",
            unit,
            "--property=LoadState",
            "--property=ActiveState",
            "--property=UnitFileState",
            "--property=FragmentPath",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    fields = dict(line.split("=", 1) for line in state if "=" in line)
    if (
        fields.get("LoadState") != "loaded"
        or fields.get("ActiveState") not in {"inactive", "failed"}
        or fields.get("UnitFileState") != "disabled"
        or fields.get("FragmentPath") != str(installed_unit)
    ):
        raise RuntimeError(f"Agent unit already active, enabled, or unexpected: {unit}")
    config_dir.mkdir(mode=0o711)
    config_dir.chmod(0o711)
    data_dir.mkdir(mode=0o700)
    data_dir.chmod(0o700)
    os.chown(data_dir, user.pw_uid, user.pw_gid)
    if ca_content is not None:
        install_fresh._write(config_dir / "ca.pem", ca_content, 0o644)
        agent["core_ca_file"] = str(config_dir / "ca.pem")
    install_fresh._write(
        config_dir / "agent.yaml", json.dumps(config, indent=2) + "\n", 0o440, 0, user.pw_gid
    )
    install_fresh._write(config_dir / "agent.env", agent_env, 0o600)
    install_fresh._run("systemctl", "start", unit)
    install_fresh._run("systemctl", "is-active", "--quiet", unit)
    install_fresh._run("systemctl", "enable", unit)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="root-owned private registered Agent bundle")
    parser.add_argument("--confirm-add-agent", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_add_agent:
        parser.error("--confirm-add-agent is required; this starts and enables a service")
    try:
        add(args.bundle)
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as error:
        print(f"Adding Agent failed: {error}", file=sys.stderr)
        print(
            "The new Agent may be partially installed or running. Inspect its service, "
            "configuration and data before retrying; do not remove other Agent data.",
            file=sys.stderr,
        )
        return 1
    print("Agent started. Register its printer and verify Moonraker connectivity and Core sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
