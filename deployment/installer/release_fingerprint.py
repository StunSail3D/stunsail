#!/usr/bin/env python3
"""Fingerprint release files without including the prepared virtual environment."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import verify_backup


def _walk_error(error: OSError) -> None:
    raise error


def fingerprint(release: Path) -> str:
    if not stat.S_ISDIR(release.lstat().st_mode):
        raise ValueError(f"release must be a directory, not a symlink: {release}")
    files = []
    for current, dirs, names in os.walk(release, followlinks=False, onerror=_walk_error):
        parent = Path(current)
        included = []
        for name in sorted(dirs):
            path = parent / name
            info = path.lstat()
            if parent == release and name == ".venv":
                if not stat.S_ISDIR(info.st_mode):
                    raise ValueError(f"virtual environment must be a directory: {path}")
                continue
            if name == "__pycache__":
                if not stat.S_ISDIR(info.st_mode):
                    raise ValueError(f"cache must be a directory: {path}")
                continue
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError(f"release contains a non-directory or symlink: {path}")
            included.append(name)
        dirs[:] = included
        for name in sorted(names):
            path = parent / name
            if not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError(f"release contains a non-regular file or symlink: {path}")
            files.append((path.relative_to(release).as_posix(), path))
    digest = hashlib.sha256()
    for relative, path in sorted(files):
        name = relative.encode("utf-8")
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(bytes.fromhex(verify_backup.digest(path)))
    return digest.hexdigest()
