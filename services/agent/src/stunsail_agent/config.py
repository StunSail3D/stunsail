"""Agent configuration loading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

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
    core_url: str | None = None
    core_token: str | None = None
    sync_interval: float = 5.0
    core_ca_file: str | None = None


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
    sync_interval = float(agent.get("sync_interval_seconds", 5.0))
    if sync_interval <= 0:
        raise ConfigError("sync_interval_seconds must be positive")
    core_url = agent.get("core_url")
    mode = raw.get("deployment_mode")
    if mode not in (None, "standalone", "agent_only"):
        raise ConfigError("deployment_mode must be standalone or agent_only")
    if mode == "agent_only" and not core_url:
        raise ConfigError("agent_only requires agent.core_url using HTTPS")
    if core_url:
        if not isinstance(core_url, str):
            raise ConfigError("agent.core_url must be an HTTP(S) URL")
        try:
            parsed = urlsplit(core_url)
            valid_port = parsed.port
        except ValueError as exc:
            raise ConfigError("agent.core_url is not a valid HTTP(S) URL") from exc
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or valid_port == 0
        ):
            raise ConfigError("agent.core_url must be an HTTP(S) URL without credentials or query")
        if mode == "agent_only" and parsed.scheme != "https":
            raise ConfigError("agent_only requires agent.core_url using HTTPS")
    ca_file = agent.get("core_ca_file")
    if ca_file is not None:
        if not isinstance(ca_file, str) or not ca_file:
            raise ConfigError("agent.core_ca_file must be a non-empty path")
        if not core_url or urlsplit(core_url).scheme != "https":
            raise ConfigError("agent.core_ca_file requires an HTTPS core_url")
    core_token = os.environ.get("STUNSAIL_AGENT_TOKEN") or None
    return AgentConfig(
        buffer_path=url[len(SQLITE_PREFIX) :],
        moonraker=MoonrakerEndpoint(
            instance["url"], os.environ.get(env_name) if env_name else None
        ),
        instance_name=instance.get("name", "default"),
        agent_id=agent.get("agent_id"),
        sample_interval=interval,
        core_url=core_url.rstrip("/") + "/api/v1" if core_url else None,
        core_token=core_token,
        sync_interval=sync_interval,
        core_ca_file=ca_file,
    )
