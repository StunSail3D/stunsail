#!/usr/bin/env python3
"""Provision TLS for an installed StunSail system (experimental, post-install).

Installs a PC-generated server certificate/key and CA trust bundle, enables the
loopback-Core TLS frontend, and verifies HTTPS readiness against the CA. Uses only
the standard library: the host runtime intentionally has no cryptography. The CA
private key must never be copied to this host.
"""

from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import os
import pwd
import ssl
import subprocess
import sys
import time
from pathlib import Path

import add_agent
import install_fresh

FRONTEND_UNIT = "stunsail-frontend.service"
FRONTEND_PORT = 8443


def _certs_dir() -> Path:
    return install_fresh.ETC / "certs"


def _regular_input(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected a regular file: {path}")


def _validate_ip(value: str) -> None:
    ipaddress.ip_address(value)


def _validate_cert_key(cert: Path, key: Path) -> None:
    _regular_input(cert)
    _regular_input(key)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))


def _validate_ca(ca: Path) -> None:
    _regular_input(ca)
    if "PRIVATE KEY-----" in ca.read_text(encoding="utf-8"):
        raise ValueError("CA trust bundle must not contain a private key")
    ssl.create_default_context(cafile=str(ca))


def _trusted_release() -> Path:
    for path in (install_fresh.OPT, install_fresh.OPT / "releases", install_fresh.ETC):
        add_agent._trusted_directory(path)
    current = install_fresh.OPT / "current"
    if not current.is_symlink():
        raise ValueError("current runtime must be an installer-managed symlink")
    release = current.resolve(strict=True)
    if release.parent != (install_fresh.OPT / "releases").resolve(strict=True):
        raise ValueError("current release is outside the releases directory")
    return release


def _install_certs(cert: Path, key: Path, ca: Path) -> None:
    core = pwd.getpwnam("stunsail-core")
    directory = _certs_dir()
    install_fresh._absent(directory)
    directory.mkdir(mode=0o750)
    os.chown(directory, 0, core.pw_gid)
    directory.chmod(0o750)
    install_fresh._write(directory / "server.crt", cert.read_text(encoding="utf-8"), 0o644)
    install_fresh._write(directory / "ca.crt", ca.read_text(encoding="utf-8"), 0o644)
    install_fresh._write(
        directory / "server.key", key.read_text(encoding="utf-8"), 0o640, 0, core.pw_gid
    )


def _release_unit(release: Path) -> Path:
    source = release / "deployment" / "systemd" / FRONTEND_UNIT
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"release is missing a regular unit: {source}")
    add_agent._unit_is_trusted(source)
    return source


def _install_unit(source: Path) -> None:
    target = install_fresh.UNITS / FRONTEND_UNIT
    install_fresh._absent(target)
    install_fresh._write(target, source.read_text(encoding="utf-8"), 0o644)
    install_fresh._run("systemctl", "daemon-reload")
    install_fresh._run("systemctl", "enable", "--now", FRONTEND_UNIT)


def _verify_https(ip: str, ca: Path, port: int = FRONTEND_PORT) -> dict:
    context = ssl.create_default_context(cafile=str(ca))
    connection = http.client.HTTPSConnection(ip, port, context=context, timeout=5)
    try:
        connection.request("GET", "/api/v1/health/ready")
        response = connection.getresponse()
        data = response.read(65536)
        status = response.status
    finally:
        connection.close()
    if status != 200:
        raise RuntimeError(f"TLS frontend readiness returned HTTP {status}")
    body = json.loads(data)
    if not isinstance(body, dict) or body.get("status") != "ready":
        raise RuntimeError("TLS frontend returned an invalid readiness response")
    return body


def _ready_https(ip: str, ca: Path, *, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            _verify_https(ip, ca)
            return
        except (OSError, ValueError, RuntimeError, http.client.HTTPException) as error:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"TLS frontend did not become ready within {timeout:.0f} seconds"
                ) from error
            time.sleep(0.5)


def provision(cert: Path, key: Path, ca: Path, ip: str) -> None:
    if os.name != "posix" or os.geteuid() != 0:
        raise RuntimeError("TLS provisioning requires Linux root")
    _validate_ip(ip)
    _validate_cert_key(cert, key)
    _validate_ca(ca)
    release = _trusted_release()
    source_unit = _release_unit(release)
    _install_certs(cert, key, ca)
    _install_unit(source_unit)
    _ready_https(ip, _certs_dir() / "ca.crt")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--server-cert", type=Path, required=True, help="PC-generated server certificate (PEM)"
    )
    parser.add_argument(
        "--server-key", type=Path, required=True, help="PC-generated server private key (PEM)"
    )
    parser.add_argument(
        "--ca-bundle", type=Path, required=True, help="CA trust bundle without a private key (PEM)"
    )
    parser.add_argument(
        "--ip-address", required=True, help="host IP present in the certificate IP SAN"
    )
    parser.add_argument("--confirm-provision-tls", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_provision_tls:
        parser.error(
            "--confirm-provision-tls is required; this installs certificates and enables "
            "the TLS frontend"
        )
    try:
        provision(args.server_cert, args.server_key, args.ca_bundle, args.ip_address)
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        subprocess.SubprocessError,
        http.client.HTTPException,
    ) as error:
        print(f"TLS provisioning failed: {error}", file=sys.stderr)
        print(
            "Certificates or the frontend service may be partially installed. Inspect "
            "/etc/stunsail/certs, the frontend unit and its logs before retrying; do not "
            "remove existing configuration or data.",
            file=sys.stderr,
        )
        return 1
    ca_path = _certs_dir() / "ca.crt"
    core_url = f"https://{args.ip_address}:{FRONTEND_PORT}"
    print(f"TLS frontend enabled and verified at {core_url}.")
    print("To onboard an Agent over TLS:")
    print("  1. Register a new Agent ID in the Core UI (Settings) and copy its token.")
    print(f"  2. Run configure.py: mode agent_only, Core URL {core_url},")
    print(f"     CA bundle path {ca_path}, and the registered Agent token.")
    print("  3. Run add_agent.py <bundle> --confirm-add-agent.")
    print("  4. Verify the Agent syncs over HTTPS, then register its printer.")
    print("The CA private key stays on the PC; only the ca.crt trust bundle was installed here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
