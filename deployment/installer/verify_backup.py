#!/usr/bin/env python3
"""Verify an installer-managed backup without modifying it or live data."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
from pathlib import Path

import configure

SHA256 = re.compile(r"[a-f0-9]{64}")


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def verify(directory: Path) -> dict:
    if not stat.S_ISDIR(directory.lstat().st_mode):
        raise ValueError("backup must be a directory, not a symlink")
    manifest_path = directory / "manifest.json"
    if not stat.S_ISREG(manifest_path.lstat().st_mode):
        raise ValueError("manifest must be a regular file")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("format") not in (2, 3):
        raise ValueError("unsupported or incomplete backup manifest; expected format 2 or 3")
    agents = manifest.get("agents")
    if (
        not isinstance(agents, list)
        or not agents
        or not all(
            isinstance(agent, str)
            and configure.IDENTIFIER.fullmatch(agent)
            and agent not in {".", ".."}
            for agent in agents
        )
        or len(agents) != len(set(agents))
    ):
        raise ValueError("invalid Agent list in backup manifest")
    if (
        not isinstance(manifest.get("core"), bool)
        or not isinstance(manifest.get("version"), str)
        or not manifest["version"]
        or not isinstance(manifest.get("release_path"), str)
        or not Path(manifest["release_path"]).is_absolute()
        or not isinstance(manifest.get("lock_sha256"), str)
        or not SHA256.fullmatch(manifest["lock_sha256"])
    ):
        raise ValueError("invalid release or Core metadata in backup manifest")
    if manifest["format"] == 3 and (
        not isinstance(manifest.get("release_sha256"), str)
        or not SHA256.fullmatch(manifest["release_sha256"])
    ):
        raise ValueError("invalid release fingerprint in backup manifest")
    hashes = manifest.get("files")
    if not isinstance(hashes, dict):
        raise ValueError("backup manifest has no file checksums")
    required = {
        f"{parent}/agent/{agent}/{name}"
        for agent in agents
        for parent, name in (
            ("config", "agent.yaml"),
            ("config", "agent.env"),
            ("data", "buffer.db"),
        )
    }
    if manifest["core"]:
        required.update(("config/core.env", "data/core/stunsail.db"))
    optional = {f"config/agent/{agent}/ca.pem" for agent in agents}
    if not required.issubset(hashes) or set(hashes) - required - optional:
        raise ValueError("backup manifest has missing or unexpected files")
    if not all(isinstance(value, str) and SHA256.fullmatch(value) for value in hashes.values()):
        raise ValueError("invalid checksum in backup manifest")

    actual = set()
    for root, dirs, files in os.walk(directory, followlinks=False):
        for name in dirs:
            path = Path(root) / name
            if not stat.S_ISDIR(path.lstat().st_mode):
                raise ValueError(f"backup contains a symlinked directory: {path}")
        for name in files:
            path = Path(root) / name
            if not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError(f"backup contains a non-regular file: {path}")
            actual.add(path.relative_to(directory).as_posix())
    if actual != set(hashes) | {"manifest.json"}:
        raise ValueError("backup files do not match manifest")
    for name, expected in hashes.items():
        path = directory.joinpath(*name.split("/"))
        if digest(path) != expected:
            raise ValueError(f"checksum mismatch: {name}")
        if name.startswith("data/"):
            uri = path.resolve(strict=True).as_uri() + "?mode=ro&immutable=1"
            with contextlib.closing(sqlite3.connect(uri, uri=True)) as db:
                if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ValueError(f"SQLite integrity check failed: {name}")
    for agent in agents:
        config_path = directory / "config" / "agent" / agent / "agent.yaml"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or not isinstance(config.get("agent"), dict):
            raise ValueError(f"invalid Agent configuration: {agent}")
        details = config["agent"]
        if details.get("agent_id") != agent or details.get("local_buffer_url") != (
            f"sqlite:////var/lib/stunsail/agent/{agent}/buffer.db"
        ):
            raise ValueError(f"Agent identity or buffer path mismatch: {agent}")
        ca = details.get("core_ca_file")
        if ca is not None and (
            ca != f"/etc/stunsail/agent/{agent}/ca.pem"
            or f"config/agent/{agent}/ca.pem" not in hashes
        ):
            raise ValueError(f"Agent CA bundle is missing or external: {agent}")
    if manifest["core"]:
        core_env = (directory / "config" / "core.env").read_text(encoding="utf-8").splitlines()
        db_lines = [line for line in core_env if line.startswith("STUNSAIL_DATABASE_URL=")]
        if db_lines != ["STUNSAIL_DATABASE_URL=sqlite:////var/lib/stunsail/core/stunsail.db"]:
            raise ValueError("Core database URL does not match installer-managed path")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path, help="existing protected backup directory")
    args = parser.parse_args(argv)
    try:
        manifest = verify(args.backup)
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f"Backup verification failed: {error}", file=sys.stderr)
        return 1
    release_note = (
        "Release fingerprint recorded."
        if manifest["format"] == 3
        else "Legacy format 2: release files cannot be compared."
    )
    print(
        f"Backup verified: {len(manifest['agents'])} Agent(s), "
        f"Core {'included' if manifest['core'] else 'not included'}, "
        f"release {manifest['version']}. {release_note} This does not authenticate the backup."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
