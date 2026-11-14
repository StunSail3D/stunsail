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
    # Ancestors may be user-owned (for example a home directory). The bundle itself
    # is created root-owned 0700, so only root can read its credentials; we still
    # reject group/world-writable ancestors to limit tampering with the path.
    for path in (parent, *parent.parents):
        info = path.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022:
            raise ValueError(
                f"bundle ancestor must be a directory and not group/world writable: {path}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="trusted extracted release source")
    parser.add_argument("bundle", type=Path, help="new private configuration directory")
    parser.add_argument(
        "--mode", choices=("standalone", "agent_only"), help="skip the interactive mode prompt"
    )
    args = parser.parse_args(argv)
    if os.name != "posix" or os.geteuid() != 0:
        print("Guided installation requires Linux root.", file=sys.stderr)
        return 1
    try:
        validate_bundle_destination(args.bundle)
    except (OSError, ValueError) as error:
        print(f"Invalid bundle destination: {error}", file=sys.stderr)
        return 1

    print("Experimental fresh installation only. Existing installations are not upgraded.")
    configure_argv = [str(args.bundle)]
    if args.mode:
        configure_argv += ["--mode", args.mode]
    if configure.main(configure_argv) != 0:
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
            low_space = input("Accept the low-disk-space risk? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            low_space = ""
        if low_space not in {"y", "yes"}:
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
            answer = input("Accept the experimental-platform risk? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer not in {"y", "yes"}:
            print("Installation cancelled; no services changed.")
            return 1
        command.append("--confirm-experimental-platform")
    return install_fresh.main(command)


if __name__ == "__main__":
    raise SystemExit(main())
