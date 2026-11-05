"""Agent configuration loading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from stunsail_moonraker import MoonrakerEndpoint

SQLITE_PREFIX = "sqlite:///"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class AgentConfig:
    buffer_path: str
    moonraker: MoonrakerEndpoint
    instance_name: str
    agent_id: str | None = None
    sample_interval: float = 1.0


def load_config(path: str | Path) -> AgentConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    agent = raw.get("agent")
    if not isinstance(agent, dict):
        raise ConfigError("missing 'agent' section")
    url = agent.get("local_buffer_url", "")
    if not url.startswith(SQLITE_PREFIX):
        raise ConfigError("agent.local_buffer_url must be a sqlite:/// URL")
    instances = (agent.get("moonraker") or {}).get("instances") or []
    if len(instances) != 1:
        raise ConfigError("exactly one agent.moonraker.instances entry is supported in Phase 1")
    instance = instances[0]
    if not instance.get("url"):
        raise ConfigError("moonraker instance requires 'url'")
    env_name = instance.get("credential_env")
    interval = float(agent.get("sample_interval_seconds", 1.0))
    if interval <= 0:
        raise ConfigError("sample_interval_seconds must be positive")
    return AgentConfig(
        buffer_path=url[len(SQLITE_PREFIX) :],
        moonraker=MoonrakerEndpoint(
            instance["url"], os.environ.get(env_name) if env_name else None
        ),
        instance_name=instance.get("name", "default"),
        agent_id=agent.get("agent_id"),
        sample_interval=interval,
    )
