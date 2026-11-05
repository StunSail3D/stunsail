"""Moonraker HTTP client for discovery, queries and history."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from .errors import MoonrakerConnectionError, MoonrakerResponseError


@dataclass(frozen=True)
class MoonrakerEndpoint:
    """Location and optional credential of one Moonraker instance."""

    url: str
    api_key: str | None = None

    @property
    def http_url(self) -> str:
        return self.url.rstrip("/")

    @property
    def websocket_url(self) -> str:
        parts = urlsplit(self.http_url)
        scheme = "wss" if parts.scheme == "https" else "ws"
        return urlunsplit((scheme, parts.netloc, parts.path.rstrip("/") + "/websocket", "", ""))

    @property
    def headers(self) -> dict[str, str]:
        return {"X-Api-Key": self.api_key} if self.api_key else {}

    def __repr__(self) -> str:
        return f"MoonrakerEndpoint(url={self.url!r}, api_key={'***' if self.api_key else None})"


class MoonrakerHttpClient:
    """Async wrapper over the Moonraker endpoints StunSail needs."""

    def __init__(
        self,
        endpoint: MoonrakerEndpoint,
        *,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=endpoint.http_url,
            headers=endpoint.headers,
            timeout=timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> MoonrakerHttpClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise MoonrakerConnectionError(f"GET {path} failed: {exc!r}") from exc
        if response.status_code != 200:
            raise MoonrakerResponseError(f"GET {path} returned HTTP {response.status_code}")
        try:
            return response.json()["result"]
        except (ValueError, KeyError) as exc:
            raise MoonrakerResponseError(f"GET {path} returned no result") from exc

    async def server_info(self) -> dict[str, Any]:
        return await self._get("/server/info")

    async def printer_info(self) -> dict[str, Any]:
        return await self._get("/printer/info")

    async def list_objects(self) -> list[str]:
        result = await self._get("/printer/objects/list")
        return list(result["objects"])

    async def query_objects(self, objects: dict[str, list[str] | None]) -> dict[str, Any]:
        """Query objects; a None field list requests every field of that object."""
        params = {name: ",".join(fields) if fields else "" for name, fields in objects.items()}
        result = await self._get("/printer/objects/query", params)
        return result["status"]

    async def history_list(self, limit: int = 10) -> list[dict[str, Any]]:
        result = await self._get("/server/history/list", {"limit": limit, "order": "desc"})
        return list(result.get("jobs", []))
