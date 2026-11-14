import asyncio
import importlib.util
import json
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
import uvicorn

INSTALLER = Path(__file__).resolve().parents[2] / "deployment" / "installer"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, INSTALLER / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


https_frontend = _load("https_frontend", "https_frontend.py")
generator = _load("generate_ca_and_cert", "generate_ca_and_cert.py")


class _EchoHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _read_body(self):
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            chunks = []
            while True:
                size = int(self.rfile.readline().strip() or b"0", 16)
                if size == 0:
                    self.rfile.readline()
                    break
                chunks.append(self.rfile.read(size))
                self.rfile.readline()
            return b"".join(chunks)
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _handle(self):
        body = self._read_body()
        status = 404 if self.path.split("?")[0] == "/not-found" else 200
        payload = json.dumps(
            {
                "method": self.command,
                "path": self.path,
                "headers": {key.lower(): value for key, value in self.headers.items()},
                "body": body.decode("utf-8", "replace"),
            }
        ).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Upstream", "stub")
        self.send_header("Set-Cookie", "a=1")
        self.send_header("Set-Cookie", "b=2")
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _handle
    do_POST = _handle
    do_PUT = _handle
    do_DELETE = _handle

    def log_message(self, *args):
        pass


@pytest.fixture
def stub_core():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EchoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def frontend(stub_core, monkeypatch):
    monkeypatch.setattr(https_frontend, "CORE_BASE_URL", stub_core)
    return https_frontend


@pytest.fixture(scope="module")
def tls_material(tmp_path_factory):
    ca_cert, ca_key = generator.generate_ca()
    server_cert, server_key = generator.generate_server_cert(ca_cert, ca_key, ["127.0.0.1"], [])
    other_ca_cert, _ = generator.generate_ca()
    directory = tmp_path_factory.mktemp("tls")
    (directory / "ca.crt").write_bytes(generator.certificate_pem(ca_cert))
    (directory / "other-ca.crt").write_bytes(generator.certificate_pem(other_ca_cert))
    (directory / "server.crt").write_bytes(generator.certificate_pem(server_cert))
    (directory / "server.key").write_bytes(generator.private_key_pem(server_key))
    return directory


def call(module, method, path, **kwargs):
    async def run():
        transport = httpx.ASGITransport(app=module.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://frontend.test"
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def test_query_string_is_forwarded(frontend):
    response = call(frontend, "GET", "/api/v1/jobs?limit=5&state=completed")
    assert response.status_code == 200
    assert response.json()["path"] == "/api/v1/jobs?limit=5&state=completed"


def test_post_body_is_forwarded(frontend):
    response = call(frontend, "POST", "/api/v1/agents/printer-1/sync", json={"jobs": [1, 2]})
    echoed = response.json()
    assert echoed["method"] == "POST"
    assert echoed["path"] == "/api/v1/agents/printer-1/sync"
    assert json.loads(echoed["body"]) == {"jobs": [1, 2]}


def test_large_body_is_streamed(frontend):
    blob = "x" * 65536
    response = call(frontend, "POST", "/api/v1/agents/printer-1/sync", content=blob)
    assert response.json()["body"] == blob


def test_headers_forwarded_hop_by_hop_stripped(frontend, stub_core):
    response = call(
        frontend,
        "GET",
        "/api/v1/health/ready",
        headers={
            "X-Custom": "keep",
            "Keep-Alive": "timeout=5",
            "Proxy-Authorization": "Basic secret",
            "X-Forwarded-For": "203.0.113.9",
            "X-Forwarded-Proto": "http",
        },
    )
    echoed = response.json()["headers"]
    assert echoed["x-custom"] == "keep"
    assert "keep-alive" not in echoed
    assert "proxy-authorization" not in echoed
    assert echoed["host"] == stub_core.split("//")[1]
    assert echoed["x-forwarded-for"] == "203.0.113.9, 127.0.0.1"
    assert echoed["x-forwarded-proto"] == "https"


def test_upstream_status_and_duplicate_response_headers_forwarded(frontend):
    response = call(frontend, "GET", "/not-found")
    assert response.status_code == 404
    assert response.headers["x-upstream"] == "stub"
    assert response.headers.get_list("set-cookie") == ["a=1", "b=2"]


def test_502_when_core_unreachable(monkeypatch):
    monkeypatch.setattr(https_frontend, "CORE_BASE_URL", "http://127.0.0.1:9")
    response = call(https_frontend, "GET", "/api/v1/health/ready")
    assert response.status_code == 502
    assert "unreachable" in response.text


def test_tls_handshake_with_generated_certs_and_wrong_ca_rejected(
    frontend, tls_material, stub_core
):
    config = uvicorn.Config(
        frontend.app,
        host="127.0.0.1",
        port=0,
        ssl_certfile=str(tls_material / "server.crt"),
        ssl_keyfile=str(tls_material / "server.key"),
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started, "uvicorn TLS frontend did not start"
        port = server.servers[0].sockets[0].getsockname()[1]
        url = f"https://127.0.0.1:{port}/api/v1/health/ready?via=tls"

        trusted_ca = ssl.create_default_context(cafile=str(tls_material / "ca.crt"))
        untrusted_ca = ssl.create_default_context(cafile=str(tls_material / "other-ca.crt"))

        async def trusted():
            async with httpx.AsyncClient(verify=trusted_ca) as client:
                return await client.get(url)

        response = asyncio.run(trusted())
        assert response.status_code == 200
        assert response.json()["path"] == "/api/v1/health/ready?via=tls"

        async def untrusted():
            async with httpx.AsyncClient(verify=untrusted_ca) as client:
                await client.get(url)

        with pytest.raises(httpx.ConnectError):
            asyncio.run(untrusted())
    finally:
        server.should_exit = True
        thread.join(timeout=15)
