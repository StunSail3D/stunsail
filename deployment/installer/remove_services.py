#!/usr/bin/env python3
"""Back up, disable and remove installer-managed service definitions, retaining data."""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import backup_installation
import install_fresh
import maintenance_backup
import release_fingerprint
import verify_backup

OTHER_UNIT_DIRS = (
    Path("/run/systemd/system"),
    Path("/usr/local/lib/systemd/system"),
    Path("/usr/lib/systemd/system"),
    Path("/lib/systemd/system"),
)


def _walk_error(error: OSError) -> None:
    raise error


def _reject_remaining_links(has_core: bool) -> None:
    root = install_fresh.UNITS
    expected = {root / install_fresh.AGENT_UNIT}
    if has_core:
        expected.add(root / install_fresh.CORE_UNIT)
    prefixes = ("stunsail-agent@", "stunsail-core.service")
    for directory in (root, *OTHER_UNIT_DIRS):
        if not directory.exists() and not directory.is_symlink():
            continue
        for current, directories, files in os.walk(
            directory, followlinks=False, onerror=_walk_error
        ):
            for name in directories + files:
                path = Path(current) / name
                if path in expected:
                    continue
                if name.startswith(prefixes):
                    raise ValueError(f"unexpected systemd unit link, override, or drop-in: {path}")
                if path.is_symlink():
                    target = path.resolve()
                    if target in expected or target.name.startswith(prefixes):
                        raise ValueError(f"unexpected systemd alias to StunSail unit: {path}")


def remove(destination: Path) -> None:
    if os.name != "posix" or os.geteuid() != 0:
        raise RuntimeError("service removal requires Linux root")
    maintenance_backup.create(destination)
    manifest = verify_backup.verify(destination)
    agent_ids = sorted(manifest["agents"])
    current_ids = sorted(path.name for path in (backup_installation.ETC / "agent").iterdir())
    if agent_ids != current_ids:
        raise RuntimeError("Agent list changed after backup; refusing to remove service units")
    release = (backup_installation.OPT / "current").resolve(strict=True)
    if manifest["release_path"] != str(release):
        raise RuntimeError("active release changed after backup; refusing to remove service units")
    if manifest["lock_sha256"] != verify_backup.digest(release / "uv.lock"):
        raise RuntimeError(
            "release lockfile changed after backup; refusing to remove service units"
        )
    if manifest["format"] == 3 and (
        manifest["release_sha256"] != release_fingerprint.fingerprint(release)
    ):
        raise RuntimeError("release files changed after backup; refusing to remove service units")
    if manifest["core"] != (backup_installation.ETC / "core.env").is_file():
        raise RuntimeError(
            "Core configuration changed after backup; refusing to remove service units"
        )
    units = [backup_installation._agent_unit(agent) for agent in agent_ids]
    if maintenance_backup._loaded_agents() - set(units):
        raise RuntimeError("unexpected loaded Agent service after backup")
    backup_installation._no_active_agents()
    for unit in units:
        backup_installation._stopped(unit)
    names = [install_fresh.AGENT_UNIT]
    if manifest["core"]:
        backup_installation._stopped(install_fresh.CORE_UNIT)
        names.append(install_fresh.CORE_UNIT)
    paths = [maintenance_backup._validate_template(name) for name in names]
    _reject_remaining_links(manifest["core"])
    for unit in units:
        maintenance_backup._managed_unit(unit, paths[0])
    if manifest["core"]:
        maintenance_backup._managed_unit(install_fresh.CORE_UNIT, paths[1])
    try:
        for path in paths:
            path.unlink()
    except OSError as error:
        try:
            install_fresh._run("systemctl", "daemon-reload")
        except (OSError, subprocess.SubprocessError) as reload_error:
            raise RuntimeError(
                f"unit removal failed ({error}); systemd reload also failed ({reload_error})"
            ) from reload_error
        raise
    install_fresh._run("systemctl", "daemon-reload")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "backup", type=Path, help="new backup directory in a secure root-owned parent"
    )
    parser.add_argument("--confirm-remove-services", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_remove_services:
        parser.error("--confirm-remove-services is required; services will be stopped and removed")
    try:
        remove(args.backup)
    except (OSError, ValueError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as error:
        print(f"Service removal failed: {error}", file=sys.stderr)
        print(
            "Services may be disabled, stopped or partially removed. No automatic rollback was "
            "attempted. Inspect systemd and the backup before proceeding.",
            file=sys.stderr,
        )
        return 1
    print(
        f"Service definitions removed. Backup: {args.backup}. Configuration, databases, "
        "buffers, runtimes and service accounts were retained."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
