import shutil
import subprocess
from configparser import ConfigParser
from pathlib import Path

import pytest

UNITS = Path(__file__).resolve().parents[2] / "deployment" / "systemd"


def read_unit(name):
    unit = ConfigParser(interpolation=None)
    unit.optionxform = str
    unit.read(UNITS / name, encoding="utf-8")
    return unit


def test_core_is_loopback_bound_and_does_not_run_migrations():
    service = read_unit("stunsail-core.service")["Service"]
    assert service["User"] == "stunsail-core"
    assert service["EnvironmentFile"] == "/etc/stunsail/core.env"
    assert "--host 127.0.0.1 --port 8000" in service["ExecStart"]
    assert "ExecStartPre" not in service
    assert service["StateDirectory"] == "stunsail/core"
    assert service["ProtectSystem"] == "strict"


def test_agent_instances_use_separate_configuration_and_buffers():
    service = read_unit("stunsail-agent@.service")["Service"]
    assert service["User"] == "stunsail-agent"
    assert service["EnvironmentFile"] == "/etc/stunsail/agent/%I/agent.env"
    assert "--config /etc/stunsail/agent/%I/agent.yaml" in service["ExecStart"]
    assert service["StateDirectory"] == "stunsail/agent/%I"
    assert service["UMask"] == "0077"
    assert service["ProtectSystem"] == "strict"


@pytest.mark.skipif(shutil.which("systemd-escape") is None, reason="systemd-escape is unavailable")
@pytest.mark.parametrize("agent_id", ["printer-1", ".printer", "printer_1", "a.b-c"])
def test_agent_instance_name_round_trips(agent_id):
    unit = subprocess.check_output(
        ["systemd-escape", "--template=stunsail-agent@.service", "--", agent_id], text=True
    ).strip()
    escaped = unit.removeprefix("stunsail-agent@").removesuffix(".service")
    unescaped = subprocess.check_output(
        ["systemd-escape", "--unescape", "--", escaped], text=True
    ).strip()
    assert unescaped == agent_id


def test_frontend_is_unprivileged_tls_proxy_to_loopback_core():
    unit = read_unit("stunsail-frontend.service")
    service = unit["Service"]
    assert service["User"] == "stunsail-core"
    assert service["Group"] == "stunsail-core"
    assert "EnvironmentFile" not in service
    assert "StateDirectory" not in service
    exec_start = service["ExecStart"]
    assert "/opt/stunsail/current/.venv/bin/uvicorn" in exec_start
    assert "--app-dir /opt/stunsail/current/deployment/installer" in exec_start
    assert "https_frontend:app" in exec_start
    assert "--host 0.0.0.0 --port 8443" in exec_start
    assert "--ssl-certfile /etc/stunsail/certs/server.crt" in exec_start
    assert "--ssl-keyfile /etc/stunsail/certs/server.key" in exec_start
    assert service["UMask"] == "0077"
    assert service["NoNewPrivileges"] == "true"
    assert service["PrivateTmp"] == "true"
    assert service["ProtectHome"] == "true"
    assert service["ProtectSystem"] == "strict"
    assert "stunsail-core.service" in unit["Unit"]["After"]
    assert unit["Install"]["WantedBy"] == "multi-user.target"
