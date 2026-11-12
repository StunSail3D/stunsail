#!/usr/bin/env python3
"""Build a data-preserving Debian source/runtime payload from an explicit allowlist."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = (
    "apps/api",
    "services/agent",
    "services/core",
    "packages/moonraker",
    "packages/shared-models",
    "packages/plugin-sdk",
    "packages/cost-engine",
)
WEB_EXTENSIONS = {".js", ".css", ".png", ".svg", ".ico", ".woff", ".woff2", ".ttf"}


def _copy_file(root: Path, destination: Path, relative: Path) -> None:
    source = root / relative
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"required regular file missing or symlinked: {relative}")
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(0o644)


def _copy_tree(root: Path, destination: Path, relative: Path, suffixes: set[str]) -> None:
    source = root / relative
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"required directory missing or symlinked: {relative}")
    copied = 0
    for current, dirs, files in os.walk(source, followlinks=False):
        parent = Path(current)
        dirs[:] = [name for name in dirs if not name.startswith(".") and name != "__pycache__"]
        for directory in dirs:
            if (parent / directory).is_symlink():
                raise ValueError(f"symlinked directory in release input: {parent / directory}")
        for name in files:
            path = parent / name
            if name.startswith(".") or path.suffix.lower() not in suffixes:
                continue
            _copy_file(root, destination, path.relative_to(root))
            copied += 1
    if not copied:
        raise ValueError(f"no release files found in {relative}")


def stage_payload(root: Path, stage: Path) -> str:
    with (root / "pyproject.toml").open("rb") as stream:
        version = tomllib.load(stream)["project"]["version"]
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){2}", version):
        raise ValueError("project version must be a numeric major.minor.patch")
    release = stage / "usr" / "share" / "stunsail" / "source"
    for name in ("pyproject.toml", "uv.lock", "alembic.ini"):
        _copy_file(root, release, Path(name))
    for package in PACKAGES:
        relative = Path(package)
        _copy_file(root, release, relative / "pyproject.toml")
        _copy_tree(root, release, relative / "src", {".py"})
    _copy_tree(root, release, Path("database/migrations"), {".py", ".mako"})
    _copy_file(root, release, Path("apps/web/dist/index.html"))
    _copy_tree(root, release, Path("apps/web/dist"), WEB_EXTENSIONS)
    for name in (
        "add_agent.py",
        "agent_runtime_smoke.py",
        "apply_restore.py",
        "apply_upgrade.py",
        "backup_installation.py",
        "check_running.py",
        "configure.py",
        "generate_ca.py",
        "guided_install.py",
        "install_fresh.py",
        "maintenance_backup.py",
        "preflight.py",
        "prepare_runtime.py",
        "register_local_agent.py",
        "rehearse_upgrade.py",
        "release_fingerprint.py",
        "remove_services.py",
        "rollback_upgrade.py",
        "runtime_smoke.py",
        "sqlite_snapshot.py",
        "stage_restore.py",
        "verify_backup.py",
        "verify_release.py",
        "README.md",
    ):
        _copy_file(root, release, Path("deployment/installer") / name)
    for name in ("stunsail-core.service", "stunsail-agent@.service", "README.md"):
        _copy_file(root, release, Path("deployment/systemd") / name)
    _copy_file(root, release, Path("docs/architecture/operations.md"))
    control = stage / "DEBIAN"
    control.mkdir(parents=True)
    (control / "control").write_text(
        "Package: stunsail\n"
        f"Version: {version}-1\n"
        "Section: utils\nPriority: optional\nArchitecture: all\n"
        "Maintainer: StunSail contributors\n"
        "Depends: python3 (>= 3.11)\n"
        "Description: StunSail local printer cost tracker payload\n"
        " Includes application sources and prebuilt web assets. Runtime preparation,\n"
        " configuration, migrations and service activation are separate steps.\n",
        encoding="utf-8",
    )
    (control / "control").chmod(0o644)
    return version


def build(root: Path, output: Path) -> None:
    if shutil.which("dpkg-deb") is None:
        raise RuntimeError("dpkg-deb is required to build the Debian package")
    output = output.absolute()
    if not output.parent.is_dir():
        raise ValueError("output parent directory must already exist")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refusing to overwrite {output}")
    with tempfile.TemporaryDirectory(prefix="stunsail-package-") as temporary:
        temp = Path(temporary)
        stage_payload(root, temp / "stage")
        archive = temp / "stunsail.deb"
        subprocess.run(
            ["dpkg-deb", "--root-owner-group", "--build", str(temp / "stage"), str(archive)],
            check=True,
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(output, flags, 0o644)
        try:
            with os.fdopen(fd, "wb") as target, archive.open("rb") as source:
                shutil.copyfileobj(source, target)
        except BaseException:
            output.unlink()
            raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a Debian package without modifying services."
    )
    parser.add_argument("output", type=Path, help="new .deb file; must not exist")
    args = parser.parse_args(argv)
    try:
        build(ROOT, args.output)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Debian package build failed: {error}", file=sys.stderr)
        return 1
    print(f"Built {args.output}; no services or configuration were changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
