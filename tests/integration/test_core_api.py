from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from stunsail_api.app import create_app
from stunsail_core.db import Base
from stunsail_core.settings import CoreSettings, SettingsError
from stunsail_cost_engine import CalibrationProfile, PsuModel, filament_mass_g

T0 = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
AGENT = "agent-test"
JOB = "job-1"


def make_client(db_url, admin_token=None):
    return TestClient(create_app(CoreSettings(db_url, admin_token)))


def profile_data():
    return CalibrationProfile(
        version=1,
        name="p",
        bed_rated_w=220.0,
        hotend_rated_w=60.0,
        base_load_dc_w=15.0,
        psu=PsuModel(350.0, ((0.05, 0.7), (1.0, 0.86))),
        fans={"fan": 3.0},
    ).snapshot()


def samples(start_seq=1, count=61):
    return [
        {
            "sequence": start_seq + i,
            "observed_at": (T0 + timedelta(seconds=i)).isoformat(),
            "job_id": JOB,
            "quality": "ok",
            "payload": {
                "status": {
                    "heater_bed": {"power": 0.5},
                    "extruder": {"power": 0.6},
                    "fan": {"speed": 1.0},
                }
            },
        }
        for i in range(count)
    ]


def event(seq, event_type, at_s, **payload):
    return {
        "contract_version": 1,
        "event_id": f"evt-{seq}",
        "agent_id": AGENT,
        "sequence": seq,
        "event_type": event_type,
        "observed_at": (T0 + timedelta(seconds=at_s)).isoformat(),
        "payload": {"job_id": JOB, "filename": "cube.gcode", **payload},
    }


START = event(1, "job.started", 0, state="printing")
DONE = event(2, "job.completed", 60, filament_used_mm=1000.0, print_duration_s=60.0)


class Setup:
    def __init__(self, client):
        self.client = client
        self.token = client.post("/api/v1/agents", json={"agent_id": AGENT, "name": "A"}).json()[
            "token"
        ]
        self.auth = {"Authorization": f"Bearer {self.token}"}

    def sync(self, samples_=(), events=(), headers=None):
        return self.client.post(
            f"/api/v1/agents/{AGENT}/sync",
            json={"samples": list(samples_), "events": list(events)},
            headers=self.auth if headers is None else headers,
        )

    def configure(self, profile=True, tariff=True):
        c = self.client
        if profile:
            pid = c.post(
                "/api/v1/calibration-profiles",
                json={"name": "p", "version": 1, "data": profile_data()},
            ).json()["id"]
        else:
            pid = None
        c.post(
            "/api/v1/printers", json={"agent_id": AGENT, "name": "P", "calibration_profile_id": pid}
        )
        if tariff:
            c.post(
                "/api/v1/tariffs",
                json={
                    "currency": "ZAR",
                    "rate_per_kwh": "4.50",
                    "effective_from": "2026-01-01T00:00:00+02:00",
                },
            )

    def spool(self, cost="400"):
        return self.client.post(
            "/api/v1/spools",
            json={
                "name": "PETG",
                "material": "PETG",
                "density_g_cm3": "1.27",
                "opening_weight_g": "1000",
                "purchase_cost": cost,
                "currency": "ZAR",
            },
        ).json()["id"]

    def job(self):
        (job,) = self.client.get("/api/v1/jobs").json()
        return job["id"]

    def ledger(self, spool_id):
        return self.client.get(f"/api/v1/spools/{spool_id}/ledger").json()


@pytest.fixture
def env(db_url):
    client = make_client(db_url)
    return Setup(client), db_url


def test_migrations_match_models(db_url):
    engine = create_engine(db_url)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []


