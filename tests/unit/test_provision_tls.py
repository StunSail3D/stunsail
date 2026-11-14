import ipaddress
import json
import os
import ssl
import sys
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

INSTALLER = Path(__file__).resolve().parents[2] / "deployment" / "installer"
if os.name == "posix":
    sys.path.insert(0, str(INSTALLER))
    try:
        import generate_ca_and_cert
        import install_fresh
        import provision_tls
    finally:
        sys.path.remove(str(INSTALLER))

pytestmark = pytest.mark.skipif(os.name != "posix", reason="requires POSIX installation tools")


@pytest.fixture(scope="module")
def ca():
    return generate_ca_and_cert.generate_ca()


def write_pem(directory, cert, key, ca_cert):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "server.crt").write_bytes(generate_ca_and_cert.certificate_pem(cert))
    (directory / "server.key").write_bytes(generate_ca_and_cert.private_key_pem(key))
    (directory / "ca.crt").write_bytes(generate_ca_and_cert.certificate_pem(ca_cert))
    return directory / "server.crt", directory / "server.key", directory / "ca.crt"


@pytest.fixture
def inputs(tmp_path, ca):
    ca_cert, ca_key = ca
    cert, key = generate_ca_and_cert.generate_server_cert(ca_cert, ca_key, ["192.0.2.10"], [])
    return write_pem(tmp_path / "inputs", cert, key, ca_cert)


@pytest.fixture
def host(tmp_path, monkeypatch):
    root = tmp_path / "host"
    opt, etc, units = root / "opt", root / "etc", root / "units"
    release = opt / "releases" / "initial"
    unit_dir = release / "deployment" / "systemd"
    unit_dir.mkdir(parents=True)
    (unit_dir / provision_tls.FRONTEND_UNIT).write_text("[Unit]\nDescription=frontend\n")
    (opt / "current").symlink_to(release, target_is_directory=True)
    etc.mkdir(parents=True)
    units.mkdir(parents=True)
    monkeypatch.setattr(install_fresh, "OPT", opt)
    monkeypatch.setattr(install_fresh, "ETC", etc)
    monkeypatch.setattr(install_fresh, "UNITS", units)
    monkeypatch.setattr(
        provision_tls.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=0, pw_gid=0)
    )
    events = []
    monkeypatch.setattr(install_fresh, "_run", lambda *command: events.append(command))
    monkeypatch.setattr(
        provision_tls, "_ready_https", lambda ip, ca, **kw: events.append(("ready", ip, str(ca)))
    )
    return SimpleNamespace(opt=opt, etc=etc, units=units, release=release, events=events)


def test_provision_installs_certs_and_unit_and_enables(host, inputs):
    cert, key, ca = inputs
    provision_tls.provision(cert, key, ca, "192.0.2.10")
    certs = host.etc / "certs"
    assert certs.stat().st_mode & 0o777 == 0o750
    assert (certs / "server.crt").stat().st_mode & 0o777 == 0o644
    assert (certs / "ca.crt").stat().st_mode & 0o777 == 0o644
    assert (certs / "server.key").stat().st_mode & 0o777 == 0o640
    assert (certs / "server.crt").read_bytes() == cert.read_bytes()
    assert (certs / "server.key").read_bytes() == key.read_bytes()
    installed = host.units / provision_tls.FRONTEND_UNIT
    assert installed.read_text() == "[Unit]\nDescription=frontend\n"
    assert ("systemctl", "daemon-reload") in host.events
    assert ("systemctl", "enable", "--now", provision_tls.FRONTEND_UNIT) in host.events
    assert ("ready", "192.0.2.10", str(certs / "ca.crt")) in host.events


def test_provision_requires_root(host, inputs, monkeypatch):
    monkeypatch.setattr(provision_tls.os, "geteuid", lambda: 1000)
    with pytest.raises(RuntimeError, match="Linux root"):
        provision_tls.provision(*inputs, "192.0.2.10")
    assert not (host.etc / "certs").exists()


def test_provision_refuses_existing_certs_dir(host, inputs):
    (host.etc / "certs").mkdir()
    with pytest.raises(FileExistsError):
        provision_tls.provision(*inputs, "192.0.2.10")
    assert not (host.units / provision_tls.FRONTEND_UNIT).exists()


def test_provision_refuses_existing_unit(host, inputs):
    (host.units / provision_tls.FRONTEND_UNIT).write_text("existing")
    with pytest.raises(FileExistsError):
        provision_tls.provision(*inputs, "192.0.2.10")
    assert (host.units / provision_tls.FRONTEND_UNIT).read_text() == "existing"


def test_provision_rejects_mismatched_key(host, inputs, ca, tmp_path):
    cert, _, ca_path = inputs
    _, other_key = generate_ca_and_cert.generate_server_cert(ca[0], ca[1], ["192.0.2.11"], [])
    bad_key = tmp_path / "bad.key"
    bad_key.write_bytes(generate_ca_and_cert.private_key_pem(other_key))
    with pytest.raises(ssl.SSLError):
        provision_tls.provision(cert, bad_key, ca_path, "192.0.2.10")
    assert not (host.etc / "certs").exists()


