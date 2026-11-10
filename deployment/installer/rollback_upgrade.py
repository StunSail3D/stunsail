#!/usr/bin/env python3
"""Restore a pre-upgrade Core snapshot and matching release with services stopped."""

from __future__ import annotations

import argparse
import os
import pwd
import sqlite3
import subprocess
import sys
from pathlib import Path

import apply_restore
import apply_upgrade
import backup_installation
import install_fresh
import maintenance_backup
import rehearse_upgrade
import verify_backup
import verify_release


def rollback(source: Path, safety: Path) -> None:
    if os.name != "posix" or os.geteuid() != 0:
        raise RuntimeError("offline rollback requires Linux root")
    apply_restore._trusted_backup(source)
    original = verify_backup.verify(source)
    opt, data, etc = backup_installation.OPT, backup_installation.DATA, backup_installation.ETC
    if any(source.is_relative_to(path) for path in (opt, data, etc)):
        raise ValueError("pre-upgrade backup must be outside the installation")
    if safety.is_relative_to(source) or source.is_relative_to(safety):
        raise ValueError("pre-upgrade and safety backup paths must not overlap")
    for path in (opt, opt / "releases", data.parent):
        maintenance_backup._trusted_directory(path)
    old_release = Path(original["release_path"])
    if old_release.parent != (opt / "releases").resolve(strict=True):
        raise ValueError("backup release is not in the installer releases directory")
    maintenance_backup._trusted_directory(old_release)
    verify_release.verify(source, old_release)
    current_link = opt / "current"
    if not current_link.is_symlink():
        raise ValueError("current release must be an installer-managed symlink")
    current = current_link.resolve(strict=True)
    if current == old_release:
        raise ValueError("backup release is already active")
    for executable in ("python", "uvicorn", "stunsail-agent", "alembic"):
        path = old_release / ".venv" / "bin" / executable
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError(f"previous runtime is missing executable: {path}")
    names = [install_fresh.AGENT_UNIT]
    if original["core"]:
        names.append(install_fresh.CORE_UNIT)
    for name in names:
        installed = maintenance_backup._validate_template(name)
        previous = old_release / "deployment" / "systemd" / name
        if (
            previous.is_symlink()
            or not previous.is_file()
            or previous.read_bytes() != (installed.read_bytes())
        ):
            raise ValueError(f"previous release service unit differs from installed unit: {name}")
    core_new = data.with_name(data.name + ".rollback-core-new")
    core_previous = data.with_name(data.name + ".rollback-core-previous")
    smoke = data.with_name(data.name + ".rollback-rehearsal")
    agents = data.with_name(data.name + ".rollback-rehearsal-agents")
    next_link = opt / "current.rollback-new"
    for path in (core_new, core_previous, smoke, agents, next_link):
        install_fresh._absent(path)
    maintenance_backup.create(safety)
    current_backup = verify_backup.verify(safety)
    if (
        set(original["agents"]) != set(current_backup["agents"])
        or original["core"] != current_backup["core"]
        or current_backup["release_path"] != str(current)
    ):
        raise ValueError("current installation topology or release differs from backup")
    old_config = {k: v for k, v in original["files"].items() if k.startswith("config/")}
    current_config = {k: v for k, v in current_backup["files"].items() if k.startswith("config/")}
    if old_config != current_config:
        raise ValueError("configuration changed since the pre-upgrade backup")
    verify_release.verify(safety, current)
    verify_release.verify(source, old_release)
    _check_current(current_link, current)
    if original["core"]:
        backup_installation._directory(data)
        backup_installation._directory(data / "core")
        if data.stat().st_dev != data.parent.stat().st_dev:
            raise ValueError("Core data and its recovery directory must be on the same filesystem")
        user = pwd.getpwnam("stunsail-core")
        apply_restore._new_directory(core_new, 0o700, user.pw_uid, user.pw_gid)
        relative = "data/core/stunsail.db"
        apply_restore._copy(
            source / relative,
            core_new / "stunsail.db",
            original["files"][relative],
            0o600,
            user.pw_uid,
            user.pw_gid,
        )
        apply_restore._new_directory(smoke, 0o700, user.pw_uid, user.pw_gid)
        apply_restore._copy(
            source / relative,
            smoke / "stunsail.db",
            original["files"][relative],
            0o600,
            user.pw_uid,
            user.pw_gid,
        )
        rehearse_upgrade._smoke(old_release, smoke)
        apply_restore._sync_directory(core_new)
    rehearse_upgrade._agents(old_release, safety, current_backup, agents)
    apply_upgrade._check_services(current_backup)
    verify_release.verify(source, old_release)
    verify_release.verify(safety, current)
    _check_current(current_link, current)
    apply_upgrade._switch(
        current_link, current, old_release, next_link, data, core_new, core_previous, current_backup
    )


def _check_current(link: Path, expected: Path) -> None:
    if not link.is_symlink() or link.resolve(strict=True) != expected:
        raise RuntimeError("current release changed during rollback")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path, help="trusted private pre-upgrade format 3 backup")
    parser.add_argument("safety_backup", type=Path, help="new secure backup of current data")
    parser.add_argument("--confirm-rollback", action="store_true")
    parser.add_argument("--confirm-writers-stopped", action="store_true")
    parser.add_argument("--confirm-data-loss", action="store_true")
    args = parser.parse_args(argv)
    if not (args.confirm_rollback and args.confirm_writers_stopped and args.confirm_data_loss):
        parser.error("all three confirmation flags are required; newer Core changes will be lost")
    try:
        rollback(args.backup, args.safety_backup)
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        sqlite3.Error,
        subprocess.SubprocessError,
    ) as error:
        print(f"Offline rollback failed: {error}", file=sys.stderr)
        print(
            "Services may be stopped or disabled and data and release may be partially switched. "
            "Do not start services or retry blindly. Inspect both backups, current symlink and "
            "rollback recovery directories. Limited in-process Core recovery may have been "
            "attempted; it does not handle process termination or power loss.",
            file=sys.stderr,
        )
        return 1
    print(
        "Offline rollback applied; services remain stopped and disabled. Current data, "
        "release, safety backup and rehearsal copies were retained. Validate before starting."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
