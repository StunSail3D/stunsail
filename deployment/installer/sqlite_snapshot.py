#!/usr/bin/env python3
"""Create a consistent SQLite snapshot without overwriting existing files."""

from __future__ import annotations

import argparse
import contextlib
import os
import sqlite3
import sys
from pathlib import Path

SQLITE_HEADER = b"SQLite format 3\x00"


def snapshot(source: Path, destination: Path) -> None:
    """Copy a live SQLite database using SQLite's online backup API.

    The destination must not exist. Source and destination are opened separately
    and no live database or WAL file is replaced.
    """
    source = source.resolve(strict=True)
    if not source.is_file():
        raise ValueError(f"source is not a regular file: {source}")
    with source.open("rb") as stream:
        if stream.read(len(SQLITE_HEADER)) != SQLITE_HEADER:
            raise ValueError(f"source is not a SQLite database: {source}")

    destination = destination.absolute()
    if not destination.parent.is_dir():
        raise ValueError(f"destination directory does not exist: {destination.parent}")

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(destination, flags, 0o600)
    os.close(fd)
    succeeded = False
    try:
        source_uri = source.as_uri() + "?mode=ro"
        with contextlib.closing(sqlite3.connect(source_uri, uri=True, timeout=30)) as original:
            with contextlib.closing(sqlite3.connect(str(destination), timeout=30)) as copy:
                original.backup(copy)
                result = copy.execute("PRAGMA integrity_check").fetchall()
                if result != [("ok",)]:
                    raise ValueError(f"snapshot integrity check failed: {result}")
        succeeded = True
    finally:
        if not succeeded:
            destination.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Back up or restore SQLite to a new, non-existing database file."
    )
    parser.add_argument("source", type=Path, help="existing database or backup")
    parser.add_argument("destination", type=Path, help="new file; must not already exist")
    args = parser.parse_args(argv)
    try:
        snapshot(args.source, args.destination)
    except (OSError, sqlite3.Error, ValueError) as error:
        print(f"SQLite snapshot failed: {error}", file=sys.stderr)
        return 1
    print(f"SQLite snapshot created and verified: {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
