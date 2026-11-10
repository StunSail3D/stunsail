#!/usr/bin/env python3
"""Apply a verified backup offline, retaining the existing installation directories."""

from __future__ import annotations

import argparse
import os
import pwd
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import backup_installation
import install_fresh
import maintenance_backup
import remove_services
import verify_backup
import verify_release


def _trusted_backup(path: Path) -> None:
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError("backup path must be absolute and contain no symlinks or '..'")
    for ancestor in (path.parent, *path.parent.parents):
        maintenance_backup._trusted_directory(ancestor)
    for current, dirs, files in os.walk(
        path, followlinks=False, onerror=remove_services._walk_error
    ):
        directory = Path(current)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError(f"backup directory must be root-owned and private: {directory}")
        for name in dirs + files:
            item = directory / name
            info = item.lstat()
            if info.st_uid != 0 or info.st_mode & 0o077:
                raise ValueError(f"backup item must be root-owned and private: {item}")
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise ValueError(f"backup contains a non-regular item: {item}")


def _new_directory(path: Path, mode: int, uid: int = 0, gid: int = 0) -> None:
    path.mkdir(mode=0o700)
    os.chmod(path, mode)
    os.chown(path, uid, gid)


def _copy(source: Path, target: Path, expected: str, mode: int, uid: int = 0, gid: int = 0) -> None:
    backup_installation._private_copy(source, target)
    if verify_backup.digest(target) != expected:
        raise ValueError(f"restored file does not match backup: {target}")
    os.chown(target, uid, gid)
    os.chmod(target, mode)


def _paths(path: Path) -> tuple[Path, Path]:
    return path.with_name(path.name + ".restore-new"), path.with_name(
        path.name + ".restore-previous"
    )


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _sync_tree(path: Path) -> None:
    for current, _, _ in os.walk(
        path, topdown=False, followlinks=False, onerror=remove_services._walk_error
    ):
        _sync_directory(Path(current))


def apply(source: Path, safety_backup: Path) -> None:
    if os.name != "posix" or os.geteuid() != 0:
        raise RuntimeError("restore requires Linux root")
    _trusted_backup(source)
    manifest = verify_backup.verify(source)
    etc, data, opt = backup_installation.ETC, backup_installation.DATA, backup_installation.OPT
    for path in (etc.parent, data.parent):
        maintenance_backup._trusted_directory(path)
    if any(source.is_relative_to(path) for path in (etc, data, opt)):
        raise ValueError("restore backup must be outside installation directories")
    if (
        safety_backup.is_relative_to(source)
        or source.is_relative_to(safety_backup)
        or safety_backup == source
    ):
        raise ValueError("restore and safety backup paths must not overlap")
    release = (opt / "current").resolve(strict=True)
    verify_release.verify(source, release)
    etc_new, etc_old = _paths(etc)
    data_new, data_old = _paths(data)
    for path in (etc_new, etc_old, data_new, data_old):
        install_fresh._absent(path)
    agent_user = pwd.getpwnam("stunsail-agent")
    core_user = pwd.getpwnam("stunsail-core") if manifest["core"] else None

    maintenance_backup.create(safety_backup)
    current = verify_backup.verify(safety_backup)
    if set(current["agents"]) != set(manifest["agents"]) or current["core"] != manifest["core"]:
        raise ValueError("backup topology does not match the current installation")
    if current["release_path"] != str(release):
        raise ValueError("current release changed during safety backup")
    verify_release.verify(safety_backup, release)
    verify_release.verify(source, release)
    _trusted_backup(source)

    _new_directory(etc_new, 0o700)
    _new_directory(data_new, 0o700)
    _new_directory(etc_new / "agent", 0o755)
    _new_directory(data_new / "agent", 0o755)
    files = manifest["files"]
    if core_user is not None:
        _new_directory(data_new / "core", 0o700, core_user.pw_uid, core_user.pw_gid)
        for relative, target, uid, gid in (
            ("config/core.env", etc_new / "core.env", 0, 0),
            (
                "data/core/stunsail.db",
                data_new / "core" / "stunsail.db",
                core_user.pw_uid,
                core_user.pw_gid,
            ),
        ):
            _copy(source / relative, target, files[relative], 0o600, uid, gid)
    for agent in manifest["agents"]:
        config = etc_new / "agent" / agent
        buffer = data_new / "agent" / agent
        _new_directory(config, 0o711)
        _new_directory(buffer, 0o700, agent_user.pw_uid, agent_user.pw_gid)
        for name, mode, uid, gid in (
            ("agent.yaml", 0o440, 0, agent_user.pw_gid),
            ("agent.env", 0o600, 0, 0),
            ("ca.pem", 0o644, 0, 0),
        ):
            relative = f"config/agent/{agent}/{name}"
            if relative in files:
                _copy(source / relative, config / name, files[relative], mode, uid, gid)
        relative = f"data/agent/{agent}/buffer.db"
        _copy(
            source / relative,
            buffer / "buffer.db",
            files[relative],
            0o600,
            agent_user.pw_uid,
            agent_user.pw_gid,
        )
    verify_release.verify(source, release)
    if (opt / "current").resolve(strict=True) != release:
        raise RuntimeError("current release changed during restore")
    units = [backup_installation._agent_unit(agent) for agent in manifest["agents"]]
    if maintenance_backup._loaded_agents() - set(units):
        raise RuntimeError("unexpected loaded Agent service")
    backup_installation._no_active_agents()
    template = maintenance_backup._validate_template(install_fresh.AGENT_UNIT)
    for unit in units:
        maintenance_backup._managed_unit(unit, template)
        backup_installation._stopped(unit)
    if manifest["core"]:
        template = maintenance_backup._validate_template(install_fresh.CORE_UNIT)
        maintenance_backup._managed_unit(install_fresh.CORE_UNIT, template)
        backup_installation._stopped(install_fresh.CORE_UNIT)
    remove_services._reject_remaining_links(manifest["core"])
    os.chmod(etc_new, 0o755)
    os.chmod(data_new, 0o755)
    _sync_tree(etc_new)
    _sync_tree(data_new)
    for original, new, previous in ((etc, etc_new, etc_old), (data, data_new, data_old)):
        os.rename(original, previous)
        _sync_directory(original.parent)
        os.rename(new, original)
        _sync_directory(original.parent)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path, help="trusted private format 3 restore backup")
    parser.add_argument("safety_backup", type=Path, help="new private backup of current data")
    parser.add_argument("--confirm-restore", action="store_true")
    parser.add_argument("--confirm-writers-stopped", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_restore or not args.confirm_writers_stopped:
        parser.error("both confirmation flags are required; restore replaces the current data")
    try:
        apply(args.backup, args.safety_backup)
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        sqlite3.Error,
        subprocess.SubprocessError,
    ) as error:
        print(f"Restore failed: {error}", file=sys.stderr)
        print(
            "Services may be stopped or disabled and installation directories may be partially "
            "swapped. Do not start services or retry blindly. Inspect the safety backup and "
            "the .restore-new and .restore-previous directories before recovery.",
            file=sys.stderr,
        )
        return 1
    print(
        "Restore applied; services remain disabled and stopped. The previous installation "
        "directories and safety backup were retained. Inspect ownership, release and data "
        "before explicitly starting services."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
