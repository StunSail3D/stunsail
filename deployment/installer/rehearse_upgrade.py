#!/usr/bin/env python3
"""Rehearse a prepared release's migrations on a backup, without activating it."""

from __future__ import annotations

import argparse
import contextlib
import os
import pwd
import secrets
import sqlite3
import subprocess
import sys
from pathlib import Path

import apply_restore
import backup_installation
import install_fresh
import maintenance_backup
import release_fingerprint
import remove_services
import sqlite_snapshot
import verify_backup
import verify_release


def _environment(database: Path) -> dict[str, str]:
    return {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": "/nonexistent",
        "STUNSAIL_DATABASE_URL": "sqlite:///" + str(database),
    }


def _migration(candidate: Path, backup: Path, digest: str, destination: Path) -> None:
    user = pwd.getpwnam("stunsail-core")
    apply_restore._new_directory(destination, 0o700, user.pw_uid, user.pw_gid)
    database = destination / "stunsail.db"
    apply_restore._copy(
        backup / "data" / "core" / "stunsail.db",
        database,
        digest,
        0o600,
        user.pw_uid,
        user.pw_gid,
    )
    env = _environment(database)
    alembic = candidate / ".venv" / "bin" / "alembic"
    for action in (("upgrade", "head"), ("current", "--check-heads")):
        subprocess.run(
            ["runuser", "-u", "stunsail-core", "--", str(alembic), *action],
            cwd=candidate,
            env=env,
            check=True,
        )
    with contextlib.closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("migration rehearsal database failed SQLite integrity check")


def _smoke(candidate: Path, destination: Path) -> None:
    user = pwd.getpwnam("stunsail-core")
    database = destination / "smoke.db"
    sqlite_snapshot.snapshot(destination / "stunsail.db", database)
    os.chown(database, user.pw_uid, user.pw_gid)
    env = _environment(database)
    env["STUNSAIL_ADMIN_TOKEN"] = secrets.token_urlsafe(32)
    subprocess.run(
        [
            "runuser",
            "-u",
            "stunsail-core",
            "--",
            str(candidate / ".venv" / "bin" / "python"),
            "-I",
            str(Path(__file__).with_name("runtime_smoke.py")),
        ],
        cwd=candidate,
        env=env,
        check=True,
    )


def _agents(candidate: Path, backup: Path, manifest: dict, destination: Path) -> None:
    user = pwd.getpwnam("stunsail-agent")
    apply_restore._new_directory(destination, 0o711)
    for agent in manifest["agents"]:
        directory = destination / agent
        apply_restore._new_directory(directory, 0o700, user.pw_uid, user.pw_gid)
        for relative, name in (
            (f"config/agent/{agent}/agent.yaml", "agent.yaml"),
            (f"data/agent/{agent}/buffer.db", "buffer.db"),
        ):
            apply_restore._copy(
                backup / relative,
                directory / name,
                manifest["files"][relative],
                0o600,
                user.pw_uid,
                user.pw_gid,
            )
        subprocess.run(
            [
                "runuser",
                "-u",
                "stunsail-agent",
                "--",
                str(candidate / ".venv" / "bin" / "python"),
                "-I",
                str(Path(__file__).with_name("agent_runtime_smoke.py")),
                str(directory / "agent.yaml"),
                str(directory / "buffer.db"),
                agent,
            ],
            cwd=candidate,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/nonexistent"},
            check=True,
        )


