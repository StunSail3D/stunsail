"""Core settings and structured logging."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime

DEFAULT_DATABASE_URL = "sqlite:///./data/stunsail.db"
MIN_ADMIN_TOKEN_LENGTH = 16


class SettingsError(ValueError):
    pass


@dataclass(frozen=True)
class CoreSettings:
    database_url: str
    admin_token: str | None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> CoreSettings:
        env = dict(os.environ) if env is None else env
        url = env.get("STUNSAIL_DATABASE_URL", DEFAULT_DATABASE_URL)
        if not url.startswith(("sqlite:///", "postgresql")):
            raise SettingsError("STUNSAIL_DATABASE_URL must be a sqlite:/// or postgresql URL")
        token = env.get("STUNSAIL_ADMIN_TOKEN") or None
        if token is not None and len(token) < MIN_ADMIN_TOKEN_LENGTH:
            raise SettingsError(
                f"STUNSAIL_ADMIN_TOKEN must be at least {MIN_ADMIN_TOKEN_LENGTH} characters"
            )
        return cls(url, token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
