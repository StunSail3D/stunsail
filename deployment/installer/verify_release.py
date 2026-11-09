#!/usr/bin/env python3
"""Compare a prepared release's source files with a verified backup."""

from __future__ import annotations

import argparse
import sqlite3
import sys
import tomllib
from pathlib import Path

import release_fingerprint
import verify_backup


def verify(backup: Path, release: Path) -> None:
    manifest = verify_backup.verify(backup)
    if manifest["format"] != 3:
        raise ValueError("format 2 backups do not contain a release fingerprint")
    if not release.is_absolute() or release.resolve(strict=True) != release:
        raise ValueError("release path must be absolute and contain no symlinks or '..'")
    actual = release_fingerprint.fingerprint(release)
    if actual != manifest["release_sha256"]:
        raise ValueError("release files do not match the backup fingerprint")
    if verify_backup.digest(release / "uv.lock") != manifest["lock_sha256"]:
        raise ValueError("release lockfile does not match the backup")
    with (release / "pyproject.toml").open("rb") as stream:
        version = tomllib.load(stream).get("project", {}).get("version")
    if version != manifest["version"]:
        raise ValueError("release version does not match the backup")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path, help="existing protected format 3 backup")
    parser.add_argument("release", type=Path, help="absolute path to matching release directory")
    args = parser.parse_args(argv)
    try:
        verify(args.backup, args.release)
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f"Release comparison failed: {error}", file=sys.stderr)
        return 1
    print(
        "Release source files match the backup fingerprint. This does not authenticate the "
        "backup or release, check the virtual environment, or apply a restore."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
