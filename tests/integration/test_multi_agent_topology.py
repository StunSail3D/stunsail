import asyncio

import httpx
from fastapi.testclient import TestClient

from stunsail_agent.store import AgentStore, utcnow
from stunsail_agent.sync import Syncer
from stunsail_api.app import create_app
from stunsail_core import models
from stunsail_core.db import make_engine, make_session_factory
from stunsail_core.settings import CoreSettings


def test_two_agents_keep_same_job_key_and_live_status_separate(db_url):
    app = create_app(CoreSettings(db_url, None))
    admin = TestClient(app)
    identities = []
    for agent_id, temp in [("agent-a", 180), ("agent-b", 220)]:
        token = admin.post("/api/v1/agents", json={"agent_id": agent_id, "name": agent_id}).json()[
            "token"
        ]
        response = admin.post(
            "/api/v1/printers", json={"agent_id": agent_id, "name": f"Printer {agent_id}"}
        )
        assert response.status_code == 201
        printer = response.json()
        store = AgentStore(":memory:")
        now = utcnow()
        store.append_event(agent_id, "job.started", now, {"job_id": "same", "state": "printing"})
        store.append_sample(now, "same", "ok", {"status": {"extruder": {"temperature": temp}}})
        identities.append((agent_id, token, printer, store, temp))
    duplicate = admin.post("/api/v1/printers", json={"agent_id": "agent-a", "name": "Duplicate"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "agent_printer_exists"

    async def sync():
        for agent_id, token, _, store, _ in identities:
            async with httpx.AsyncClient(
                base_url="http://core/api/v1",
                transport=httpx.ASGITransport(app=app),
                headers={"Authorization": f"Bearer {token}"},
            ) as client:
                await Syncer(store, agent_id, client).drain()
                store._db.execute("UPDATE events SET delivered = 0")
                store._db.execute("UPDATE samples SET delivered = 0")
                await Syncer(store, agent_id, client).drain()
                assert store.pending_counts() == (0, 0)

    asyncio.run(sync())
    jobs = admin.get("/api/v1/jobs").json()
    assert len(jobs) == 2
    for agent_id, _, printer, _store, temperature in identities:
        job = next(item for item in jobs if item["agent_id"] == agent_id)
        assert job["printer_id"] == printer["id"]
        live = admin.get(f"/api/v1/printers/{printer['id']}/live").json()
        assert live["active_job"]["id"] == job["id"]
        assert live["status"]["extruder"]["temperature"] == temperature

    for agent_id, _, _, store, _ in identities:
        store.append_event(
            agent_id,
            "job.completed",
            utcnow(),
            {"job_id": "same", "filament_used_mm": 1000.0, "print_duration_s": 10.0},
        )
    asyncio.run(sync())
    for agent_id, _, _, store, _ in identities:
        job = next(
            item for item in admin.get("/api/v1/jobs").json() if item["agent_id"] == agent_id
        )
        spool = admin.post(
            "/api/v1/spools",
            json={
                "name": agent_id,
                "material": "PLA",
                "density_g_cm3": "1.24",
                "opening_weight_g": "1000",
                "purchase_cost": "100",
                "currency": "ZAR",
            },
        ).json()
        for _ in range(2):
            assert (
                admin.post(
                    f"/api/v1/jobs/{job['id']}/spool", json={"spool_id": spool["id"]}
                ).status_code
                == 200
            )
        ledger = admin.get(f"/api/v1/spools/{spool['id']}/ledger").json()
        assert len([item for item in ledger if item["movement_type"] == "usage"]) == 1
        store.close()


def test_existing_ambiguous_printers_do_not_receive_misattributed_jobs(db_url):
    app = create_app(CoreSettings(db_url, None))
    admin = TestClient(app)
    token = admin.post("/api/v1/agents", json={"agent_id": "a", "name": "A"}).json()["token"]
    printer = admin.post("/api/v1/printers", json={"agent_id": "a", "name": "One"}).json()
    engine = make_engine(db_url)
    with make_session_factory(engine)() as session:
        session.add(models.Printer(agent_id="a", name="Legacy duplicate"))
        session.commit()
    live = admin.get(f"/api/v1/printers/{printer['id']}/live")
    assert live.status_code == 409
    assert live.json()["error"]["code"] == "ambiguous_agent_printers"
    store = AgentStore(":memory:")
    store.append_event("a", "job.started", utcnow(), {"job_id": "j"})

    async def sync():
        async with httpx.AsyncClient(
            base_url="http://core/api/v1",
            transport=httpx.ASGITransport(app=app),
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            try:
                await Syncer(store, "a", client).sync_once()
            except httpx.HTTPStatusError as error:
                assert error.response.status_code == 409
            else:
                raise AssertionError("ambiguous Agent sync should fail")

    asyncio.run(sync())
    assert store.pending_counts() == (1, 0)
    assert admin.get("/api/v1/jobs").json() == []
    store.close()
    engine.dispose()
