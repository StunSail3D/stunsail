#!/usr/bin/env python3
"""Stop managed services and create a private installation backup."""

from __future__ import annotations

import argparse
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import add_agent
import backup_installation
import configure
import guided_install
import install_fresh
import preflight


def _managed_unit(unit: str, expected: Path) -> None:
    result = subprocess.run(
        ["systemctl", "show", unit, "--property=LoadState", "--property=FragmentPath"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if fields.get("LoadState") != "loaded" or fields.get("FragmentPath") != str(expected):
        raise ValueError(f"service does not use the expected installed unit: {unit}")


def _loaded_agents() -> set[str]:
    result = subprocess.run(
        [
            "systemctl",
            "list-units",
            "--all",
            "--type=service",
            "--no-legend",
            "--no-pager",
            "--plain",
            "stunsail-agent@*.service",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return {line.split()[0] for line in result.stdout.splitlines() if line.strip()}


def _trusted_directory(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError(f"expected root-owned non-writable directory: {path}")


def _validate_template(name: str) -> Path:
    opt = backup_installation.OPT
    for path in (opt, opt / "releases", install_fresh.UNITS):
        _trusted_directory(path)
    current = opt / "current"
    if not current.is_symlink():
        raise ValueError("current runtime must be an installer-managed symlink")
    release = current.resolve(strict=True)
    if release.parent != (opt / "releases").resolve(strict=True):
        raise ValueError("current release is outside the releases directory")
    installed = install_fresh.UNITS / name
    expected = release / "deployment" / "systemd" / name
    if (
        installed.is_symlink()
        or expected.is_symlink()
        or not installed.is_file()
        or not expected.is_file()
        or installed.read_bytes() != expected.read_bytes()
    ):
        raise ValueError(f"installed service unit does not match current release: {name}")
    add_agent._unit_is_trusted(installed)
    return installed


def create(destination: Path) -> None:
    if os.name != "posix" or os.geteuid() != 0:
        raise RuntimeError("maintenance backup requires Linux root")
    guided_install.validate_bundle_destination(destination)
    if any(
        destination.is_relative_to(path)
        for path in (backup_installation.ETC, backup_installation.DATA, backup_installation.OPT)
    ):
        raise ValueError("backup destination must be outside installation directories")
    check = preflight.check_systemd("systemctl")
    if not check.ok:
        raise RuntimeError(f"systemd manager unavailable: {check.detail}")

    etc = backup_installation.ETC
    data = backup_installation.DATA
    for path in (etc, etc / "agent", data, data / "agent"):
        _trusted_directory(path)
    config_ids = {
        item.name for item in (etc / "agent").iterdir() if item.is_dir() and not item.is_symlink()
    }
    data_ids = {
        item.name for item in (data / "agent").iterdir() if item.is_dir() and not item.is_symlink()
    }
    if (
        not config_ids
        or config_ids != data_ids
        or len(config_ids) != len(list((etc / "agent").iterdir()))
        or len(data_ids) != len(list((data / "agent").iterdir()))
        or any(
            not configure.IDENTIFIER.fullmatch(item) or item in {".", ".."} for item in config_ids
        )
    ):
        raise ValueError("Agent configuration and data directories must match")
    units = [backup_installation._agent_unit(agent) for agent in sorted(config_ids)]
    unexpected = _loaded_agents() - set(units)
    if unexpected:
        raise ValueError(f"unexpected loaded Agent services: {', '.join(sorted(unexpected))}")
    template = _validate_template(install_fresh.AGENT_UNIT)
    for unit in units:
        _managed_unit(unit, template)
    core_path = etc / "core.env"
    has_core = core_path.exists() or core_path.is_symlink()
    if has_core:
        core_template = _validate_template(install_fresh.CORE_UNIT)
        _managed_unit(install_fresh.CORE_UNIT, core_template)

    for unit in units:
        install_fresh._run("systemctl", "disable", unit)
    if has_core:
        install_fresh._run("systemctl", "disable", install_fresh.CORE_UNIT)
    for unit in units:
        install_fresh._run("systemctl", "stop", unit)
    if has_core:
        install_fresh._run("systemctl", "stop", install_fresh.CORE_UNIT)
    backup_installation.backup(destination)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "destination", type=Path, help="new directory in a secure root-owned parent"
    )
    parser.add_argument("--confirm-stop-services", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_stop_services:
        parser.error("--confirm-stop-services is required; services will be disabled and stopped")
    try:
        create(args.destination)
    except (OSError, ValueError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as error:
        print(f"Maintenance backup failed: {error}", file=sys.stderr)
        print(
            "Services may have been disabled or stopped. No automatic restart was attempted. "
            "Inspect service state and any partial backup before proceeding.",
            file=sys.stderr,
        )
        return 1
    print(
        f"Backup created at {args.destination}. Local StunSail services remain disabled and "
        "stopped; inspect and explicitly re-enable them when maintenance is complete."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
