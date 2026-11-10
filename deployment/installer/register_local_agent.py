#!/usr/bin/env python3
"""Register an initial standalone Agent without printing its credentials."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path

from configure import IDENTIFIER, TOKEN

CORE_URL = "http://127.0.0.1:8000/api/v1/agents"
EMPTY_ENV = "STUNSAIL_AGENT_TOKEN=\n"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_private(path: Path) -> tuple[str, os.stat_result]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError(f"expected a regular, singly linked private file: {path}")
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError(f"file must be owned by the current user with mode 0600: {path}")
    with path.open("r", encoding="utf-8") as stream:
        return stream.read(), info


def register(bundle: Path) -> None:
    if os.name != "posix":
        raise RuntimeError("local Agent registration requires POSIX file permissions")
    directory = bundle.lstat()
    if (
        not stat.S_ISDIR(directory.st_mode)
        or directory.st_uid != os.geteuid()
        or stat.S_IMODE(directory.st_mode) != 0o700
    ):
        raise ValueError("bundle must be a current-user-owned directory with mode 0700")
    raw_config, _ = read_private(bundle / "agent.yaml")
    config = json.loads(raw_config)
    if not isinstance(config, dict) or config.get("deployment_mode") != "standalone":
        raise ValueError("bundle must contain a standalone configuration")
    agent = config.get("agent")
    if not isinstance(agent, dict):
        raise ValueError("bundle must contain an Agent configuration")
    agent_id = agent.get("agent_id")
    if (
        not isinstance(agent_id, str)
        or not IDENTIFIER.fullmatch(agent_id)
        or agent_id in {".", ".."}
        or agent.get("core_url") != "http://127.0.0.1:8000"
    ):
        raise ValueError("invalid Agent ID or standalone Core URL")
    core_env, _ = read_private(bundle / "core.env")
    admin_lines = [
        line for line in core_env.splitlines() if line.startswith("STUNSAIL_ADMIN_TOKEN=")
    ]
    if len(admin_lines) != 1 or not TOKEN.fullmatch(admin_lines[0].partition("=")[2]):
        raise ValueError("core.env must contain a valid Core admin token")
    env_path = bundle / "agent.env"
    existing, original = read_private(env_path)
    if existing != EMPTY_ENV:
        raise ValueError("agent.env must contain only an empty Agent token; refusing to overwrite")

    pending = bundle / ".agent.env.pending"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(pending, flags, 0o600)
    received = False
    try:
        body = json.dumps({"agent_id": agent_id, "name": agent_id}).encode()
        request = urllib.request.Request(
            CORE_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + admin_lines[0].partition("=")[2],
            },
            method="POST",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=10) as response:
            if response.status != 201:
                raise ValueError(f"unexpected registration status: {response.status}")
            data = json.loads(response.read(65537))
        if (
            not isinstance(data, dict)
            or data.get("agent_id") != agent_id
            or not isinstance(data.get("token"), str)
            or not TOKEN.fullmatch(data["token"])
        ):
            raise ValueError("Core returned an invalid registration response")
        received = True
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            fd = -1
            stream.write(f"STUNSAIL_AGENT_TOKEN={data['token']}\n")
            stream.flush()
            os.fsync(stream.fileno())
        current, info = read_private(env_path)
        if current != EMPTY_ENV or (info.st_dev, info.st_ino) != (original.st_dev, original.st_ino):
            raise RuntimeError(
                "agent.env changed during registration; token retained in pending file"
            )
        os.replace(pending, env_path)
        directory_fd = os.open(bundle, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if fd != -1:
            os.close(fd)
        if not received:
            pending.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="private standalone configuration directory")
    args = parser.parse_args(argv)
    try:
        register(args.bundle)
    except (
        OSError,
        ValueError,
        RuntimeError,
        urllib.error.URLError,
        http.client.HTTPException,
    ) as error:
        print(f"Agent registration failed: {error}", file=sys.stderr)
        print(
            "Core may have registered the Agent even if the request failed. Check Core before "
            "retrying; if necessary reset its token. Inspect any .agent.env.pending securely.",
            file=sys.stderr,
        )
        return 1
    print("Agent registered; its token was stored in agent.env. No services were changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
