import asyncio
import json
import os
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from stunsail_agent.cli import _core_ssl_context
from stunsail_agent.config import AgentConfig
from stunsail_agent.store import AgentStore, utcnow
from stunsail_agent.sync import Syncer
from stunsail_moonraker import MoonrakerEndpoint


def openssl_path():
    binary = shutil.which("openssl")
    if binary:
        return binary
    git_openssl = (
        Path(os.environ.get("ProgramFiles", "C:\\Program Files"))
        / "Git"
        / "usr"
        / "bin"
        / "openssl.exe"
    )
    if git_openssl.is_file():
        return str(git_openssl)
    pytest.skip("OpenSSL is required for the local TLS integration test")


def test_agent_sync_checks_certificate_and_hostname(tmp_path):
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        [
            openssl_path(),
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
        ],
        check=True,
        capture_output=True,
    )

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            response = json.dumps(
                {
                    "accepted_event_ids": [e["event_id"] for e in body["events"]],
                    "accepted_sample_sequences": [s["sequence"] for s in body["samples"]],
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert, key)
    server.socket = server_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    store = AgentStore(":memory:")
    store.append_sample(utcnow(), None, "ok", {})
    config = AgentConfig(
        buffer_path=":memory:",
        moonraker=MoonrakerEndpoint("http://localhost:7125"),
        instance_name="test",
        core_ca_file=str(cert),
    )

    async def sync(host, context):
        async with httpx.AsyncClient(
            base_url=f"https://{host}:{server.server_port}/api/v1",
            verify=context,
            trust_env=False,
        ) as client:
            await Syncer(store, "test", client).sync_once()

    try:
        with pytest.raises(httpx.ConnectError):
            asyncio.run(sync("localhost", ssl.create_default_context()))
        assert store.pending_counts() == (0, 1)
        with pytest.raises(httpx.ConnectError):
            asyncio.run(sync("127.0.0.1", _core_ssl_context(config)))
        assert store.pending_counts() == (0, 1)
        asyncio.run(sync("localhost", _core_ssl_context(config)))
        assert store.pending_counts() == (0, 0)
    finally:
        store.close()
        server.shutdown()
        thread.join()
        server.server_close()
