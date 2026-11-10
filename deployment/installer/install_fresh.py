#!/usr/bin/env python3
"""Install a fresh StunSail system from a trusted release and private bundle."""

from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
import shutil
import ssl
import stat
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import configure
import preflight
import prepare_runtime
import register_local_agent

OPT = Path("/opt/stunsail")
ETC = Path("/etc/stunsail")
DATA = Path("/var/lib/stunsail")
UNITS = Path("/etc/systemd/system")
CORE_UNIT = "stunsail-core.service"
AGENT_UNIT = "stunsail-agent@.service"


def _read_bundle(bundle: Path, *, additional_agent: bool = False) -> tuple[dict, str, str | None]:
    directory = bundle.lstat()
    if (
        not stat.S_ISDIR(directory.st_mode)
        or directory.st_uid != os.geteuid()
        or stat.S_IMODE(directory.st_mode) != 0o700
    ):
        raise ValueError("configuration bundle must be root-owned with mode 0700")
    raw, _ = register_local_agent.read_private(bundle / "agent.yaml")
    config = json.loads(raw)
    if not isinstance(config, dict) or not isinstance(config.get("agent"), dict):
        raise ValueError("invalid configuration bundle")
    agent = config["agent"]
    mode = config.get("deployment_mode")
    moonraker = agent.get("moonraker")
    if not isinstance(moonraker, dict):
        raise ValueError("configuration must contain a Moonraker section")
    instances = moonraker.get("instances", [])
    if not isinstance(instances, list) or len(instances) != 1 or not isinstance(instances[0], dict):
        raise ValueError("configuration must contain exactly one Moonraker instance")
    agent_env, _ = register_local_agent.read_private(bundle / "agent.env")
    if not agent_env.startswith("STUNSAIL_AGENT_TOKEN=") or not agent_env.endswith("\n"):
        raise ValueError("invalid agent.env")
    token = agent_env.removeprefix("STUNSAIL_AGENT_TOKEN=").removesuffix("\n")
    expected, _, _ = configure.build_configuration(
        mode,
        agent.get("agent_id"),
        instances[0].get("url"),
        agent.get("core_url"),
        token,
        agent.get("core_ca_file"),
    )
    if config != expected:
        raise ValueError("configuration must be an unmodified configure.py bundle")
    core_env = None
    if additional_agent and not token:
        raise ValueError("an additional Agent requires a registered Agent token")
    if mode == "standalone" and not additional_agent:
        _absent(bundle / ".agent.env.pending")
        if token:
            raise ValueError("fresh standalone installation requires an empty Agent token")
        core_env, _ = register_local_agent.read_private(bundle / "core.env")
        lines = core_env.splitlines()
        if (
            len(lines) != 3
            or lines[0] != "STUNSAIL_DATABASE_URL=sqlite:////var/lib/stunsail/core/stunsail.db"
            or lines[1] != "STUNSAIL_WEB_DIR=/opt/stunsail/current/apps/web/dist"
            or not lines[2].startswith("STUNSAIL_ADMIN_TOKEN=")
            or not configure.TOKEN.fullmatch(lines[2].partition("=")[2])
            or not core_env.endswith("\n")
        ):
            raise ValueError("invalid standalone core.env")
    return config, agent_env, core_env


def _read_ca(agent: dict) -> str | None:
    if not agent.get("core_ca_file"):
        return None
    ca_path = Path(agent["core_ca_file"])
    if ca_path.is_symlink() or not ca_path.is_file():
        raise ValueError("CA bundle must be an existing regular file")
    ca_content = ca_path.read_text(encoding="utf-8")
    if "PRIVATE KEY-----" in ca_content:
        raise ValueError("CA trust bundle must not contain a private key")
    ssl.create_default_context(cafile=str(ca_path))
    return ca_content