def test_job_flow_records_energy_and_costs_with_profile_version(env):
    setup, _ = env
    setup.configure()
    spool_id = setup.spool()
    response = setup.sync(samples(), [START])
    assert response.status_code == 200
    setup.client.post(f"/api/v1/jobs/{setup.job()}/spool", json={"spool_id": spool_id})
    result = setup.sync([], [DONE]).json()
    assert result["accepted_event_ids"] == ["evt-2"]

    detail = setup.client.get(f"/api/v1/jobs/{setup.job()}").json()
    assert detail["state"] == "completed" and detail["finalised_at"]
    assert detail["energy"]["basis"] == "estimated"
    assert detail["energy"]["profile_version"] == 1 and detail["energy"]["covered_s"] == 60
    assert Decimal(detail["energy"]["kwh"]) > 0
    kinds = {c["kind"]: c for c in detail["costs"]}
    assert set(kinds) == {"electricity", "filament"}
    assert kinds["electricity"]["currency"] == "ZAR" and Decimal(kinds["electricity"]["amount"]) > 0
    mass = filament_mass_g(1000.0, Decimal("1.75"), Decimal("1.27"))
    assert Decimal(kinds["filament"]["details"]["mass_g"]) == mass
    assert Decimal(kinds["filament"]["amount"]) == (mass * 400 / 1000).quantize(Decimal("0.0001"))
    assert Decimal(detail["total_cost"]) == sum(Decimal(c["amount"]) for c in detail["costs"])
    assert setup.client.get(f"/api/v1/spools/{spool_id}").json()["remaining_g"] == str(1000 - mass)


def test_replays_and_restarts_never_double_deduct(env):
    setup, db_url = env
    setup.configure()
    spool_id = setup.spool()
    setup.sync(samples(), [START])
    setup.client.post(f"/api/v1/jobs/{setup.job()}/spool", json={"spool_id": spool_id})
    setup.sync([], [DONE])
    before = setup.client.get(f"/api/v1/spools/{spool_id}").json()["remaining_g"]

    again = setup.sync(samples(), [START, DONE]).json()
    assert again["duplicate_events"] == 2 and again["duplicate_samples"] == 61
    assert again["accepted_event_ids"] == ["evt-1", "evt-2"]

    # Same terminal job under a different event id (e.g. an Agent buffer rebuild).
    redo = event(3, "job.completed", 61, filament_used_mm=1000.0, print_duration_s=60.0)
    setup.sync([], [redo])

    restarted = Setup.__new__(Setup)
    restarted.client = make_client(db_url)
    restarted.token, restarted.auth = setup.token, setup.auth
    restarted.sync(samples(), [START, DONE, redo])

    assert restarted.client.get(f"/api/v1/spools/{spool_id}").json()["remaining_g"] == before
    usage = [e for e in setup.ledger(spool_id) if e["movement_type"] == "usage"]
    assert len(usage) == 1
    assert len(restarted.client.get("/api/v1/jobs").json()) == 1


def test_late_spool_assignment_deducts_once_and_cannot_be_reassigned(env):
    setup, _ = env
    setup.configure()
    first, second = setup.spool(), setup.spool()
    setup.sync(samples(), [START, DONE])
    job_id = setup.job()
    for _ in range(2):
        assert (
            setup.client.post(f"/api/v1/jobs/{job_id}/spool", json={"spool_id": first}).status_code
            == 200
        )
    usage = [e for e in setup.ledger(first) if e["movement_type"] == "usage"]
    assert len(usage) == 1
    other = setup.client.post(f"/api/v1/jobs/{job_id}/spool", json={"spool_id": second})
    assert other.status_code == 409
    assert other.json()["error"]["code"] == "spool_already_assigned"


def test_recalculate_adds_explicit_revision(env):
    setup, _ = env
    setup.configure()
    setup.sync(samples(), [START, DONE])
    job_id = setup.job()
    assert setup.client.get(f"/api/v1/jobs/{job_id}").json()["energy"]["revision"] == 1
    again = setup.client.post(f"/api/v1/jobs/{job_id}/recalculate").json()
    assert again["energy"]["revision"] == 2


