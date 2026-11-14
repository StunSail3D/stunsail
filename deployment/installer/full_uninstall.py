#!/usr/bin/env python3
"""Back up, then completely remove an installer-managed StunSail system.

Experimental and destructive: after a verified backup, this stops and disables all
StunSail services (including instantiated Agents and the TLS frontend), removes their
unit files and enablement links, deletes /opt/stunsail, /etc/stunsail and
/var/lib/stunsail, and removes the service accounts. Requires --confirm-full-uninstall.
"""

from __future__ import annotations

import argparse
import grp
import os
import pwd
import shutil
import subprocess
import sys
from pathlib import Path

import backup_installation
import install_fresh
import maintenance_backup
import verify_backup

FRONTEND_UNIT = "stunsail-frontend.service"
ACCOUNTS = ("stunsail-core", "stunsail-agent")


def _disk_free() -> int:
    return shutil.disk_usage("/").free


def _remove_account(name: str) -> None:
    try:
        pwd.getpwnam(name)
    except KeyError:
        pass
    else:
        install_fresh._run("userdel", name)
    try:
        grp.getgrnam(name)
    except KeyError:
        pass
    else:
        install_fresh._run("groupdel", name)


def _purge_unit_files() -> None:
    for current, _, files in os.walk(install_fresh.UNITS, followlinks=False):
        for name in files:
            if name.startswith("stunsail-"):
                path = Path(current) / name
                if path.is_symlink() or path.is_file():
                    path.unlink()


def _verify_removed() -> None:
    if maintenance_backup._loaded_agents():
        raise RuntimeError("Agent services are still loaded after uninstall")
    for path in (install_fresh.OPT, install_fresh.ETC, install_fresh.DATA):
        if path.exists() or path.is_symlink():
            raise RuntimeError(f"installation directory still present: {path}")
    for _current, _, files in os.walk(install_fresh.UNITS, followlinks=False):
        for name in files:
            if name.startswith("stunsail-"):
                raise RuntimeError(f"StunSail unit or enablement link still present: {name}")
    for name in ACCOUNTS:
        try:
            pwd.getpwnam(name)
        except KeyError:
            continue
        raise RuntimeError(f"service user still present: {name}")


def uninstall(destination: Path) -> dict:
    if os.name != "posix" or os.geteuid() != 0:
        raise RuntimeError("full uninstall requires Linux root")
    free_before = _disk_free()
    maintenance_backup.create(destination)
    manifest = verify_backup.verify(destination)

    frontend = install_fresh.UNITS / FRONTEND_UNIT
    if frontend.exists() or frontend.is_symlink():
        install_fresh._run("systemctl", "disable", "--now", FRONTEND_UNIT)
    units = [backup_installation._agent_unit(agent) for agent in manifest["agents"]]
    if maintenance_backup._loaded_agents() - set(units):
        raise RuntimeError("unexpected loaded Agent service")
    for unit in units:
        install_fresh._run("systemctl", "disable", unit)
        install_fresh._run("systemctl", "stop", unit)
    if manifest["core"]:
        install_fresh._run("systemctl", "disable", install_fresh.CORE_UNIT)
        install_fresh._run("systemctl", "stop", install_fresh.CORE_UNIT)
    install_fresh._run("systemctl", "daemon-reload")

    _purge_unit_files()
    install_fresh._run("systemctl", "daemon-reload")

    for path in (install_fresh.OPT, install_fresh.ETC, install_fresh.DATA):
        if path.is_symlink():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)
    for name in ACCOUNTS:
        _remove_account(name)

    _verify_removed()
    free_after = _disk_free()
    return {
        "backup": str(destination),
        "free_before": free_before,
        "free_after": free_after,
        "freed": free_after - free_before,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "backup", type=Path, help="new backup directory in a secure root-owned parent"
    )
    parser.add_argument("--confirm-full-uninstall", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_full_uninstall:
        parser.error(
            "--confirm-full-uninstall is required; this permanently removes all StunSail "
            "data, configuration, services and service accounts after a backup"
        )
    try:
        report = uninstall(args.backup)
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as error:
        print(f"Full uninstall failed: {error}", file=sys.stderr)
        print(
            "The installation may be partially removed. A backup was attempted first; inspect "
            "it, the remaining directories, units and accounts before retrying. Do not assume "
            "the system is clean.",
            file=sys.stderr,
        )
        return 1
    print(f"Full uninstall complete. Verified backup retained at {report['backup']}.")
    print(
        f"Free space before: {report['free_before']} bytes; after: {report['free_after']} bytes "
        f"(net change {report['freed']} bytes; the retained backup still occupies space)."
    )
    print(
        "All StunSail services, unit files, data, configuration and service accounts were removed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
