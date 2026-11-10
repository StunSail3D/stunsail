import importlib.util
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE = Path(__file__).resolve().parents[2] / "deployment" / "installer" / "preflight.py"
spec = importlib.util.spec_from_file_location("stunsail_preflight", MODULE)
assert spec and spec.loader
preflight = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = preflight
spec.loader.exec_module(preflight)


@pytest.mark.parametrize(
    ("release", "supported"),
    [
        ({"ID": "debian", "VERSION_ID": "12"}, True),
        ({"ID": "raspbian", "VERSION_ID": "12"}, True),
        ({"ID": "ubuntu", "VERSION_ID": "24.04"}, True),
        ({"ID": "armbian", "VERSION_ID": "26.0.0", "VERSION_CODENAME": "noble"}, True),
        ({"ID": "armbian", "VERSION_ID": "26.0.0", "VERSION_CODENAME": "bookworm"}, True),
        ({"ID": "armbian", "VERSION_ID": "26.0.0", "VERSION_CODENAME": "jammy"}, False),
        ({"ID": "ubuntu", "VERSION_ID": "22.04"}, False),
        ({"ID": "other", "ID_LIKE": "debian", "VERSION_ID": "12"}, False),
        ({}, False),
    ],
)
def test_platform_policy(release, supported):
    results = preflight.check_platform(release, "aarch64", "Linux")
    assert results[0].ok is supported
    assert results[1].ok
    assert not preflight.check_platform(release, "armv7l", "Linux")[1].ok
    assert not preflight.check_platform(release, "aarch64", "Windows")[0].ok


def test_trixie_explicitly_experimental_not_generally_supported():
    trixie = {"ID": "debian", "VERSION_ID": "13", "VERSION_CODENAME": "trixie"}
    check = preflight.check_platform(trixie, "aarch64", "Linux")[0]
    assert not check.ok and check.requires_confirmation
    assert "unvalidated" in check.detail
    assert not preflight.check_platform(trixie, "aarch64", "Windows")[0].requires_confirmation
    assert not preflight.check_platform(
        {"ID": "debian", "VERSION_ID": "14", "VERSION_CODENAME": "trixie"},
        "aarch64",
        "Linux",
    )[0].requires_confirmation


def test_reads_release_metadata_without_executing_it(tmp_path):
    release = tmp_path / "os-release"
    marker = tmp_path / "marker"
    release.write_text(
        f'ID="armbian"\nVERSION_ID=26.0.0\nVERSION_CODENAME=noble\nEVIL=$(touch {marker})\n',
        encoding="utf-8",
    )
    info = preflight.os_release(release)
    assert info["ID"] == "armbian"
    assert info["VERSION_CODENAME"] == "noble"
    assert not marker.exists()


def test_missing_release_and_disk_path_are_reported(tmp_path):
    checks = preflight.run_checks(tmp_path / "missing", tmp_path / "missing-release")
    errors = {item.name for item in checks if not item.ok}
    assert {"operating system", "OS metadata", "disk space"}.issubset(errors)


@pytest.mark.parametrize(
    ("free", "ok", "confirmation"),
    [
        (0, False, False),
        (preflight.MIN_INSTALL_BYTES - 1, False, False),
        (preflight.MIN_INSTALL_BYTES, False, True),
        (428 * 1024**2, False, True),
        (preflight.MIN_FREE_BYTES - 1, False, True),
        (preflight.MIN_FREE_BYTES, True, False),
    ],
)
def test_disk_space_thresholds(monkeypatch, free, ok, confirmation):
    monkeypatch.setattr(preflight.shutil, "disk_usage", lambda _: SimpleNamespace(free=free))
    result = preflight.check_disk_space(Path("/"))
    assert result.ok is ok
    assert result.requires_confirmation is confirmation
    assert "minimum 256 MiB" in result.detail
    assert "recommended 2048 MiB" in result.detail


def test_disk_error_never_allows_confirmation(monkeypatch):
    def fail(_):
        raise OSError("unavailable")

    monkeypatch.setattr(preflight.shutil, "disk_usage", fail)
    result = preflight.check_disk_space(Path("/"))
    assert not result.ok and not result.requires_confirmation
    assert "unavailable" in result.detail


def test_preflight_cli_reports_low_space_as_warning_and_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(
        preflight, "run_checks", lambda _: [preflight.Check("disk space", False, "low", True)]
    )
    assert preflight.main([]) == 1
    assert "WARN: disk space: low" in capsys.readouterr().out


def test_systemd_manager_check_reports_failures(monkeypatch):
    assert not preflight.check_systemd(None).ok
    monkeypatch.setattr(
        preflight.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="255\n"),
    )
    assert preflight.check_systemd("systemctl").ok

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 5)

    monkeypatch.setattr(preflight.subprocess, "run", timeout)
    assert not preflight.check_systemd("systemctl").ok


def test_core_port_conflict_is_reported(monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("address in use")

    monkeypatch.setattr(preflight.socket, "socket", unavailable)
    check = preflight.check_core_port()
    assert not check.ok
    assert "address in use" in check.detail


def test_moonraker_preflight_with_local_http_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/server/info":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"result": {"moonraker_version": "test"}}')
            else:
                self.send_error(404)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        assert preflight.check_http(base, moonraker=True).ok
        assert not preflight.check_http(base + "/wrong", moonraker=True).ok
        assert not preflight.check_http(base, moonraker=False).ok
        assert not preflight.check_http(base + "?secret=value", moonraker=True).ok
        assert not preflight.check_http("http://user:pass@localhost", moonraker=True).ok
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_moonraker_preflight_rejects_non_moonraker_response(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            return b'{"error": "not Moonraker"}'

    monkeypatch.setattr(preflight, "urlopen", lambda *args, **kwargs: Response())
    assert not preflight.check_http("http://localhost:7125", moonraker=True).ok
