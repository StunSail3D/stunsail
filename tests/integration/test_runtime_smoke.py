import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deployment" / "installer" / "runtime_smoke.py"
spec = importlib.util.spec_from_file_location("runtime_smoke", SCRIPT)
assert spec and spec.loader
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


@pytest.mark.parametrize(
    ("readiness", "agents", "denied", "error"),
    [
        (b'{"status":"ready","api_version":"v1"}', b"[]", 401, None),
        (b'{"status":"unavailable","api_version":"v1"}', b"[]", 401, "readiness"),
        (b"not-json", b"[]", 401, "invalid JSON"),
        (b'{"status":"ready","api_version":"v1"}', b"{}", 401, "Agent list"),
        (b'{"status":"ready","api_version":"v1"}', b"[]", 200, "expected 401"),
    ],
)
def test_smoke_checks_response_status_and_shape(monkeypatch, readiness, agents, denied, error):
    class App:
        state = SimpleNamespace(session_factory=None)

        async def __call__(self, scope, receive, send):
            token = (b"authorization", b"Bearer ephemeral") in scope["headers"]
            if scope["path"].endswith("ready"):
                status, body = 200, readiness
            elif token:
                status, body = 200, agents
            else:
                status, body = denied, b"{}"
            await send({"type": "http.response.start", "status": status, "headers": []})
            await send({"type": "http.response.body", "body": body})

    monkeypatch.setenv("STUNSAIL_ADMIN_TOKEN", "ephemeral")
    monkeypatch.setattr(smoke, "create_app", App)
    if error:
        with pytest.raises(RuntimeError, match=error):
            asyncio.run(smoke._check())
    else:
        asyncio.run(smoke._check())
