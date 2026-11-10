#!/usr/bin/env python3
"""Guide a fresh installation using the shared configuration and installer."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

import configure
import install_fresh
import preflight


def validate_bundle_destination(destination: Path) -> None:
    if not destination.is_absolute():
        raise ValueError("configuration bundle path must be absolute")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"refusing to overwrite configuration bundle: {destination}")
    parent = destination.parent
    if parent.resolve(strict=True) != parent:
        raise ValueError("configuration bundle parent must not contain symlinks or '..'")
    for path in (parent, *parent.parents):
        info = path.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError(
                f"bundle ancestor must be root-owned and not group/world writable: {path}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="trusted extracted release source")
    parser.add_argument("bundle", type=Path, help="new private configuration directory")
    args = parser.parse_args(argv)
    if os.name != "posix" or os.geteuid() != 0:
        print("Guided installation requires Linux root.", file=sys.stderr)
        return 1
    try:
        validate_bundle_destination(args.bundle)
    except (OSError, ValueError) as error:
        print(f"Invalid bundle destination: {error}", file=sys.stderr)
        return 1

    print(
        "Experimental fresh installation only. Existing installations are not upgraded.\n"
        "Remote Agents require a separately provisioned HTTPS endpoint. "
        "This installer does not configure TLS."
    )
    if configure.main([str(args.bundle)]) != 0:
        return 1
    print(
        "\nThe next step creates system accounts and files, migrates a new database, "
        "and starts and enables services. Failure can leave a partial installation.\n"
        f"Credentials are stored in {args.bundle}; keep this directory private."
    )
    try:
        confirmation = input("Type INSTALL to proceed, or press Enter to cancel: ").strip()
    except (EOFError, KeyboardInterrupt):
        confirmation = ""
    if confirmation != "INSTALL":
        print(
            f"Installation cancelled. Configuration remains in {args.bundle}; no services changed."
        )
        return 1
    disk = preflight.check_disk_space(Path("/"))
    if not disk.ok:
        print(f"Disk space: {disk.detail}")
        if not disk.requires_confirmation:
            print("Installation cancelled; the disk-space check failed.")
            return 1
        print(
            "Low free space can interrupt printing, installation, upgrades and data storage. "
            "The minimum is an estimate, not a guarantee of sufficient space."
        )
        try:
            low_space = input("Type LOW SPACE to accept the risk, or press Enter to cancel: ")
        except (EOFError, KeyboardInterrupt):
            low_space = ""
        if low_space.strip() != "LOW SPACE":
            print("Installation cancelled; no services changed.")
            return 1
    command = [str(args.source), str(args.bundle), "--confirm-fresh-install"]
    if disk.requires_confirmation:
        command.append("--confirm-low-disk-space")
    platform_checks = preflight.local_platform_checks()
    platform_failures = [check for check in platform_checks if not check.ok]
    for check in platform_failures:
        print(f"Platform check: {check.name}: {check.detail}")
    if any(not check.requires_confirmation for check in platform_failures):
        print("Installation cancelled; unsupported platform or missing platform metadata.")
        return 1
    if platform_failures:
        print("This platform is experimental; installation and printing may be affected.")
        try:
            answer = input("Type EXPERIMENTAL to accept the risk, or press Enter to cancel: ")
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer.strip() != "EXPERIMENTAL":
            print("Installation cancelled; no services changed.")
            return 1
        command.append("--confirm-experimental-platform")
    return install_fresh.main(command)


if __name__ == "__main__":
    raise SystemExit(main())
