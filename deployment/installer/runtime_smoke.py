#!/usr/bin/env python3
"""Check Core readiness and admin authentication in an isolated runtime process."""

from __future__ import annotations

import asyncio
import json
import os

from stunsail_api.app import create_app


async def _request(app, path: str, token: str | None) -> tuple[int, bytes]:
    headers = []
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode("ascii")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": headers,
        "server": ("localhost", 80),
        "client": ("localhost", 1),
        "root_path": "",
    }
    messages = []
    received = False

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.Event().wait()
        raise RuntimeError("unexpected resumed receive")

    async def send(message):
        messages.append(message)

    await asyncio.wait_for(app(scope, receive, send), timeout=10)
    starts = [message for message in messages if message["type"] == "http.response.start"]
    if len(starts) != 1:
        raise RuntimeError("Core smoke test received an invalid response")
    body = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    return starts[0]["status"], body


async def _check() -> None:
    token = os.environ["STUNSAIL_ADMIN_TOKEN"]
    app = create_app()
    try:
        for path, credential, expected in (
            ("/api/v1/health/ready", None, 200),
            ("/api/v1/agents", None, 401),
            ("/api/v1/agents", token, 200),
        ):
            status, body = await _request(app, path, credential)
            if status != expected:
                raise RuntimeError(f"Core smoke test {path} returned {status}, expected {expected}")
            if status == 200:
                try:
                    payload = json.loads(body)
                except (ValueError, UnicodeDecodeError) as error:
                    raise RuntimeError(f"Core smoke test {path} returned invalid JSON") from error
                if path == "/api/v1/health/ready" and (
                    not isinstance(payload, dict)
                    or payload.get("status") != "ready"
                    or payload.get("api_version") != "v1"
                ):
                    raise RuntimeError("Core smoke test returned an invalid readiness response")
                if path == "/api/v1/agents" and not isinstance(payload, list):
                    raise RuntimeError("Core smoke test returned an invalid Agent list")
    finally:
        factory = app.state.session_factory
        if factory is not None:
            factory.kw["bind"].dispose()


if __name__ == "__main__":
    asyncio.run(_check())
    print("Candidate Core readiness and admin authentication checks passed.")
