#!/usr/bin/env python3
"""Interactive StunSail management tool (experimental).

Presents a menu to install (Standalone or Agent-only), back up, uninstall, or run
a health check. Installation runs the preflight, the guided install, an automatic
running-service check, and optional TLS certificate creation. Requires Linux root.

Usage:
    sudo python3 install.py [extracted-release-source]

The source argument is required for a fresh install; backup/uninstall/health
checks do not need it.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import check_running
import full_uninstall
import guided_install
import maintenance_backup
import preflight
import provision_tls

_RESET = "\033[0m"
_BOLD = "\033[1m"
_BLUE = "34"
_YELLOW = "33"
_GREEN = "32"
_ORANGE = "38;5;208"
_CYAN = "36"
_MAGENTA = "35"


def _color(code: str, text: str) -> str:
    if sys.stdout.isatty():
        return f"\033[{code}m{text}{_RESET}"
    return text


def _prompt(text: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{text}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    return answer or default


def _user_home() -> str:
    sudo_user = os.environ.get("SUDO_USER")
    try:
        return pwd.getpwnam(sudo_user).pw_dir if sudo_user else "/root"
    except KeyError:
        return "/root"


def _default_bundle() -> str:
    return str(Path(_user_home()) / "stunsail-setup")


def _prompt_destination(label: str, default_name: str) -> Path:
    default = Path(_user_home()) / default_name
    if default.exists() or default.is_symlink():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        default = default.with_name(f"{default_name}-{stamp}")
    return Path(_prompt(label, str(default)))


def _run_preflight() -> bool:
    checks = preflight.run_checks(Path("/"))
    checks.append(preflight.check_core_port())
    hard_failure = False
    for check in checks:
        status = "OK" if check.ok else ("WARN" if check.requires_confirmation else "FAIL")
        print(f"{status}: {check.name}: {check.detail}")
        if not check.ok and not check.requires_confirmation:
            hard_failure = True
    if hard_failure:
        print("Preflight failed; resolve the FAIL items before installing.")
        return False
    print("Preflight passed (warnings are confirmed during installation).")
    return True


def _generate_certificates(source: Path, ip: str, directory: Path) -> bool:
    uv = shutil.which("uv")
    if uv is None:
        print("uv was not found; cannot generate certificates. Skipping TLS.")
        return False
    generator = source / "deployment" / "installer" / "generate_ca_and_cert.py"
    env = os.environ.copy()
    env.setdefault("UV_CACHE_DIR", "/tmp/stunsail-uv-cache")
    command = [
        uv,
        "run",
        "--no-project",
        "--with",
        "cryptography",
        str(generator),
        "--no-ca-key",
        "--ca-cert",
        str(directory / "ca.crt"),
        "--server-cert",
        str(directory / "server.crt"),
        "--server-key",
        str(directory / "server.key"),
        "--ip-address",
        ip,
    ]
    print("Generating a TLS certificate (the CA private key is never written to disk)...")
    result = subprocess.run(command, env=env, check=False)
    if result.returncode != 0:
        print("Certificate generation failed; skipping TLS.")
        return False
    return True


def _provision_certificate(source: Path, ip: str) -> None:
    with tempfile.TemporaryDirectory(prefix="stunsail-tls-") as temporary:
        directory = Path(temporary)
        if not _generate_certificates(source, ip, directory):
            return
        result = provision_tls.main(
            [
                "--server-cert",
                str(directory / "server.crt"),
                "--server-key",
                str(directory / "server.key"),
                "--ca-bundle",
                str(directory / "ca.crt"),
                "--ip-address",
                ip,
                "--confirm-provision-tls",
            ]
        )
    if result != 0:
        print("TLS provisioning failed; inspect the frontend service before retrying.")
        return
    print(f"\nStunSail is ready at https://{ip}:8443")
    print(
        "To avoid a browser warning, copy /etc/stunsail/certs/ca.crt to your computer "
        "and import it as a trusted root certificate, then open the URL above."
    )


def _prompt_certificate_ip() -> str | None:
    ip = _prompt("Host LAN IP for the certificate (for example 192.168.1.50)")
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        print("Invalid IP address; skipping TLS.")
        return None
    return ip


def _offer_tls(source: Path) -> None:
    answer = _prompt(
        "Create a TLS certificate for the web frontend (recommended for remote access)? [y/N]",
        "n",
    ).lower()
    if answer not in {"y", "yes"}:
        print(
            "Skipping TLS. Core listens on loopback only; to reach the UI from another "
            "device use an SSH tunnel, or use the 'Install TLS certificate' menu option."
        )
        return
    ip = _prompt_certificate_ip()
    if ip is not None:
        _provision_certificate(source, ip)


def _install_certificate(source: Path | None) -> None:
    gen_source = source if source is not None else Path("/opt/stunsail/current")
    generator = gen_source / "deployment" / "installer" / "generate_ca_and_cert.py"
    if not generator.is_file():
        print("Certificate generator not found; install StunSail first or pass the source.")
        return
    ip = _prompt_certificate_ip()
    if ip is not None:
        _provision_certificate(gen_source, ip)


def _install(source: Path | None, mode: str) -> None:
    if source is None:
        print("Provide the extracted release source as an argument to install.")
        return
    bundle = Path(_prompt("Configuration bundle destination", _default_bundle()))
    print("\n== Preflight ==")
    if not _run_preflight():
        return
    print("\n== Guided installation ==")
    if guided_install.main([str(source), str(bundle), "--mode", mode]) != 0:
        return
    print("\n== Running-service check ==")
    check_running.main(["--mode", "standalone" if mode == "standalone" else "agent-only"])
    if mode == "standalone":
        _offer_tls(source)


def _backup() -> None:
    print(
        _color(_GREEN, "Backup")
        + " disables and stops local services, then creates a verified backup."
    )
    if _prompt("Type BACKUP to continue, or press Enter to cancel") != "BACKUP":
        print("Cancelled.")
        return
    destination = _prompt_destination("Backup destination", "stunsail-backup")
    maintenance_backup.main([str(destination), "--confirm-stop-services"])


def _remove_bundle() -> None:
    bundle = Path(_prompt("Configuration bundle to remove", _default_bundle()))
    if bundle.is_symlink():
        bundle.unlink()
        print(f"Removed configuration bundle symlink {bundle}.")
    elif (bundle / "agent.yaml").is_file():
        shutil.rmtree(bundle)
        print(f"Removed configuration bundle {bundle}.")
    elif bundle.exists():
        print(f"{bundle} does not look like a StunSail bundle (no agent.yaml); leaving it.")
    else:
        print(f"No configuration bundle found at {bundle}; nothing to remove.")


def _uninstall() -> bool:
    print(
        _color(_ORANGE, "Uninstall")
        + " is destructive: it removes all StunSail data, configuration, services and "
        "service accounts."
    )
    if _prompt("Type UNINSTALL to continue, or press Enter to cancel") != "UNINSTALL":
        print("Cancelled.")
        return False
    make_backup = _prompt("Create a backup before removal? [Y/n]", "y").lower() in {"y", "yes"}
    if make_backup:
        destination = _prompt_destination(
            "Backup destination (created before removal)", "stunsail-uninstall-backup"
        )
        result = full_uninstall.main([str(destination), "--confirm-full-uninstall"])
    else:
        print(
            _color(
                _ORANGE, "No backup will be created; all StunSail data will be permanently lost."
            )
        )
        result = full_uninstall.main(["--no-backup", "--confirm-full-uninstall"])
    if result != 0:
        print("Uninstall failed; inspect the system before retrying.")
        return False
    _remove_bundle()
    print("StunSail completely removed.")
    return True


def _health() -> None:
    etc = Path("/etc/stunsail")
    if not etc.exists():
        print("StunSail does not appear to be installed (/etc/stunsail is missing).")
        return
    mode = "standalone" if (etc / "core.env").exists() else "agent-only"
    check_running.main(["--mode", mode])


def _menu() -> str:
    print()
    print(_BOLD + "StunSail management (experimental)" + _RESET)
    print(f"  1) {_color(_BLUE, 'Install Standalone')}")
    print(f"  2) {_color(_YELLOW, 'Install Agent-only')}")
    print(f"  3) {_color(_MAGENTA, 'Install TLS certificate')}")
    print(f"  4) {_color(_GREEN, 'Backup')}")
    print(f"  5) {_color(_ORANGE, 'Uninstall')}")
    print(f"  6) {_color(_CYAN, 'Health check')}")
    print("  0) Exit")
    return _prompt("Select an option")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source",
        type=Path,
        nargs="?",
        default=None,
        help="trusted extracted release source (required for a fresh install)",
    )
    args = parser.parse_args(argv)
    if os.name != "posix" or os.geteuid() != 0:
        print("This tool requires Linux root.", file=sys.stderr)
        return 1
    while True:
        choice = _menu()
        if choice == "1":
            _install(args.source, "standalone")
        elif choice == "2":
            _install(args.source, "agent_only")
        elif choice == "3":
            _install_certificate(args.source)
        elif choice == "4":
            _backup()
        elif choice == "5":
            if _uninstall():
                print("Uninstall finished; exiting.")
                return 0
        elif choice == "6":
            _health()
        elif choice in {"0", "q", "quit", "exit"}:
            print("Goodbye.")
            return 0
        else:
            print("Invalid option; choose a number from the menu.")


if __name__ == "__main__":
    raise SystemExit(main())
