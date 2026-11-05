"""Collector: keeps one Moonraker session observed and persisted."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import logging
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any

from stunsail_moonraker import MoonrakerError, backoff_delays

from .jobs import Emitted, JobTracker
from .source import Discovery, StatusSource, StatusUpdate
from .store import AgentStore, utcnow

log = logging.getLogger("stunsail.agent")

GAP_FACTOR = 3


def merge_status(cache: dict[str, Any], delta: dict[str, Any]) -> None:
    for name, fields in delta.items():
        if isinstance(fields, dict):
            cache.setdefault(name, {}).update(fields)
        else:
            cache[name] = fields


class Collector:
    def __init__(
        self,
        store: AgentStore,
        agent_id: str,
        *,
        sample_interval: float = 1.0,
        clock: Callable[[], datetime] = utcnow,
        delays: Callable[[], Iterator[float]] = backoff_delays,
    ) -> None:
        self._store = store
        self._agent_id = agent_id
        self._interval = sample_interval
        self._clock = clock
        self._delays = delays
        self._tracker = JobTracker(store)
        self._cache: dict[str, Any] = {}
        self._klippy_ready = False
        self._established = False

    def _emit(self, event_type: str, payload: dict[str, Any], at: datetime | None = None) -> None:
        self._store.append_event(self._agent_id, event_type, at or self._clock(), payload)

    def _emit_all(self, emitted: list[Emitted], at: datetime) -> None:
        for event_type, payload in emitted:
            self._emit(event_type, payload, at)

    def _record_sample(self) -> None:
        if not self._klippy_ready or not self._cache:
            return
        active = self._store.active_job()
        self._store.append_sample(
            self._clock(),
            active["job_id"] if active else None,
            "ok",
            {"status": copy.deepcopy(self._cache)},
        )

    async def _sampler(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            self._record_sample()

    def _note_gap(self, now: datetime) -> None:
        previous = self._store.last_sample_time()
        if previous and (now - previous).total_seconds() > GAP_FACTOR * self._interval:
            self._emit(
                "telemetry.gap",
                {
                    "gap_start": previous.isoformat(),
                    "gap_end": now.isoformat(),
                    "reason": "no_samples",
                },
                now,
            )

    async def _establish(self, source: StatusSource) -> Discovery:
        discovery = await source.open()
        snapshot = await source.snapshot()
        now = self._clock()
        self._cache = {}
        merge_status(self._cache, snapshot)
        self._klippy_ready = True
        self._emit(
            "connection.established",
            {
                "klippy_state": discovery.printer_info.get("state"),
                "software_version": discovery.printer_info.get("software_version"),
                "moonraker_version": discovery.server_info.get("moonraker_version"),
                "available_objects": discovery.objects,
                "observed_objects": discovery.observed,
            },
            now,
        )
        self._note_gap(now)
        try:
            history = await source.history(10)
        except MoonrakerError:
            history = []
        self._emit_all(self._tracker.reconcile(self._cache, history, now), now)
        self._emit_all(self._tracker.observe(self._cache, now), now)
        self._established = True
        return discovery

    def _apply(self, update: StatusUpdate) -> None:
        now = self._clock()
        if update.kind == "klippy":
            self._klippy_ready = update.detail == "klippy.ready"
            self._emit(update.detail or "klippy.unknown", {}, now)
            return
        if update.kind == "snapshot":
            self._cache = {}
            self._klippy_ready = True
        merge_status(self._cache, update.status)
        self._emit_all(self._tracker.observe(self._cache, now), now)

    async def run_once(self, source: StatusSource) -> None:
        """Observe one Moonraker session until it fails; always releases the source."""
        sampler: asyncio.Task[None] | None = None
        try:
            await self._establish(source)
            sampler = asyncio.create_task(self._sampler())
            async for update in source.updates():
                self._apply(update)
        finally:
            if sampler is not None:
                sampler.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await sampler
            await source.close()

    async def run_forever(
        self, source_factory: Callable[[], StatusSource], stop: asyncio.Event
    ) -> None:
        delays = self._delays()
        while not stop.is_set():
            session = asyncio.create_task(self.run_once(source_factory()))
            stopper = asyncio.create_task(stop.wait())
            await asyncio.wait({session, stopper}, return_when=asyncio.FIRST_COMPLETED)
            stopper.cancel()
            if stop.is_set():
                session.cancel()
                with contextlib.suppress(asyncio.CancelledError, MoonrakerError, OSError):
                    await session
                return
            try:
                session.result()
            except (MoonrakerError, OSError) as exc:
                log.warning("Moonraker session ended: %s", exc)
                if self._established:
                    self._emit("connection.lost", {"reason": str(exc)})
                    self._established = False
                    delays = self._delays()
                self._klippy_ready = False
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), next(delays))