def test_provision_rejects_private_key_in_ca(host, inputs, ca):
    cert, key, ca_path = inputs
    ca_path.write_bytes(ca_path.read_bytes() + generate_ca_and_cert.private_key_pem(ca[1]))
    with pytest.raises(ValueError, match="private key"):
        provision_tls.provision(cert, key, ca_path, "192.0.2.10")
    assert not (host.etc / "certs").exists()


def test_provision_rejects_invalid_ip(host, inputs):
    with pytest.raises(ValueError):
        provision_tls.provision(*inputs, "999.1.1.1")
    assert not (host.etc / "certs").exists()


def test_provision_rejects_missing_input(host, inputs):
    cert, key, _ = inputs
    with pytest.raises(ValueError, match="regular file"):
        provision_tls.provision(cert, key, host.etc / "absent.crt", "192.0.2.10")


def test_provision_rejects_untrusted_release(host, inputs):
    (host.opt / "current").unlink()
    with pytest.raises(ValueError, match="installer-managed symlink"):
        provision_tls.provision(*inputs, "192.0.2.10")
    assert not (host.etc / "certs").exists()


def test_provision_rejects_missing_release_unit(host, inputs):
    (host.release / "deployment" / "systemd" / provision_tls.FRONTEND_UNIT).unlink()
    with pytest.raises(ValueError, match="missing a regular unit"):
        provision_tls.provision(*inputs, "192.0.2.10")
    assert not (host.etc / "certs").exists()


def issue(ca, ips, *, expired=False):
    ca_cert, ca_key = ca
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-server")]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=2))
        .not_valid_after(now - timedelta(days=1) if expired else now + timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(i)) for i in ips]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return cert, key


class _ReadyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = json.dumps({"status": "ready", "api_version": "v1"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class _QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        pass


@contextmanager
def tls_server(cert, key):
    server = _QuietServer(("127.0.0.1", 0), _ReadyHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_verify_https_accepts_valid_cert(tmp_path, ca):
    cert, key = issue(ca, ["127.0.0.1"])
    cert_path, key_path, ca_path = write_pem(tmp_path / "tls", cert, key, ca[0])
    with tls_server(cert_path, key_path) as port:
        body = provision_tls._verify_https("127.0.0.1", ca_path, port)
    assert body["status"] == "ready"


def test_verify_https_rejects_missing_san(tmp_path, ca):
    cert, key = issue(ca, ["192.0.2.10"])
    cert_path, key_path, ca_path = write_pem(tmp_path / "tls", cert, key, ca[0])
    with tls_server(cert_path, key_path) as port:
        with pytest.raises(OSError):
            provision_tls._verify_https("127.0.0.1", ca_path, port)


def test_verify_https_rejects_expired_cert(tmp_path, ca):
    cert, key = issue(ca, ["127.0.0.1"], expired=True)
    cert_path, key_path, ca_path = write_pem(tmp_path / "tls", cert, key, ca[0])
    with tls_server(cert_path, key_path) as port:
        with pytest.raises(OSError):
            provision_tls._verify_https("127.0.0.1", ca_path, port)


def test_verify_https_rejects_wrong_ca(tmp_path, ca):
    cert, key = issue(ca, ["127.0.0.1"])
    cert_path, key_path, _ = write_pem(tmp_path / "tls", cert, key, ca[0])
    other_ca_cert, _ = generate_ca_and_cert.generate_ca()
    other_ca = tmp_path / "other-ca.crt"
    other_ca.write_bytes(generate_ca_and_cert.certificate_pem(other_ca_cert))
    with tls_server(cert_path, key_path) as port:
        with pytest.raises(OSError):
            provision_tls._verify_https("127.0.0.1", other_ca, port)


def test_main_requires_confirm_flag(tmp_path):
    cert, key, ca = (tmp_path / name for name in ("server.crt", "server.key", "ca.crt"))
    with pytest.raises(SystemExit) as excinfo:
        provision_tls.main(
            [
                "--server-cert",
                str(cert),
                "--server-key",
                str(key),
                "--ca-bundle",
                str(ca),
                "--ip-address",
                "192.0.2.10",
            ]
        )
    assert excinfo.value.code == 2


def test_main_prints_onboarding(host, inputs, monkeypatch, capsys):
    monkeypatch.setattr(provision_tls, "provision", lambda *args: None)
    cert, key, ca = inputs
    code = provision_tls.main(
        [
            "--server-cert",
            str(cert),
            "--server-key",
            str(key),
            "--ca-bundle",
            str(ca),
            "--ip-address",
            "192.0.2.10",
            "--confirm-provision-tls",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "https://192.0.2.10:8443" in out
    assert "agent_only" in out
    assert "add_agent.py" in out
