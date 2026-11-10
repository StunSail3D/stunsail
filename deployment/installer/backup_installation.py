#!/usr/bin/env python3
"""Back up a stopped, installer-managed StunSail installation to a new directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

import configure
import guided_install
import release_fingerprint
import sqlite_snapshot
import verify_backup

ETC = Path("/etc/stunsail")
DATA = Path("/var/lib/stunsail")
OPT = Path("/opt/stunsail")


def _regular(path: Path) -> None:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"expected a regular file, not a symlink: {path}")


def _directory(path: Path) -> None:
    if not stat.S_ISDIR(path.lstat().st_mode):
        raise ValueError(f"expected a directory, not a symlink: {path}")


def _stopped(unit: str) -> None:
    result = subprocess.run(
        ["systemctl", "show", unit, "--property=LoadState", "--property=ActiveState"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if fields.get("LoadState") != "loaded" or fields.get("ActiveState") not in {
        "inactive",
        "failed",
    }:
        raise RuntimeError(f"service {unit} is not loaded and stopped: {result.stdout.strip()}")


def _agent_unit(agent_id: str) -> str:
    return subprocess.run(
        ["systemd-escape", "--template=stunsail-agent@.service", "--", agent_id],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()


def _no_active_agents() -> None:
    result = subprocess.run(
        [
            "systemctl",
            "list-units",
            "--all",
            "--type=service",
            "--no-legend",
            "--no-pager",
            "--state=active,activating,reloading,deactivating",
            "stunsail-agent@*.service",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.stdout.strip():
        raise RuntimeError("an additional Agent service is active; stop all Agents before backup")


def _private_directory(path: Path) -> None:
    path.mkdir(mode=0o700)
    path.chmod(0o700)


def _private_copy(source: Path, destination: Path) -> None:
    _regular(source)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as target, source.open("rb") as original:
        os.fchmod(target.fileno(), 0o600)
        shutil.copyfileobj(original, target)
        target.flush()
        os.fsync(target.fileno())


def backup(destination: Path) -> None:
    if os.name != "posix" or os.geteuid() != 0:
        raise RuntimeError("installation backup requires Linux root")
    guided_install.validate_bundle_destination(destination)
    if any(destination.is_relative_to(path) for path in (ETC, DATA, OPT)):
        raise ValueError("backup destination must be outside the installation directories")
    for path in (ETC, ETC / "agent", DATA, DATA / "agent", OPT, OPT / "releases"):
        _directory(path)
    current = OPT / "current"
    if not current.is_symlink():
        raise ValueError("current release must be an installer-managed symlink")
    release = current.resolve(strict=True)
    if release.parent != (OPT / "releases").resolve(strict=True):
        raise ValueError("current release must be directly under the releases directory")
    for name in ("pyproject.toml", "uv.lock"):
        _regular(release / name)
    with (release / "pyproject.toml").open("rb") as stream:
        version = tomllib.load(stream).get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("current release has no project version")
    release_hash = release_fingerprint.fingerprint(release)

    configurations = sorted((ETC / "agent").iterdir())
    buffers = sorted((DATA / "agent").iterdir())
    if not configurations or {p.name for p in configurations} != {p.name for p in buffers}:
        raise ValueError("Agent configuration and data directories must match and not be empty")
    agent_files: list[tuple[str, Path, Path, list[Path]]] = []
    for directory in configurations:
        _directory(directory)
        agent_id = directory.name
        if not configure.IDENTIFIER.fullmatch(agent_id) or agent_id in {".", ".."}:
            raise ValueError(f"invalid Agent directory name: {agent_id}")
        data_dir = DATA / "agent" / agent_id
        _directory(data_dir)
        files = sorted(directory.iterdir())
        if {path.name for path in files} - {"agent.yaml", "agent.env", "ca.pem"}:
            raise ValueError(f"unexpected Agent configuration file in {directory}")
        for path in files:
            _regular(path)
        if not {"agent.yaml", "agent.env"}.issubset({path.name for path in files}):
            raise ValueError(f"incomplete Agent configuration: {directory}")
        config = json.loads((directory / "agent.yaml").read_text(encoding="utf-8"))
        if not isinstance(config, dict) or not isinstance(config.get("agent"), dict):
            raise ValueError(f"invalid Agent configuration: {directory}")
        agent = config["agent"]
        if agent.get("agent_id") != agent_id or agent.get("local_buffer_url") != (
            f"sqlite:////var/lib/stunsail/agent/{agent_id}/buffer.db"
        ):
            raise ValueError(f"Agent identity or buffer path does not match: {directory}")
        ca = agent.get("core_ca_file")
        if ca is not None and (
            ca != f"/etc/stunsail/agent/{agent_id}/ca.pem" or not (directory / "ca.pem").is_file()
        ):
            raise ValueError(f"external or missing Agent CA bundle: {directory}")
        database = data_dir / "buffer.db"
        _regular(database)
        if {p.name for p in data_dir.iterdir()} - {"buffer.db", "buffer.db-wal", "buffer.db-shm"}:
            raise ValueError(f"unexpected Agent data in {data_dir}; back it up separately")
        for path in data_dir.iterdir():
            _regular(path)
        agent_files.append((agent_id, directory, database, files))

    core_env = ETC / "core.env"
    has_core = core_env.exists() or core_env.is_symlink()
    if {p.name for p in ETC.iterdir()} - {"agent", "core.env"}:
        raise ValueError("unexpected Core configuration; back it up separately")
    if {p.name for p in DATA.iterdir()} - {"agent", "core"}:
        raise ValueError("unexpected data directory; back it up separately")
    if has_core:
        _regular(core_env)
        core_contents = core_env.read_text(encoding="utf-8").splitlines()
        db_lines = [line for line in core_contents if line.startswith("STUNSAIL_DATABASE_URL=")]
        if db_lines != ["STUNSAIL_DATABASE_URL=sqlite:////var/lib/stunsail/core/stunsail.db"]:
            raise ValueError("Core database URL does not match installer-managed path")
        core_dir = DATA / "core"
        _directory(core_dir)
        if {p.name for p in core_dir.iterdir()} - {
            "stunsail.db",
            "stunsail.db-wal",
            "stunsail.db-shm",
        }:
            raise ValueError("unexpected Core data; back it up separately")
        _regular(core_dir / "stunsail.db")
        for path in core_dir.iterdir():
            _regular(path)
    elif (DATA / "core").exists() or (DATA / "core").is_symlink():
        raise ValueError("Core data exists without Core configuration")

    _no_active_agents()
    for agent_id, _, _, _ in agent_files:
        _stopped(_agent_unit(agent_id))
    if has_core:
        _stopped("stunsail-core.service")
    _private_directory(destination)
    _private_directory(destination / "config")
    _private_directory(destination / "data")
    config_agents = destination / "config" / "agent"
    data_agents = destination / "data" / "agent"
    _private_directory(config_agents)
    _private_directory(data_agents)
    if has_core:
        _private_copy(core_env, destination / "config" / "core.env")
        _private_directory(destination / "data" / "core")
        sqlite_snapshot.snapshot(
            DATA / "core" / "stunsail.db", destination / "data" / "core" / "stunsail.db"
        )
    for agent_id, _, database, files in agent_files:
        _private_directory(config_agents / agent_id)
        _private_directory(data_agents / agent_id)
        for path in files:
            _private_copy(path, config_agents / agent_id / path.name)
        sqlite_snapshot.snapshot(database, data_agents / agent_id / "buffer.db")
    _no_active_agents()
    for agent_id, _, _, _ in agent_files:
        _stopped(_agent_unit(agent_id))
    if has_core:
        _stopped("stunsail-core.service")
    if not current.is_symlink() or current.resolve(strict=True) != release:
        raise RuntimeError("current release changed during backup; no manifest was written")
    if release_fingerprint.fingerprint(release) != release_hash:
        raise RuntimeError("release files changed during backup; no manifest was written")
    with (release / "pyproject.toml").open("rb") as stream:
        final_version = tomllib.load(stream).get("project", {}).get("version")
    if final_version != version:
        raise RuntimeError("release version changed during backup; no manifest was written")
    backup_files = [
        path
        for parent in (destination / "config", destination / "data")
        for path in parent.rglob("*")
        if path.is_file()
    ]
    manifest = {
        "format": 3,
        "release_path": str(release),
        "version": version,
        "lock_sha256": hashlib.sha256((release / "uv.lock").read_bytes()).hexdigest(),
        "release_sha256": release_hash,
        "core": has_core,
        "agents": [agent_id for agent_id, _, _, _ in agent_files],
        "files": {
            path.relative_to(destination).as_posix(): verify_backup.digest(path)
            for path in sorted(backup_files)
        },
    }
    manifest_path = destination / "manifest.json"
    fd = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(manifest, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "destination", type=Path, help="new directory in a secure root-owned parent"
    )
    args = parser.parse_args(argv)
    try:
        backup(args.destination)
    except (OSError, ValueError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as error:
        print(f"Installation backup failed: {error}", file=sys.stderr)
        print(
            "If a partial backup exists, inspect it securely before removing or retrying.",
            file=sys.stderr,
        )
        return 1
    print(f"Backup created at {args.destination}; protect its credentials and retain the release.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
