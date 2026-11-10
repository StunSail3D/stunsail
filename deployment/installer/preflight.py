#!/usr/bin/env python3
"""Read-only checks for the future Linux installer."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

MIN_FREE_BYTES = 2 * 1024**3
MIN_INSTALL_BYTES = 256 * 1024**2
SUPPORTED_ARCHITECTURES = {"x86_64", "aarch64"}


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    requires_confirmation: bool = False


def check_disk_space(directory: Path) -> Check:
    try:
        free = shutil.disk_usage(directory).free
    except OSError as error:
        return Check("disk space", False, str(error))
    detail = (
        f"{free // 1024**2} MiB free on {directory}; "
        f"minimum {MIN_INSTALL_BYTES // 1024**2} MiB, recommended {MIN_FREE_BYTES // 1024**2} MiB"
    )
    if free < MIN_INSTALL_BYTES:
        return Check("disk space", False, detail + "; insufficient installation reserve")
    if free < MIN_FREE_BYTES:
        return Check("disk space", False, detail + "; low-space confirmation required", True)
    return Check("disk space", True, detail)


def os_release(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        result[key] = value
    return result


def check_platform(release: dict[str, str], machine: str, system: str) -> list[Check]:
    identifier = release.get("ID", "").lower()
    like = release.get("ID_LIKE", "").lower().split()
    version = release.get("VERSION_ID", "")
    codename = release.get("VERSION_CODENAME", "").lower()
    armbian = identifier == "armbian" or "armbian" in like
    if identifier == "debian" or identifier == "raspbian":
        supported = version == "12"
    elif identifier == "ubuntu":
        supported = version == "24.04"
    elif armbian:
        supported = version.startswith("26.") and codename in {"bookworm", "noble"}
    else:
        supported = False
    experimental = (
        system == "Linux" and identifier == "debian" and version == "13" and codename == "trixie"
    )
    detail = f"{identifier or 'unknown'} {version or 'unknown'} ({codename or 'unknown base'})"
    if experimental:
        detail += "; experimental and unvalidated, explicit confirmation required"
    return [
        Check("operating system", system == "Linux" and supported, detail, experimental),
        Check("architecture", machine.lower() in SUPPORTED_ARCHITECTURES, machine),
        Check("Python", sys.version_info >= (3, 11), platform.python_version()),
    ]


def check_systemd(executable: str | None) -> Check:
    if not executable:
        return Check("systemd manager", False, "systemctl not found")
    try:
        result = subprocess.run(
            [executable, "show", "--property=Version", "--value"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return Check("systemd manager", False, str(error))
    version = result.stdout.strip()
    return Check("systemd manager", bool(version), version or "manager returned no version")


def check_core_port() -> Check:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 8000))
    except OSError as error:
        return Check("Core port", False, f"127.0.0.1:8000: {error}")
    return Check("Core port", True, "127.0.0.1:8000 is available")


def check_http(url: str, *, moonraker: bool) -> Check:
    name = "Moonraker" if moonraker else "dependency index"
    try:
        parsed = urlsplit(url)
        port = parsed.port
        if (
            parsed.scheme not in (("http", "https") if moonraker else ("https",))
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or port == 0
            or any(c.isspace() or ord(c) < 32 for c in url)
        ):
            raise ValueError("invalid URL; credentials, queries and fragments are not allowed")
        endpoint = url.rstrip("/") + "/server/info" if moonraker else url
        with urlopen(endpoint, timeout=5) as response:
            if not moonraker and urlsplit(response.geturl()).scheme != "https":
                raise ValueError("dependency index redirected to a non-HTTPS URL")
            if moonraker:
                body = response.read(1024 * 1024 + 1)
                if len(body) > 1024 * 1024:
                    raise ValueError("Moonraker response exceeds 1 MiB")
                data = json.loads(body)
                if not isinstance(data, dict) or not isinstance(data.get("result"), dict):
                    raise ValueError("response is not Moonraker server information")
            else:
                response.read(1)
        return Check(name, True, "reachable")
    except (OSError, ValueError, http.client.HTTPException) as error:
        return Check(name, False, str(error))


def local_platform_checks(release_path: Path = Path("/etc/os-release")) -> list[Check]:
    try:
        release = os_release(release_path)
    except OSError as error:
        release = {}
        release_error = str(error)
    else:
        release_error = ""
    checks = check_platform(release, platform.machine(), platform.system())
    if release_error:
        checks.append(Check("OS metadata", False, release_error))
    return checks


def run_checks(directory: Path, release_path: Path = Path("/etc/os-release")) -> list[Check]:
    checks = local_platform_checks(release_path)
    for command in ("systemctl", "dpkg", "python3"):
        path = shutil.which(command)
        checks.append(Check(command, bool(path), path or "not found"))
    checks.append(check_systemd(shutil.which("systemctl")))
    checks.append(check_disk_space(directory))
    checks.append(
        Check(
            "administrator privileges",
            hasattr(os, "geteuid") and os.geteuid() == 0,
            "root required for system-wide installation",
        )
    )
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check prerequisites without installing anything.")
    parser.add_argument(
        "--disk-path",
        type=Path,
        default=Path("/"),
        help="existing filesystem to check for free space",
    )
    parser.add_argument(
        "--mode", choices=("standalone", "agent_only"), help="check the selected deployment mode"
    )
    parser.add_argument(
        "--moonraker-url", help="explicitly test the Moonraker server/info endpoint"
    )
    parser.add_argument(
        "--dependency-index-url",
        help="explicitly test an HTTPS dependency index (for example https://pypi.org/simple/)",
    )
    args = parser.parse_args(argv)
    checks = run_checks(args.disk_path)
    if args.mode == "standalone":
        checks.append(check_core_port())
    if args.moonraker_url:
        checks.append(check_http(args.moonraker_url, moonraker=True))
    if args.dependency_index_url:
        checks.append(check_http(args.dependency_index_url, moonraker=False))
    for check in checks:
        status = "OK" if check.ok else "WARN" if check.requires_confirmation else "FAIL"
        print(f"{status}: {check.name}: {check.detail}")
    print(
        "Checks are point-in-time only. Service conflicts, certificate provisioning and "
        "end-to-end installation are not checked."
    )
    if not args.moonraker_url or not args.dependency_index_url:
        print("Moonraker and dependency access are checked only when their URLs are supplied.")
    return 0 if all(check.ok for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
