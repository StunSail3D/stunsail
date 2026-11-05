"""Moonraker JSON-RPC WebSocket client."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from .errors import MoonrakerConnectionError, MoonrakerResponseError
from .http import MoonrakerEndpoint


@dataclass(frozen=True)
class Notification:
    method: str
    params: list[Any]


def backoff_delays(
    initial: float = 1.0, maximum: float = 30.0, factor: float = 2.0
) -> Iterator[float]:
    """Endless bounded exponential backoff sequence."""
    delay = initial
    while True:
        yield min(delay, maximum)
        delay *= factor


class MoonrakerWebSocket:
    """One WebSocket session: JSON-RPC calls plus a stream of notifications."""

    def __init__(self, endpoint: MoonrakerEndpoint, *, open_timeout: float = 10.0) -> None:
        self._endpoint = endpoint
        self._open_timeout = open_timeout
        self._connection: ClientConnection | None = None
        self._reader: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._notifications: asyncio.Queue[Notification | None] = asyncio.Queue()
        self._ids = itertools.count(1)
        self._closed = False

    async def connect(self) -> None:
        try:
            self._connection = await connect(
                self._endpoint.websocket_url,
                additional_headers=self._endpoint.headers or None,
                open_timeout=self._open_timeout,
            )
        except (OSError, TimeoutError, WebSocketException) as exc:
            raise MoonrakerConnectionError(f"WebSocket connect failed: {exc!r}") from exc
        self._reader = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        self._closed = True
        if self._connection is not None:
            await self._connection.close()
        if self._reader is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader

    async def __aenter__(self) -> MoonrakerWebSocket:
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def _read_loop(self) -> None:
        assert self._connection is not None
        try:
            async for raw in self._connection:
                self._dispatch(raw)
        except WebSocketException:
            pass
        finally:
            self._closed = True
            error = MoonrakerConnectionError("WebSocket connection lost")
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(error)
            self._pending.clear()
            self._notifications.put_nowait(None)

    def _dispatch(self, raw: str | bytes) -> None:
        try:
            message = json.loads(raw)
        except ValueError:
            return
        if not isinstance(message, dict):
            return
        message_id = message.get("id")
        if message_id is not None:
            future = self._pending.pop(message_id, None)
            if future is None or future.done():
                return
            if "error" in message:
                future.set_exception(MoonrakerResponseError(str(message["error"])))
            else:
                future.set_result(message.get("result"))
        elif "method" in message:
            self._notifications.put_nowait(
                Notification(message["method"], list(message.get("params") or []))
            )

    async def call(
        self, method: str, params: dict[str, Any] | None = None, timeout: float = 10.0
    ) -> Any:
        if self._connection is None or self._closed:
            raise MoonrakerConnectionError("WebSocket is not connected")
        request_id = next(self._ids)
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        payload = {"jsonrpc": "2.0", "method": method, "id": request_id}
        if params:
            payload["params"] = params
        try:
            await self._connection.send(json.dumps(payload))
            async with asyncio.timeout(timeout):
                return await future
        except (WebSocketException, TimeoutError) as exc:
            raise MoonrakerConnectionError(f"{method} failed: {exc!r}") from exc
        finally:
            self._pending.pop(request_id, None)

    async def subscribe(self, objects: dict[str, list[str] | None]) -> dict[str, Any]:
        """Subscribe to objects and return their initial status snapshot."""
        result = await self.call("printer.objects.subscribe", {"objects": objects})
        return result["status"]

    async def notifications(self) -> AsyncIterator[Notification]:
        """Yield notifications until the connection ends, then raise a connection error."""
        while True:
            item = await self._notifications.get()
            if item is None:
                raise MoonrakerConnectionError("WebSocket connection lost")
            yield item