def rehearse(candidate: Path, backup: Path) -> None:
    if os.name != "posix" or os.geteuid() != 0:
        raise RuntimeError("upgrade rehearsal requires Linux root")
    opt = backup_installation.OPT
    for path in (opt, opt / "releases", backup_installation.DATA.parent):
        maintenance_backup._trusted_directory(path)
    if not candidate.is_absolute() or candidate.resolve(strict=True) != candidate:
        raise ValueError("candidate must be an absolute release path without symlinks")
    if candidate.parent != (opt / "releases").resolve(strict=True):
        raise ValueError("candidate must be directly under the installer releases directory")
    maintenance_backup._trusted_directory(candidate)
    current = (opt / "current").resolve(strict=True)
    if current == candidate:
        raise ValueError("candidate must be a separate prepared release")
    candidate_hash = release_fingerprint.fingerprint(candidate)
    for executable in ("python", "uvicorn", "stunsail-agent", "alembic"):
        path = candidate / ".venv" / "bin" / executable
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError(f"candidate runtime is missing executable: {path}")
    has_core = (backup_installation.ETC / "core.env").is_file()
    names = [install_fresh.AGENT_UNIT]
    if has_core:
        names.append(install_fresh.CORE_UNIT)
    for name in names:
        installed = maintenance_backup._validate_template(name)
        proposed = candidate / "deployment" / "systemd" / name
        if (
            proposed.is_symlink()
            or not proposed.is_file()
            or proposed.read_bytes() != (installed.read_bytes())
        ):
            raise ValueError(f"candidate service unit differs from installed unit: {name}")
    rehearsal = backup_installation.DATA.with_name(
        backup_installation.DATA.name + ".upgrade-rehearsal"
    )
    agent_rehearsal = backup_installation.DATA.with_name(
        backup_installation.DATA.name + ".upgrade-rehearsal-agents"
    )
    install_fresh._absent(agent_rehearsal)
    if has_core:
        install_fresh._absent(rehearsal)
    maintenance_backup.create(backup)
    manifest = verify_backup.verify(backup)
    if manifest["core"] != has_core or manifest["release_path"] != str(current):
        raise RuntimeError("installation changed during maintenance backup")
    verify_release.verify(backup, current)
    if (opt / "current").resolve(strict=True) != current:
        raise RuntimeError("current release changed during upgrade rehearsal")
    if release_fingerprint.fingerprint(candidate) != candidate_hash:
        raise RuntimeError("candidate release changed during upgrade rehearsal")
    units = [backup_installation._agent_unit(agent) for agent in manifest["agents"]]
    if maintenance_backup._loaded_agents() - set(units):
        raise RuntimeError("unexpected loaded Agent service")
    backup_installation._no_active_agents()
    agent_template = maintenance_backup._validate_template(install_fresh.AGENT_UNIT)
    for unit in units:
        maintenance_backup._managed_unit(unit, agent_template)
        backup_installation._stopped(unit)
    if has_core:
        core_template = maintenance_backup._validate_template(install_fresh.CORE_UNIT)
        maintenance_backup._managed_unit(install_fresh.CORE_UNIT, core_template)
        backup_installation._stopped(install_fresh.CORE_UNIT)
    remove_services._reject_remaining_links(has_core)
    if has_core:
        _migration(candidate, backup, manifest["files"]["data/core/stunsail.db"], rehearsal)
        _smoke(candidate, rehearsal)
    _agents(candidate, backup, manifest, agent_rehearsal)
    if release_fingerprint.fingerprint(candidate) != candidate_hash:
        raise RuntimeError("candidate release changed during migration rehearsal")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path, help="already prepared candidate release")
    parser.add_argument("backup", type=Path, help="new secure pre-upgrade backup directory")
    parser.add_argument("--confirm-stop-services", action="store_true")
    parser.add_argument("--confirm-writers-stopped", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_stop_services or not args.confirm_writers_stopped:
        parser.error("both confirmation flags are required")
    try:
        rehearse(args.candidate, args.backup)
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        sqlite3.Error,
        subprocess.SubprocessError,
    ) as error:
        print(f"Upgrade rehearsal failed: {error}", file=sys.stderr)
        print(
            "Services may be disabled or stopped. The backup and rehearsal database may be "
            "partial. Inspect them before retrying; no release was activated and no rollback "
            "was attempted.",
            file=sys.stderr,
        )
        return 1
    print(
        "Upgrade rehearsal completed. No release was activated and live databases were not "
        "migrated. Services remain disabled and stopped; inspect the backup and rehearsal "
        "database before deciding how to proceed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
