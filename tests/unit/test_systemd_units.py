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
