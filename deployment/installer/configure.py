#!/usr/bin/env python3
"""Interactively prepare a private, non-destructive deployment configuration."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit

IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,256}$")


def validate_url(value: str, *, https: bool) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid URL or port") from exc
    if (
        parsed.scheme not in (("https",) if https else ("http", "https"))
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port == 0
        or any(c.isspace() or ord(c) < 32 for c in value)
    ):
        raise ValueError("URL must be HTTP(S), without credentials, query, or fragment")
    return value.rstrip("/")


def build_configuration(
    mode: str,
    agent_id: str,
    moonraker_url: str,
    core_url: str,
    token: str,
    ca_file: str | None = None,
) -> tuple[dict[str, object], str, str | None]:
    if mode not in {"standalone", "agent_only"}:
        raise ValueError("Mode must be standalone or agent_only")
    if not IDENTIFIER.fullmatch(agent_id) or agent_id in {".", ".."}:
        raise ValueError("Agent ID must be 1-100 letters, digits, dots, underscores or hyphens")
    if not token and mode != "standalone":
        raise ValueError("Agent-only mode requires a registered Agent token")
    if token and not TOKEN.fullmatch(token):
        raise ValueError("Agent token must contain 16-256 URL-safe letters, digits, - or _")
    moonraker = validate_url(moonraker_url, https=False)
    core = validate_url(core_url, https=mode == "agent_only")
    if mode == "standalone" and core != "http://127.0.0.1:8000":
        raise ValueError("Standalone Core URL must be http://127.0.0.1:8000")
    agent: dict[str, object] = {
        "agent_id": agent_id,
        "local_buffer_url": f"sqlite:////var/lib/stunsail/agent/{agent_id}/buffer.db",
        "core_url": core,
        "moonraker": {"instances": [{"name": agent_id, "url": moonraker}]},
    }
    if ca_file:
        if not ca_file.startswith("/") or any(ord(char) < 32 for char in ca_file):
            raise ValueError("CA file must be an absolute path without control characters")
        if not core.startswith("https://"):
            raise ValueError("A CA file requires an HTTPS Core URL")
        agent["core_ca_file"] = ca_file
    admin = secrets.token_urlsafe(32) if mode == "standalone" else None
    return {"deployment_mode": mode, "agent": agent}, token, admin


def write_bundle(
    destination: Path, config: dict[str, object], token: str, admin: str | None
) -> None:
    """Create a new private directory; never replace an existing configuration."""
    destination.mkdir(mode=0o700)
    if os.name == "posix":
        os.chmod(destination, 0o700)

    def create(name: str, content: str) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(destination / name, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)

    create("agent.yaml", json.dumps(config, indent=2) + "\n")
    create("agent.env", f"STUNSAIL_AGENT_TOKEN={token}\n")
    if admin:
        create(
            "core.env",
            "STUNSAIL_DATABASE_URL=sqlite:////var/lib/stunsail/core/stunsail.db\n"
            "STUNSAIL_WEB_DIR=/opt/stunsail/current/apps/web/dist\n"
            f"STUNSAIL_ADMIN_TOKEN={admin}\n",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a private configuration bundle; does not install or start services."
    )
    parser.add_argument("destination", type=Path, help="new directory in a secure parent")
    args = parser.parse_args(argv)
    try:
        mode = input("Mode (standalone/agent_only): ").strip()
        agent_id = input("Registered Agent ID: ").strip()
        moonraker = input("Moonraker URL: ").strip()
        if mode == "standalone":
            core = "http://127.0.0.1:8000"
        else:
            core = input("Core HTTPS URL: ").strip()
        ca = input("Core CA bundle path (optional): ").strip() or None
        prompt = (
            "Agent token (hidden; leave empty until registered): "
            if mode == "standalone"
            else "Registered Agent token (hidden): "
        )
        token = getpass.getpass(prompt)
        config, agent_token, admin = build_configuration(mode, agent_id, moonraker, core, token, ca)
        write_bundle(args.destination, config, agent_token, admin)
    except (OSError, ValueError, EOFError, KeyboardInterrupt) as error:
        print(f"Configuration preparation failed: {error}", file=sys.stderr)
        return 1
    print(f"Private configuration written to {args.destination}.")
    print("No services were installed or started. Protect and back up this directory.")
    if admin:
        print("The generated Core admin token is in core.env; do not share it.")
        if not agent_token:
            print("After starting Core, register this Agent and put its token in agent.env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
