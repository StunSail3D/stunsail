import asyncio
from datetime import timedelta
from decimal import Decimal

import httpx
from fastapi.testclient import TestClient
from test_core_api import AGENT, T0, profile_data

from stunsail_agent import sync as sync_module
from stunsail_agent.store import AgentStore
from stunsail_agent.sync import Syncer
from stunsail_api.app import create_app
from stunsail_core.settings import CoreSettings

JOB = "job-e2e"


def fill_buffer(store, seconds=60):
    store.append_event(
        AGENT, "job.started", T0, {"job_id": JOB, "filename": "cube.gcode", "state": "printing"}
    )
    for i in range(seconds + 1):
        store.append_sample(
            T0 + timedelta(seconds=i),
            JOB,
            "ok",
            {
                "status": {
                    "heater_bed": {"power": 0.5},
                    "extruder": {"power": 0.6},
                    "fan": {"speed": 1.0},
                }
            },
        )
    store.append_event(
        AGENT,
        "job.completed",
        T0 + timedelta(seconds=seconds),
        {
            "job_id": JOB,
            "filename": "cube.gcode",
            "end_source": "observed",
            "filament_used_mm": 1000.0,
            "print_duration_s": float(seconds),
        },
    )


def setup_core(db_url):
    app = create_app(CoreSettings(db_url, None))
    admin = TestClient(app)
    token = admin.post("/api/v1/agents", json={"agent_id": AGENT, "name": "A"}).json()["token"]
    pid = admin.post(
        "/api/v1/calibration-profiles", json={"name": "p", "version": 3, "data": profile_data()}
    ).json()["id"]
    admin.post(
        "/api/v1/printers", json={"agent_id": AGENT, "name": "P", "calibration_profile_id": pid}
    )
    admin.post(
        "/api/v1/tariffs",
        json={"currency": "ZAR", "rate_per_kwh": "4.50", "effective_from": "2026-01-01T00:00:00Z"},
    )
    return app, admin, token


def client_for(app, token, fail_first=0):
    state = {"failures": fail_first}
    asgi = httpx.ASGITransport(app=app)

    class Flaky(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            if state["failures"] > 0:
                state["failures"] -= 1
                return httpx.Response(503, request=request)
            return await asgi.handle_async_request(request)

    return httpx.AsyncClient(
        transport=Flaky(),
        base_url="http://core/api/v1",
        headers={"Authorization": f"Bearer {token}"},
    )


def test_buffer_syncs_to_core_and_produces_costed_job(db_url, monkeypatch):
    monkeypatch.setattr(sync_module, "BATCH", 20)
    app, admin, token = setup_core(db_url)
    store = AgentStore(":memory:")
    fill_buffer(store)

    async def go():
        async with client_for(app, token) as client:
            await Syncer(store, AGENT, client).drain()

    asyncio.run(go())
    assert store.pending_counts() == (0, 0)
    (job,) = admin.get("/api/v1/jobs").json()
    detail = admin.get(f"/api/v1/jobs/{job['id']}").json()
    assert detail["state"] == "completed"
    assert detail["energy"]["profile_version"] == 3
    assert Decimal(detail["energy"]["kwh"]) > 0
    assert {c["kind"] for c in detail["costs"]} == {"electricity"}


def test_failed_delivery_stays_queued_then_retry_is_idempotent(db_url):
    app, admin, token = setup_core(db_url)
    store = AgentStore(":memory:")
    fill_buffer(store, seconds=10)

    async def go():
        async with client_for(app, token, fail_first=1) as client:
            syncer = Syncer(store, AGENT, client)
            try:
                await syncer.sync_once()
            except httpx.HTTPStatusError:
                pass
            assert store.pending_counts() == (2, 11)
            await syncer.drain()
            # Simulate lost acknowledgements: everything is re-sent and must be a no-op.
            store._db.execute("UPDATE events SET delivered = 0")
            store._db.execute("UPDATE samples SET delivered = 0")
            await syncer.drain()

    asyncio.run(go())
    assert store.pending_counts() == (0, 0)
    (job,) = admin.get("/api/v1/jobs").json()
    detail = admin.get(f"/api/v1/jobs/{job['id']}").json()
    assert detail["energy"]["revision"] == 1


def test_events_wait_for_earlier_samples_in_a_batch(db_url, monkeypatch):
    monkeypatch.setattr(sync_module, "BATCH", 5)
    store = AgentStore(":memory:")
    fill_buffer(store, seconds=10)
    sent = []

    class Capture(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            import json

            body = json.loads(request.content)
            sent.append(body)
            return httpx.Response(
                200,
                json={
                    "accepted_event_ids": [e["event_id"] for e in body["events"]],
                    "accepted_sample_sequences": [s["sequence"] for s in body["samples"]],
                    "duplicate_events": 0,
                    "duplicate_samples": 0,
                },
                request=request,
            )

    async def go():
        async with httpx.AsyncClient(transport=Capture(), base_url="http://core/api/v1") as client:
            await Syncer(store, AGENT, client).drain()

    asyncio.run(go())
    terminal_batch = next(
        i
        for i, b in enumerate(sent)
        if any(e["event_type"] == "job.completed" for e in b["events"])
    )
    delivered_before = sum(len(b["samples"]) for b in sent[: terminal_batch + 1])
    assert delivered_before == 11  # the terminal event never precedes its samples
    assert store.pending_counts() == (0, 0)
