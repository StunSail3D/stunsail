#!/usr/bin/env python3
"""Apply a rehearsed offline upgrade while retaining the previous release and Core data."""

from __future__ import annotations

import argparse
import os
import pwd
import sqlite3
import subprocess
import sys
from pathlib import Path

import apply_restore
import backup_installation
import install_fresh
import maintenance_backup
import rehearse_upgrade
import release_fingerprint
import remove_services
import sqlite_snapshot
import verify_backup
import verify_release


def _check_services(manifest: dict) -> None:
    units = [backup_installation._agent_unit(agent) for agent in manifest["agents"]]
    if maintenance_backup._loaded_agents() - set(units):
        raise RuntimeError("unexpected loaded Agent service")
    backup_installation._no_active_agents()
    agent_template = maintenance_backup._validate_template(install_fresh.AGENT_UNIT)
    for unit in units:
        maintenance_backup._managed_unit(unit, agent_template)
        backup_installation._stopped(unit)
    if manifest["core"]:
        core_template = maintenance_backup._validate_template(install_fresh.CORE_UNIT)
        maintenance_backup._managed_unit(install_fresh.CORE_UNIT, core_template)
        backup_installation._stopped(install_fresh.CORE_UNIT)
    remove_services._reject_remaining_links(manifest["core"])


def _identity(path: Path) -> tuple[int, int]:
    info = path.lstat()
    return info.st_dev, info.st_ino


def _switch(
    current_link: Path,
    current: Path,
    target: Path,
    next_link: Path,
    data: Path,
    prepared: Path,
    previous: Path,
    manifest: dict,
) -> None:
    core = data / "core"
    original_id = _identity(core) if manifest["core"] else None
    prepared_id = _identity(prepared) if manifest["core"] else None
    try:
        next_link.symlink_to(target, target_is_directory=True)
        apply_restore._sync_directory(current_link.parent)
        if manifest["core"]:
            os.rename(core, previous)
            apply_restore._sync_directory(data)
            apply_restore._sync_directory(data.parent)
            os.rename(prepared, core)
            apply_restore._sync_directory(data)
            apply_restore._sync_directory(data.parent)
        os.replace(next_link, current_link)
        apply_restore._sync_directory(current_link.parent)
    except OSError as error:
        if not manifest["core"]:
            raise
        try:
            if not current_link.is_symlink() or current_link.resolve(strict=True) != current:
                raise RuntimeError("release link changed; automatic recovery refused")
            _check_services(manifest)
            if previous.exists() and _identity(previous) == original_id:
                if core.exists() or core.is_symlink():
                    if _identity(core) != prepared_id or prepared.exists() or prepared.is_symlink():
                        raise RuntimeError("Core paths changed; automatic recovery refused")
                    os.rename(core, prepared)
                    apply_restore._sync_directory(data)
                    apply_restore._sync_directory(data.parent)
                elif not prepared.exists() or _identity(prepared) != prepared_id:
                    raise RuntimeError("prepared Core path changed; automatic recovery refused")
                os.rename(previous, core)
                apply_restore._sync_directory(data)
                apply_restore._sync_directory(data.parent)
            elif previous.is_symlink() or previous.exists():
                raise RuntimeError("previous Core path changed; automatic recovery refused")
            elif not core.exists() or _identity(core) != original_id:
                raise RuntimeError("original Core path changed; automatic recovery refused")
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as recovery_error:
            raise RuntimeError(
                f"switch failed: {error}; automatic Core recovery failed or was refused: "
                f"{recovery_error}"
            ) from error
        raise RuntimeError(
            f"switch failed: {error}; original Core directory restored, "
            "but inspect all recovery paths before restarting"
        ) from error


def apply(candidate: Path, backup: Path) -> None:
    if os.name != "posix" or os.geteuid() != 0:
        raise RuntimeError("offline upgrade requires Linux root")
    opt, data = backup_installation.OPT, backup_installation.DATA
    current_link = opt / "current"
    if not current_link.is_symlink():
        raise ValueError("current release must be an installer-managed symlink")
    old_release = current_link.resolve(strict=True)
    candidate_hash = release_fingerprint.fingerprint(candidate)
    core = data / "core"
    core_new = data.with_name(data.name + ".upgrade-core-new")
    core_old = data.with_name(data.name + ".upgrade-core-previous")
    next_link = opt / "current.upgrade-new"
    for path in (core_new, core_old, next_link):
        install_fresh._absent(path)
    rehearse_upgrade.rehearse(candidate, backup)
    manifest = verify_backup.verify(backup)
    if manifest["release_path"] != str(old_release):
        raise RuntimeError("current release changed during upgrade")
    verify_release.verify(backup, old_release)
    if release_fingerprint.fingerprint(candidate) != candidate_hash:
        raise RuntimeError("candidate release changed during upgrade")
    if not current_link.is_symlink() or current_link.resolve(strict=True) != old_release:
        raise RuntimeError("current release changed during upgrade")
    if manifest["core"]:
        backup_installation._directory(data)
        backup_installation._directory(core)
        if data.stat().st_dev != data.parent.stat().st_dev:
            raise ValueError("Core data and its recovery directory must be on the same filesystem")
        user = pwd.getpwnam("stunsail-core")
        apply_restore._new_directory(core_new, 0o700, user.pw_uid, user.pw_gid)
        migrated = data.with_name(data.name + ".upgrade-rehearsal") / "stunsail.db"
        backup_installation._regular(migrated)
        target = core_new / "stunsail.db"
        sqlite_snapshot.snapshot(migrated, target)
        os.chown(target, user.pw_uid, user.pw_gid)
        os.chmod(target, 0o600)
        with target.open("rb") as stream:
            os.fsync(stream.fileno())
        apply_restore._sync_directory(core_new)
    _check_services(manifest)
    verify_release.verify(backup, old_release)
    if release_fingerprint.fingerprint(candidate) != candidate_hash:
        raise RuntimeError("candidate release changed before activation")
    if not current_link.is_symlink() or current_link.resolve(strict=True) != old_release:
        raise RuntimeError("current release changed before activation")
    _switch(current_link, old_release, candidate, next_link, data, core_new, core_old, manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path, help="already prepared trusted candidate release")
    parser.add_argument("backup", type=Path, help="new secure pre-upgrade backup directory")
    parser.add_argument("--confirm-upgrade", action="store_true")
    parser.add_argument("--confirm-writers-stopped", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_upgrade or not args.confirm_writers_stopped:
        parser.error("both confirmation flags are required; this replaces live Core data")
    try:
        apply(args.candidate, args.backup)
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        sqlite3.Error,
        subprocess.SubprocessError,
    ) as error:
        print(f"Offline upgrade failed: {error}", file=sys.stderr)
        print(
            "Services may be disabled or stopped. The release and Core database may be "
            "partially switched. Do not start services or retry blindly; inspect the backup, "
            "current symlink, stunsail.upgrade-core-new and stunsail.upgrade-core-previous "
            "before recovery. A limited in-process Core recovery may have been attempted; "
            "it does not handle process termination or power loss.",
            file=sys.stderr,
        )
        return 1
    print(
        "Offline upgrade applied. Services remain disabled and stopped. The previous release, "
        "Core data, backup and rehearsal copies were retained. Inspect and validate before "
        "explicitly starting services."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
