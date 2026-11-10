#!/usr/bin/env python3
"""Stage a verified backup in a new private directory without replacing live data."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

import backup_installation
import guided_install
import verify_backup


def stage(source: Path, destination: Path) -> None:
    if os.name != "posix" or os.geteuid() != 0:
        raise RuntimeError("restore staging requires Linux root")
    guided_install.validate_bundle_destination(destination)
    if source.is_symlink():
        raise ValueError("backup directory must not be a symlink")
    source = source.resolve(strict=True)
    resolved_destination = destination.resolve()
    if resolved_destination.is_relative_to(source) or source.is_relative_to(resolved_destination):
        raise ValueError("backup and staging directories must not contain one another")
    if any(
        resolved_destination.is_relative_to(path)
        for path in (backup_installation.ETC, backup_installation.DATA, backup_installation.OPT)
    ):
        raise ValueError("staging directory must be outside installation directories")
    manifest = verify_backup.verify(source)
    backup_installation._private_directory(destination)
    for relative in sorted(manifest["files"]):
        source_file = source.joinpath(*relative.split("/"))
        target = destination.joinpath(*relative.split("/"))
        parent = destination
        for component in relative.split("/")[:-1]:
            parent = parent / component
            if not parent.exists():
                backup_installation._private_directory(parent)
        backup_installation._private_copy(source_file, target)
    backup_installation._private_copy(source / "manifest.json", destination / "manifest.json")
    verify_backup.verify(destination)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path, help="existing verified format 2 or 3 backup")
    parser.add_argument(
        "destination", type=Path, help="new directory in a secure root-owned parent"
    )
    args = parser.parse_args(argv)
    try:
        stage(args.backup, args.destination)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        print(f"Restore staging failed: {error}", file=sys.stderr)
        print(
            "If a partial staging directory exists, inspect it securely before retrying.",
            file=sys.stderr,
        )
        return 1
    print(
        f"Verified restore copy staged at {args.destination}. "
        "No live data or services were changed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
