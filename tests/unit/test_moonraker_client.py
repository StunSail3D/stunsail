import asyncio
import json

import httpx
import pytest
from websockets.asyncio.server import serve

from stunsail_moonraker import (
    MoonrakerConnectionError,
    MoonrakerEndpoint,
    MoonrakerHttpClient,
    MoonrakerWebSocket,
    backoff_delays,
)


def test_endpoint_urls_and_secret_redaction():
    endpoint = MoonrakerEndpoint("https://printer.local:7125/", api_key="secret")
    assert endpoint.websocket_url == "wss://printer.local:7125/websocket"
    assert endpoint.headers == {"X-Api-Key": "secret"}
    assert "secret" not in repr(endpoint)


def test_backoff_is_bounded():
    delays = backoff_delays(1, 8)
    assert [next(delays) for _ in range(6)] == [1, 2, 4, 8, 8, 8]


def test_http_client_queries():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/printer/objects/list":
            return httpx.Response(200, json={"result": {"objects": ["extruder", "fan"]}})
        if request.url.path == "/printer/objects/query":
            assert request.url.params["extruder"] == "temperature,target"
            return httpx.Response(200, json={"result": {"status": {"extruder": {"target": 0}}}})
        return httpx.Response(500)

    async def scenario():
        client = MoonrakerHttpClient(
            MoonrakerEndpoint("http://moonraker.test"), transport=httpx.MockTransport(handler)
        )
        async with client:
            assert await client.list_objects() == ["extruder", "fan"]
            status = await client.query_objects({"extruder": ["temperature", "target"]})
            assert status == {"extruder": {"target": 0}}
            with pytest.raises(Exception, match="HTTP 500"):
                await client.printer_info()

    asyncio.run(scenario())


def test_websocket_rpc_notifications_and_disconnect():
    async def handler(connection):
        async for raw in connection:
            request = json.loads(raw)
            assert request["method"] == "printer.objects.subscribe"
            await connection.send(
                json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": {"status": {"a": 1}}})
            )
            await connection.send(
                json.dumps({"method": "notify_status_update", "params": [{"a": {"b": 2}}, 1.0]})
            )
            await connection.close()

    async def scenario():
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            ws = MoonrakerWebSocket(MoonrakerEndpoint(f"http://127.0.0.1:{port}"))
            async with ws:
                assert await ws.subscribe({"a": None}) == {"a": 1}
                seen = []
                with pytest.raises(MoonrakerConnectionError):
                    async for note in ws.notifications():
                        seen.append(note)
                assert seen[0].method == "notify_status_update"
                assert seen[0].params[0] == {"a": {"b": 2}}

    asyncio.run(scenario())


def test_websocket_connect_failure_is_connection_error():
    async def scenario():
        ws = MoonrakerWebSocket(MoonrakerEndpoint("http://127.0.0.1:9"), open_timeout=2)
        with pytest.raises(MoonrakerConnectionError):
            await ws.connect()

    asyncio.run(scenario())
