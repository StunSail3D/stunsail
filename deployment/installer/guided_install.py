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
    return install_fresh.main([str(args.source), str(args.bundle), "--confirm-fresh-install"])


if __name__ == "__main__":
    raise SystemExit(main())