def test_job_without_profile_has_no_fabricated_energy(env):
    setup, _ = env
    setup.configure(profile=False)
    setup.sync(samples(), [START, DONE])
    job_id = setup.job()
    detail = setup.client.get(f"/api/v1/jobs/{job_id}").json()
    assert detail["energy"] is None and detail["costs"] == []
    recalculated = setup.client.post(f"/api/v1/jobs/{job_id}/recalculate")
    assert recalculated.status_code == 409 and recalculated.json()["error"]["code"] == "no_evidence"


def test_cancelled_job_with_extrusion_still_deducts(env):
    setup, _ = env
    setup.configure()
    spool_id = setup.spool()
    setup.sync(samples(), [START])
    setup.client.post(f"/api/v1/jobs/{setup.job()}/spool", json={"spool_id": spool_id})
    setup.sync([], [event(2, "job.cancelled", 30, filament_used_mm=400.0)])
    usage = [e for e in setup.ledger(spool_id) if e["movement_type"] == "usage"]
    assert len(usage) == 1 and "cancelled" in usage[0]["notes"]


def test_agent_authentication(env):
    setup, _ = env
    assert setup.sync(headers={}).status_code == 401
    assert setup.sync(headers={"Authorization": "Bearer nope"}).status_code == 401
    wrong_agent = dict(START, agent_id="other")
    assert setup.sync([], [wrong_agent]).status_code == 422
    unknown = setup.client.post(
        "/api/v1/agents/ghost/sync", json={}, headers={"Authorization": f"Bearer {setup.token}"}
    )
    assert unknown.status_code == 401


def test_sequence_reuse_with_new_event_id_rolls_back_whole_batch(env):
    setup, _ = env
    setup.configure()
    setup.sync([], [START])
    clash = dict(DONE, sequence=1)
    batch = setup.sync(samples(), [clash])
    assert batch.status_code == 409 and batch.json()["error"]["code"] == "sequence_conflict"
    assert setup.sync(samples(), []).json()["duplicate_samples"] == 0  # nothing was stored


def test_naive_timestamps_are_rejected(env):
    setup, _ = env
    bad = dict(START, observed_at="2026-11-05T10:00:00")
    assert setup.sync([], [bad]).status_code == 422


def test_admin_token_protects_management_routes(db_url):
    client = make_client(db_url, admin_token="a" * 20)
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/jobs").status_code == 401
    assert (
        client.get("/api/v1/jobs", headers={"Authorization": "Bearer " + "b" * 20}).status_code
        == 401
    )
    assert (
        client.get("/api/v1/jobs", headers={"Authorization": "Bearer " + "a" * 20}).status_code
        == 200
    )


def test_readiness_requires_migrated_database(db_url, tmp_path):
    assert make_client(db_url).get("/api/v1/health/ready").status_code == 200
    empty = f"sqlite:///{(tmp_path / 'empty.db').as_posix()}"
    assert make_client(empty).get("/api/v1/health/ready").status_code == 503


def test_settings_validation():
    assert CoreSettings.from_env({}).admin_token is None
    with pytest.raises(SettingsError):
        CoreSettings.from_env({"STUNSAIL_DATABASE_URL": "mysql://x"})
    with pytest.raises(SettingsError):
        CoreSettings.from_env({"STUNSAIL_ADMIN_TOKEN": "short"})


def test_validation_errors_for_bad_inputs(env):
    setup, _ = env
    c = setup.client
    assert (
        c.post(
            "/api/v1/tariffs",
            json={"currency": "zar", "rate_per_kwh": "4", "effective_from": "2026-01-01T00:00:00Z"},
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/api/v1/spools",
            json={
                "name": "x",
                "material": "PLA",
                "density_g_cm3": "1.2",
                "opening_weight_g": "1000",
                "purchase_cost": "300",
            },
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/api/v1/calibration-profiles", json={"name": "x", "version": 1, "data": {}}
        ).status_code
        == 422
    )
    assert c.get("/api/v1/jobs/missing").status_code == 404
    assert c.get("/api/v1/jobs?limit=9999").status_code == 422

# placeholder
