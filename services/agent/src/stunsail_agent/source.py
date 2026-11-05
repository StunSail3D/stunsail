"""Adapter that turns the Moonraker client into the Agent's status source."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from stunsail_moonraker import MoonrakerEndpoint, MoonrakerHttpClient, MoonrakerWebSocket

ALWAYS_OBSERVED = ("print_stats", "virtual_sdcard", "extruder", "heater_bed")
FAN_PREFIXES = ("heater_fan", "controller_fan", "fan_generic", "temperature_fan")
KLIPPY_METHODS = {
    "notify_klippy_ready": "klippy.ready",
    "notify_klippy_shutdown": "klippy.shutdown",
    "notify_klippy_disconnected": "klippy.disconnected",
}


@dataclass
class Discovery:
    printer_info: dict[str, Any]
    server_info: dict[str, Any]
    objects: list[str]
    observed: list[str] = field(default_factory=list)


@dataclass
class StatusUpdate:
    """kind is 'snapshot' (full state), 'status' (delta) or 'klippy' (service state change)."""

    kind: str
    status: dict[str, Any] = field(default_factory=dict)
    detail: str | None = None


class StatusSource(Protocol):
    async def open(self) -> Discovery: ...
    async def snapshot(self) -> dict[str, Any]: ...
    async def history(self, limit: int) -> list[dict[str, Any]]: ...
    def updates(self) -> AsyncIterator[StatusUpdate]: ...
    async def close(self) -> None: ...


def select_observed_objects(available: list[str]) -> list[str]:
    """Pick only objects this printer exposes and that the cost tracker needs."""
    chosen = [name for name in ALWAYS_OBSERVED if name in available]
    chosen += [name for name in available if name == "fan" or name.split(" ", 1)[0] in FAN_PREFIXES]
    return chosen


class MoonrakerSource:
    def __init__(self, endpoint: MoonrakerEndpoint) -> None:
        self._endpoint = endpoint
        self._http: MoonrakerHttpClient | None = None
        self._ws: MoonrakerWebSocket | None = None
        self._observed: dict[str, list[str] | None] = {}

    async def open(self) -> Discovery:
        self._http = MoonrakerHttpClient(self._endpoint)
        try:
            server_info = await self._http.server_info()
            printer_info = await self._http.printer_info()
            objects = await self._http.list_objects()
            self._ws = MoonrakerWebSocket(self._endpoint)
            await self._ws.connect()
        except BaseException:
            await self.close()
            raise
        observed = select_observed_objects(objects)
        self._observed = dict.fromkeys(observed)
        return Discovery(printer_info, server_info, objects, observed)

    async def snapshot(self) -> dict[str, Any]:
        assert self._ws is not None
        return await self._ws.subscribe(self._observed)

    async def history(self, limit: int) -> list[dict[str, Any]]:
        assert self._http is not None
        return await self._http.history_list(limit)

    async def updates(self) -> AsyncIterator[StatusUpdate]:
        assert self._ws is not None
        async for note in self._ws.notifications():
            if note.method == "notify_status_update" and note.params:
                yield StatusUpdate("status", note.params[0])
            elif note.method in KLIPPY_METHODS:
                yield StatusUpdate("klippy", detail=KLIPPY_METHODS[note.method])
                if note.method == "notify_klippy_ready":
                    # Klippy restarts drop subscriptions, so resubscribe for a fresh snapshot.
                    yield StatusUpdate("snapshot", await self.snapshot())

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        if self._http is not None:
            await self._http.aclose()
            self._http = None
