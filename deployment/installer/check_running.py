#!/usr/bin/env python3
"""Check running installer-managed services without changing service state."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

import backup_installation
import configure
import install_fresh
import maintenance_backup
import register_local_agent

CORE_URL = "http://127.0.0.1:8000"
MAX_RESPONSE = 1024 * 1024


def _active(unit: str, template) -> None:
    maintenance_backup._managed_unit(unit, template)
    result = subprocess.run(
        ["systemctl", "show", unit, "--property=ActiveState", "--property=SubState"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if fields.get("ActiveState") != "active" or fields.get("SubState") != "running":
        raise RuntimeError(f"service is not active and running: {unit}")


def _response(opener, path: str, expected: int):
    request = urllib.request.Request(CORE_URL + path, method="GET")
    try:
        response = opener.open(request, timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        if response.status != expected:
            raise RuntimeError(f"Core {path} returned HTTP {response.status}, expected {expected}")
        if expected != 200:
            return None
        data = response.read(MAX_RESPONSE + 1)
    if len(data) > MAX_RESPONSE:
        raise ValueError(f"Core {path} response exceeds size limit")
    try:
        return json.loads(data)
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError(f"Core {path} returned invalid JSON") from error


def _core() -> None:
    backup_installation._regular(backup_installation.ETC / "core.env")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), register_local_agent.NoRedirect()
    )
    ready = _response(opener, "/api/v1/health/ready", 200)
    if (
        not isinstance(ready, dict)
        or ready.get("status") != "ready"
        or ready.get("api_version") != "v1"
    ):
        raise RuntimeError("Core returned an invalid readiness response")
    _response(opener, "/api/v1/agents", 401)


def check(mode: str) -> tuple[bool, list[str]]:
    if os.name != "posix" or os.geteuid() != 0:
        raise RuntimeError("running service check requires Linux root")
    if mode not in {"standalone", "agent-only"}:
        raise ValueError("expected deployment mode must be standalone or agent-only")
    etc, data = backup_installation.ETC, backup_installation.DATA
    for path in (etc, etc / "agent", data, data / "agent"):
        maintenance_backup._trusted_directory(path)
    configs = list((etc / "agent").iterdir())
    buffers = list((data / "agent").iterdir())
    ids = {path.name for path in configs}
    if (
        not ids
        or ids != {path.name for path in buffers}
        or any(not path.is_dir() or path.is_symlink() for path in (*configs, *buffers))
        or any(not configure.IDENTIFIER.fullmatch(item) or item in {".", ".."} for item in ids)
    ):
        raise ValueError("Agent configuration and data directories must match")
    agents = sorted(ids)
    units = [backup_installation._agent_unit(agent) for agent in agents]
    if maintenance_backup._loaded_agents() - set(units):
        raise RuntimeError("unexpected loaded Agent service")
    agent_template = maintenance_backup._validate_template(install_fresh.AGENT_UNIT)
    core_env, core_data = etc / "core.env", data / "core"
    has_core = core_env.exists() or core_env.is_symlink()
    if has_core != (core_data.exists() or core_data.is_symlink()):
        raise ValueError("Core configuration and data directories do not match")
    if has_core != (mode == "standalone"):
        raise ValueError(f"local Core presence does not match expected {mode} mode")
    if has_core:
        backup_installation._directory(core_data)
        core_template = maintenance_backup._validate_template(install_fresh.CORE_UNIT)
        _active(install_fresh.CORE_UNIT, core_template)
        _core()
        _active(install_fresh.CORE_UNIT, core_template)
    for unit in units:
        _active(unit, agent_template)
    return has_core, agents


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("standalone", "agent-only"), required=True)
    args = parser.parse_args(argv)
    try:
        core, agents = check(args.mode)
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
        http.client.HTTPException,
    ) as error:
        print(f"Running service check failed: {error}", file=sys.stderr)
        print(
            "No services were changed. Inspect service state and logs before proceeding.",
            file=sys.stderr,
        )
        return 1
    print(f"Local service checks passed for {len(agents)} Agent(s).")
    if core:
        print("Local Core readiness and unauthenticated access checks passed.")
    else:
        print("No local Core was checked.")
    print("Agent connectivity, synchronization and printer health were not checked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
