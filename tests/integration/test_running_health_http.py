import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[2] / "deployment" / "installer"
if os.name == "posix":
    sys.path.insert(0, str(INSTALLER))
    try:
        import backup_installation
        import check_running
    finally:
        sys.path.remove(str(INSTALLER))

pytestmark = pytest.mark.skipif(os.name != "posix", reason="requires POSIX installation tools")

TOKEN = "test_token_123456789"


@pytest.fixture
def core_server(tmp_path, monkeypatch):
    requests = []
    replies = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers.get("Authorization")))
            if (self.path, self.headers.get("Authorization")) in replies:
                status, body, headers = replies[(self.path, self.headers.get("Authorization"))]
            elif self.path in replies:
                status, body, headers = replies[self.path]
            elif self.path == "/api/v1/health/ready":
                status, body, headers = 200, b'{"status":"ready","api_version":"v1"}', {}
            elif self.headers.get("Authorization") == f"Bearer {TOKEN}":
                status, body, headers = 200, b"[]", {}
            else:
                status, body, headers = 401, b"{}", {}
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    etc = tmp_path / "etc"
    etc.mkdir()
    env = etc / "core.env"
    env.write_text(f"STUNSAIL_ADMIN_TOKEN={TOKEN}\n")
    env.chmod(0o600)
    monkeypatch.setattr(backup_installation, "ETC", etc)
    monkeypatch.setattr(check_running, "CORE_URL", f"http://127.0.0.1:{server.server_port}")
    try:
        yield requests, replies
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_real_http_readiness_and_unauthenticated_denial(core_server):
    requests, _ = core_server
    check_running._core()
    assert requests == [
        ("/api/v1/health/ready", None),
        ("/api/v1/agents", None),
    ]


@pytest.mark.parametrize(
    "path, status, body, headers, message",
    [
        ("/api/v1/health/ready", 200, b'{"status":"ready"}', {}, "invalid readiness"),
        ("/api/v1/health/ready", 200, b"not-json", {}, "invalid JSON"),
        ("/api/v1/health/ready", 503, b"{}", {}, "HTTP 503"),
        ("/api/v1/agents", 200, b"[]", {}, "expected 401"),
        ("/api/v1/health/ready", 302, b"", {"Location": "http://127.0.0.1:1/"}, "HTTP 302"),
    ],
)
def test_rejects_unhealthy_or_redirected_responses(
    core_server, path, status, body, headers, message
):
    requests, replies = core_server
    replies[path] = status, body, headers
    with pytest.raises((ValueError, RuntimeError), match=message):
        check_running._core()
    assert all(authorization is None for _, authorization in requests)


def test_rejects_oversized_response(core_server, monkeypatch):
    _, replies = core_server
    monkeypatch.setattr(check_running, "MAX_RESPONSE", 32)
    replies["/api/v1/health/ready"] = 200, json.dumps({"padding": "x" * 50}).encode(), {}
    with pytest.raises(ValueError, match="size limit"):
        check_running._core()


def test_rejects_symlinked_core_config(core_server, tmp_path):
    env = tmp_path / "etc" / "core.env"
    env.rename(tmp_path / "original")
    env.symlink_to(tmp_path / "original")
    with pytest.raises(ValueError, match="regular file"):
        check_running._core()
    assert not core_server[0]


@pytest.mark.parametrize("migrated", [True, False])
def test_real_core_over_loopback(tmp_path, monkeypatch, migrated):
    from alembic import command
    from alembic.config import Config

    root = INSTALLER.parents[1]
    database = tmp_path / "core.db"
    monkeypatch.setenv("STUNSAIL_DATABASE_URL", f"sqlite:///{database}")
    monkeypatch.setenv("STUNSAIL_ADMIN_TOKEN", TOKEN)
    if migrated:
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "database" / "migrations"))
        command.upgrade(config, "head")
    etc = tmp_path / "etc"
    etc.mkdir()
    env_file = etc / "core.env"
    env_file.write_text(f"STUNSAIL_ADMIN_TOKEN={TOKEN}\n")
    env_file.chmod(0o600)
    monkeypatch.setattr(backup_installation, "ETC", etc)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        monkeypatch.setattr(check_running, "CORE_URL", f"http://127.0.0.1:{port}")
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "stunsail_api.main:app",
                "--fd",
                str(listener.fileno()),
                "--log-level",
                "error",
            ],
            pass_fds=(listener.fileno(),),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            deadline = time.monotonic() + 15
            while True:
                try:
                    check_running._core()
                    if not migrated:
                        pytest.fail("unmigrated Core unexpectedly passed")
                    break
                except RuntimeError as error:
                    if not migrated and "HTTP 503" in str(error):
                        break
                    raise
                except OSError as error:
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError("Core process did not become available") from error
                    time.sleep(0.1)
        finally:
            process.terminate()
            process.communicate(timeout=10)
