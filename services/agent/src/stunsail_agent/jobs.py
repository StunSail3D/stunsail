"""Durable job state machine driven by observed Moonraker status."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from .store import ACTIVE_STATES, AgentStore, iso

# Moonraker print_stats.state -> terminal job state.
TERMINAL_FROM_PRINT_STATS = {"complete": "completed", "cancelled": "cancelled", "error": "error"}
# Moonraker history job status -> terminal job state; anything else is "interrupted".
TERMINAL_FROM_HISTORY = {"completed": "completed", "cancelled": "cancelled", "error": "error"}
EVENT_FOR_TERMINAL = {
    "completed": "job.completed",
    "cancelled": "job.cancelled",
    "error": "job.errored",
    "interrupted": "job.interrupted",
}

Emitted = tuple[str, dict[str, Any]]


def _print_stats(status: dict[str, Any]) -> dict[str, Any]:
    return status.get("print_stats") or {}


class JobTracker:
    """Turns status snapshots into persisted job transitions.

    Each terminal transition clears the active job, so a job is finalised exactly once.
    """

    def __init__(self, store: AgentStore) -> None:
        self._store = store

    def observe(self, status: dict[str, Any], now: datetime) -> list[Emitted]:
        stats = _print_stats(status)
        state = stats.get("state")
        if state is None:
            return []
        filename = stats.get("filename") or None
        emitted: list[Emitted] = []
        active = self._store.active_job()

        if active and state in ACTIVE_STATES and filename and filename != active["filename"]:
            emitted += self._finalise(active, "interrupted", now, "observed", status)
            active = None

        if active is None:
            if state in ACTIVE_STATES:
                emitted += self._start(state, filename, status, now)
            return emitted

        self._record_progress(active, status, now)
        if state == "printing" and active["state"] == "paused":
            self._store.update_job(active["job_id"], state="printing", updated_at=iso(now))
            emitted.append(("job.resumed", {"job_id": active["job_id"]}))
        elif state == "paused" and active["state"] == "printing":
            self._store.update_job(active["job_id"], state="paused", updated_at=iso(now))
            emitted.append(("job.paused", {"job_id": active["job_id"]}))
        elif state in TERMINAL_FROM_PRINT_STATS:
            emitted += self._finalise(
                active, TERMINAL_FROM_PRINT_STATS[state], now, "observed", status
            )
        elif state == "standby":
            emitted += self._finalise(active, "interrupted", now, "observed", status)
        return emitted

    def reconcile(
        self, status: dict[str, Any], history: list[dict[str, Any]], now: datetime
    ) -> list[Emitted]:
        """Resolve a job left active by a restart or outage against current state and history."""
        active = self._store.active_job()
        if active is None:
            return []
        stats = _print_stats(status)
        if stats.get("state") in ACTIVE_STATES and stats.get("filename") == active["filename"]:
            return []
        started_epoch = datetime.fromisoformat(active["started_at"]).timestamp()
        match = next(
            (
                job
                for job in history
                if job.get("filename") == active["filename"]
                and (job.get("end_time") or 0) >= started_epoch - 60
            ),
            None,
        )
        if match is None:
            return self._finalise(active, "interrupted", now, "reconcile", status)
        terminal = TERMINAL_FROM_HISTORY.get(match.get("status", ""), "interrupted")
        return self._finalise(active, terminal, now, "history", status, history_job=match)

    def _start(
        self, state: str, filename: str | None, status: dict[str, Any], now: datetime
    ) -> list[Emitted]:
        stats = _print_stats(status)
        job_id = str(uuid.uuid4())
        self._store.insert_job(
            {
                "job_id": job_id,
                "filename": filename,
                "state": state,
                "started_at": iso(now),
                "updated_at": iso(now),
                "filament_used_mm": stats.get("filament_used"),
                "print_duration_s": stats.get("print_duration"),
                "evidence": json.dumps({"start_print_stats": stats}),
            }
        )
        return [("job.started", {"job_id": job_id, "filename": filename, "state": state})]

    def _record_progress(
        self, active: dict[str, Any], status: dict[str, Any], now: datetime
    ) -> None:
        stats = _print_stats(status)
        self._store.update_job(
            active["job_id"],
            updated_at=iso(now),
            filament_used_mm=stats.get("filament_used", active["filament_used_mm"]),
            print_duration_s=stats.get("print_duration", active["print_duration_s"]),
        )

    def _finalise(
        self,
        active: dict[str, Any],
        terminal: str,
        now: datetime,
        source: str,
        status: dict[str, Any],
        history_job: dict[str, Any] | None = None,
    ) -> list[Emitted]:
        stats = _print_stats(status)
        evidence = json.loads(active["evidence"])
        evidence["end_print_stats"] = stats
        filament = active["filament_used_mm"]
        duration = active["print_duration_s"]
        if history_job is not None:
            evidence["history_job"] = history_job
            filament = history_job.get("filament_used", filament)
            duration = history_job.get("print_duration", duration)
        elif source == "observed":
            filament = stats.get("filament_used", filament)
            duration = stats.get("print_duration", duration)
        self._store.update_job(
            active["job_id"],
            state=terminal,
            updated_at=iso(now),
            ended_at=iso(now),
            end_source=source,
            filament_used_mm=filament,
            print_duration_s=duration,
            evidence=json.dumps(evidence),
        )
        payload = {
            "job_id": active["job_id"],
            "filename": active["filename"],
            "end_source": source,
            "filament_used_mm": filament,
            "print_duration_s": duration,
        }
        return [(EVENT_FOR_TERMINAL[terminal], payload)]
