"""Durable local SQLite buffer for Agent events, samples and job state."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CONTRACT_VERSION = 1
ACTIVE_STATES = ("printing", "paused")

# Ordered, append-only. PRAGMA user_version records how many have been applied.
MIGRATIONS = [
    """
    CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE events (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL UNIQUE,
        event_type TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        payload TEXT NOT NULL,
        delivered INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE samples (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        observed_at TEXT NOT NULL,
        job_id TEXT,
        quality TEXT NOT NULL,
        payload TEXT NOT NULL
    );
    CREATE INDEX samples_observed_at ON samples (observed_at);
    CREATE TABLE jobs (
        job_id TEXT PRIMARY KEY,
        moonraker_job_id TEXT,
        filename TEXT,
        state TEXT NOT NULL,
        started_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        ended_at TEXT,
        end_source TEXT,
        filament_used_mm REAL,
        print_duration_s REAL,
        evidence TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX jobs_state ON jobs (state);
    """,
]


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds")


class AgentStore:
    def __init__(self, path: str | Path) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._migrate()

    def close(self) -> None:
        self._db.close()

    def _migrate(self) -> None:
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        for index in range(version, len(MIGRATIONS)):
            self._db.execute("BEGIN")
            for statement in MIGRATIONS[index].split(";"):
                if statement.strip():
                    self._db.execute(statement)
            self._db.execute(f"PRAGMA user_version = {index + 1}")
            self._db.execute("COMMIT")

    def get_value(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_value(self, key: str, value: str) -> None:
        self._db.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, value))

    def agent_id(self, configured: str | None = None) -> str:
        """Return a stable agent identity, generating and persisting one if needed."""
        if configured:
            self.set_value("agent_id", configured)
            return configured
        existing = self.get_value("agent_id")
        if existing:
            return existing
        generated = f"agent-{uuid.uuid4()}"
        self.set_value("agent_id", generated)
        return generated

    def append_event(
        self, agent_id: str, event_type: str, observed_at: datetime, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Persist an event and return it as a contract v1 envelope."""
        event_id = str(uuid.uuid4())
        cursor = self._db.execute(
            "INSERT INTO events (event_id, event_type, observed_at, payload) VALUES (?, ?, ?, ?)",
            (event_id, event_type, iso(observed_at), json.dumps(payload)),
        )
        return {
            "contract_version": CONTRACT_VERSION,
            "event_id": event_id,
            "agent_id": agent_id,
            "sequence": cursor.lastrowid,
            "event_type": event_type,
            "observed_at": iso(observed_at),
            "payload": payload,
        }

    def list_events(self, agent_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM events ORDER BY sequence LIMIT ?", (limit,)
        ).fetchall()
        return [
            {
                "contract_version": CONTRACT_VERSION,
                "event_id": row["event_id"],
                "agent_id": agent_id,
                "sequence": row["sequence"],
                "event_type": row["event_type"],
                "observed_at": row["observed_at"],
                "payload": json.loads(row["payload"]),
            }
            for row in rows
        ]

    def append_sample(
        self, observed_at: datetime, job_id: str | None, quality: str, payload: dict[str, Any]
    ) -> int:
        cursor = self._db.execute(
            "INSERT INTO samples (observed_at, job_id, quality, payload) VALUES (?, ?, ?, ?)",
            (iso(observed_at), job_id, quality, json.dumps(payload)),
        )
        return int(cursor.lastrowid or 0)

    def last_sample_time(self) -> datetime | None:
        row = self._db.execute("SELECT MAX(observed_at) AS t FROM samples").fetchone()
        return datetime.fromisoformat(row["t"]) if row["t"] else None

    def count(self, table: str) -> int:
        if table not in {"events", "samples", "jobs"}:
            raise ValueError(table)
        return int(self._db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def sample_count_for_job(self, job_id: str) -> int:
        row = self._db.execute("SELECT COUNT(*) FROM samples WHERE job_id = ?", (job_id,))
        return int(row.fetchone()[0])

    def job_samples(self, job_id: str) -> list[tuple[datetime, dict[str, Any]]]:
        rows = self._db.execute(
            "SELECT observed_at, payload FROM samples WHERE job_id = ? ORDER BY observed_at",
            (job_id,),
        ).fetchall()
        return [
            (datetime.fromisoformat(r["observed_at"]), json.loads(r["payload"])["status"])
            for r in rows
        ]

    def insert_job(self, job: dict[str, Any]) -> None:
        columns = ", ".join(job)
        marks = ", ".join("?" for _ in job)
        self._db.execute(f"INSERT INTO jobs ({columns}) VALUES ({marks})", tuple(job.values()))

    def update_job(self, job_id: str, **fields: Any) -> None:
        assignments = ", ".join(f"{name} = ?" for name in fields)
        self._db.execute(
            f"UPDATE jobs SET {assignments} WHERE job_id = ?", (*fields.values(), job_id)
        )

    def active_job(self) -> dict[str, Any] | None:
        marks = ", ".join("?" for _ in ACTIVE_STATES)
        row = self._db.execute(
            f"SELECT * FROM jobs WHERE state IN ({marks}) ORDER BY started_at DESC LIMIT 1",
            ACTIVE_STATES,
        ).fetchone()
        return dict(row) if row else None

    def list_jobs(self) -> list[dict[str, Any]]:
        rows = self._db.execute("SELECT * FROM jobs ORDER BY started_at").fetchall()
        return [dict(row) for row in rows]