def _absent(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing installation path: {path}")


def _account_absent(name: str) -> None:
    try:
        pwd.getpwnam(name)
    except KeyError:
        pass
    else:
        raise FileExistsError(f"refusing to reuse existing user: {name}")
    try:
        grp.getgrnam(name)
    except KeyError:
        pass
    else:
        raise FileExistsError(f"refusing to reuse existing group: {name}")


def _run(*command: str) -> None:
    subprocess.run(list(command), check=True)


def _write(path: Path, content: str, mode: int, uid: int = 0, gid: int = 0) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(path, flags, mode)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        os.fchmod(stream.fileno(), mode)
        os.fchown(stream.fileno(), uid, gid)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _ready() -> None:
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), register_local_agent.NoRedirect()
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with opener.open("http://127.0.0.1:8000/api/v1/health/ready", timeout=2) as response:
                body = json.loads(response.read(65536))
                if response.status == 200 and body.get("status") == "ready":
                    return
        except (OSError, ValueError, AttributeError):
            time.sleep(0.5)
    raise RuntimeError("Core did not become ready within 30 seconds")


def install(
    source: Path,
    bundle: Path,
    *,
    confirm_low_disk_space: bool = False,
    confirm_experimental_platform: bool = False,
) -> None:
    if os.name != "posix" or os.geteuid() != 0:
        raise RuntimeError("fresh system installation requires Linux root")
    config, agent_env, core_env = _read_bundle(bundle)
    agent = config["agent"]
    agent_id = agent["agent_id"]
    standalone = config["deployment_mode"] == "standalone"
    checks = preflight.run_checks(Path("/"))
    if standalone:
        checks.append(preflight.check_core_port())
    failures = [
        f"{item.name}: {item.detail}"
        for item in checks
        if not item.ok
        and not (
            item.requires_confirmation
            and (
                (item.name == "disk space" and confirm_low_disk_space)
                or (item.name == "operating system" and confirm_experimental_platform)
            )
        )
    ]
    if failures:
        raise RuntimeError("preflight failed: " + "; ".join(failures))
    for item in checks:
        if not item.ok and item.requires_confirmation:
            print(
                f"WARNING: {item.name}: {item.detail}. Installation may fail; "
                "existing printing services and data may be affected by resource exhaustion.",
                file=sys.stderr,
            )
    for command in ("uv", "groupadd", "useradd", "runuser", "systemd-escape"):
        if not shutil.which(command):
            raise RuntimeError(f"required command not found: {command}")
    for path in (OPT, ETC, DATA, UNITS / AGENT_UNIT):
        _absent(path)
    if standalone:
        _absent(UNITS / CORE_UNIT)
    for unit in (CORE_UNIT, AGENT_UNIT) if standalone else (AGENT_UNIT,):
        for directory in (
            Path("/run/systemd/system"),
            Path("/usr/local/lib/systemd/system"),
            Path("/usr/lib/systemd/system"),
            Path("/lib/systemd/system"),
        ):
            _absent(directory / unit)
        probe = unit if unit == CORE_UNIT else "stunsail-agent@stunsail-install-probe.service"
        state = subprocess.run(
            ["systemctl", "show", probe, "--property=LoadState", "--value"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        if state != "not-found":
            raise FileExistsError(f"systemd already has a unit named {unit}: {state}")
    identities = ["stunsail-agent"]
    if standalone:
        identities.append("stunsail-core")
    for identity in identities:
        _account_absent(identity)
    source = prepare_runtime.validate_source(source)
    for unit in (CORE_UNIT, AGENT_UNIT) if standalone else (AGENT_UNIT,):
        path = source / "deployment" / "systemd" / unit
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"release is missing a regular unit: {path}")
    ca_content = _read_ca(agent)

    for identity in identities:
        _run("groupadd", "--system", identity)
        _run(
            "useradd",
            "--system",
            "--gid",
            identity,
            "--no-create-home",
            "--home-dir",
            "/nonexistent",
            "--shell",
            "/usr/sbin/nologin",
            identity,
        )
    OPT.mkdir(mode=0o755)
    OPT.chmod(0o755)
    releases = OPT / "releases"
    releases.mkdir(mode=0o755)
    releases.chmod(0o755)
    old_umask = os.umask(0o022)
    try:
        prepare_runtime.prepare(source, releases / "initial")
    finally:
        os.umask(old_umask)
    (OPT / "current").symlink_to(releases / "initial", target_is_directory=True)
    ETC.mkdir(mode=0o755)
    ETC.chmod(0o755)
    (ETC / "agent").mkdir(mode=0o755)
    (ETC / "agent").chmod(0o755)
    agent_dir = ETC / "agent" / agent_id
    agent_dir.mkdir(mode=0o711)
    agent_dir.chmod(0o711)
    DATA.mkdir(mode=0o755)
    DATA.chmod(0o755)
    (DATA / "agent").mkdir(mode=0o755)
    (DATA / "agent").chmod(0o755)
    agent_user = pwd.getpwnam("stunsail-agent")
    agent_data = DATA / "agent" / agent_id
    agent_data.mkdir(mode=0o700)
    agent_data.chmod(0o700)
    os.chown(agent_data, agent_user.pw_uid, agent_user.pw_gid)
    if ca_content is not None:
        _write(agent_dir / "ca.pem", ca_content, 0o644)
        agent["core_ca_file"] = str(agent_dir / "ca.pem")
    _write(
        agent_dir / "agent.yaml",
        json.dumps(config, indent=2) + "\n",
        0o440,
        0,
        agent_user.pw_gid,
    )
    if standalone:
        core_user = pwd.getpwnam("stunsail-core")
        core_data = DATA / "core"
        core_data.mkdir(mode=0o700)
        core_data.chmod(0o700)
        os.chown(core_data, core_user.pw_uid, core_user.pw_gid)
        _write(ETC / "core.env", core_env, 0o600)
        env = os.environ.copy()
        env["STUNSAIL_DATABASE_URL"] = "sqlite:////var/lib/stunsail/core/stunsail.db"
        subprocess.run(
            [
                "runuser",
                "-u",
                "stunsail-core",
                "--",
                str(OPT / "current/.venv/bin/alembic"),
                "upgrade",
                "head",
            ],
            cwd=OPT / "current",
            env=env,
            check=True,
        )
    for unit in (CORE_UNIT, AGENT_UNIT) if standalone else (AGENT_UNIT,):
        _write(
            UNITS / unit,
            (source / "deployment/systemd" / unit).read_text(encoding="utf-8"),
            0o644,
        )
    _run("systemctl", "daemon-reload")
    if standalone:
        _run("systemctl", "start", CORE_UNIT)
        _ready()
        _run("systemctl", "is-active", "--quiet", CORE_UNIT)
        register_local_agent.register(bundle)
        agent_env, _ = register_local_agent.read_private(bundle / "agent.env")
    _write(agent_dir / "agent.env", agent_env, 0o600)
    instance = subprocess.run(
        ["systemd-escape", "--template=stunsail-agent@.service", "--", agent_id],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _run("systemctl", "start", instance)
    _run("systemctl", "is-active", "--quiet", instance)
    _run("systemctl", "enable", *((CORE_UNIT, instance) if standalone else (instance,)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="trusted extracted release source")
    parser.add_argument("bundle", type=Path, help="root-owned private configuration bundle")
    parser.add_argument("--confirm-fresh-install", action="store_true")
    parser.add_argument(
        "--confirm-low-disk-space",
        action="store_true",
        help="accept less than the recommended 2 GiB free; the minimum still applies",
    )
    parser.add_argument(
        "--confirm-experimental-platform",
        action="store_true",
        help="accept the specifically identified experimental OS; other OS failures remain fatal",
    )
    args = parser.parse_args(argv)
    if not args.confirm_fresh_install:
        parser.error("--confirm-fresh-install is required; this creates users and starts services")
    try:
        install(
            args.source,
            args.bundle,
            confirm_low_disk_space=args.confirm_low_disk_space,
            confirm_experimental_platform=args.confirm_experimental_platform,
        )
    except (OSError, ValueError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Fresh installation failed: {error}", file=sys.stderr)
        print(
            "Installation may be partial and services may be running. Do not retry blindly or "
            "remove data; inspect systemd, the bundle, /opt/stunsail, /etc/stunsail and "
            "/var/lib/stunsail first.",
            file=sys.stderr,
        )
        return 1
    print("Fresh installation started. Register a printer in Settings and verify Agent sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
