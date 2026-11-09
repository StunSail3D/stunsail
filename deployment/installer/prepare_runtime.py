#!/usr/bin/env python3
"""Prepare a separate, immutable-location runtime without activating services."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REQUIRED_SOURCE = (
    "pyproject.toml",
    "uv.lock",
    "alembic.ini",
    "apps/web/dist/index.html",
    "database/migrations/env.py",
)


def prepare(source: Path, destination: Path) -> None:
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise ValueError("release source must be a directory")
    destination = destination.absolute()
    if not destination.parent.is_dir():
        raise ValueError("runtime parent directory must exist")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"refusing to overwrite {destination}")
    resolved_destination = destination.resolve()
    if resolved_destination.is_relative_to(source) or source.is_relative_to(resolved_destination):
        raise ValueError("runtime and source must not contain one another")
    for relative in REQUIRED_SOURCE:
        path = source / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"release source is missing a regular file: {relative}")
    for directory, subdirectories, files in os.walk(source, followlinks=False):
        for name in subdirectories + files:
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError(f"release source contains symlink: {path}")
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required to prepare the locked runtime")
    destination.mkdir(mode=0o755)
    shutil.copytree(source, destination, dirs_exist_ok=True)
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    env["UV_PROJECT_ENVIRONMENT"] = str(destination / ".venv")
    subprocess.run(
        [uv, "sync", "--locked", "--all-packages", "--no-default-groups", "--group", "runtime"],
        cwd=destination,
        env=env,
        check=True,
    )
    for executable in ("python", "uvicorn", "stunsail-agent", "alembic"):
        path = destination / ".venv" / "bin" / executable
        if not path.is_file() or not os.access(path, os.X_OK):
            raise RuntimeError(f"prepared runtime is missing executable: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a new runtime from a trusted release; no services are changed."
    )
    parser.add_argument("source", type=Path, help="trusted extracted release source directory")
    parser.add_argument("destination", type=Path, help="new final runtime directory")
    args = parser.parse_args(argv)
    try:
        prepare(args.source, args.destination)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Runtime preparation failed: {error}", file=sys.stderr)
        print(
            "If a partial destination was created, inspect it before removing or retrying.",
            file=sys.stderr,
        )
        return 1
    print(f"Runtime prepared at {args.destination}; no services or data were changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
