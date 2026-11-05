from datetime import timedelta
from decimal import Decimal

import pytest
from test_core_api import DONE, JOB, START, T0, Setup, make_client, samples


@pytest.fixture
def setup(db_url):
    return Setup(make_client(db_url))


def printer_id(setup):
    return setup.client.get("/api/v1/printers").json()[0]["id"]


def test_live_status_shows_latest_sample_and_active_job(setup):
    setup.configure()
    setup.sync(samples(count=5), [START])
    live = setup.client.get(f"/api/v1/printers/{printer_id(setup)}/live").json()
    assert live["active_job"]["filename"] == "cube.gcode"
    assert live["status"]["extruder"]["power"] == 0.6
    assert live["sample_age_s"] > 0
    setup.sync([], [DONE])
    after = setup.client.get(f"/api/v1/printers/{printer_id(setup)}/live").json()
    assert after["active_job"] is None


def test_live_status_before_any_data(setup):
    setup.configure()
    live = setup.client.get(f"/api/v1/printers/{printer_id(setup)}/live").json()
    assert live["status"] is None and live["active_job"] is None
    assert setup.client.get("/api/v1/printers/missing/live").status_code == 404


def test_summary_totals_match_job_costs(setup):
    setup.configure()
    spool_id = setup.spool()
    setup.sync(samples(), [START])
    setup.client.post(f"/api/v1/jobs/{setup.job()}/spool", json={"spool_id": spool_id})
    setup.sync([], [DONE])
    detail = setup.client.get(f"/api/v1/jobs/{setup.job()}").json()
    summary = setup.client.get("/api/v1/reports/summary").json()
    assert summary["jobs"] == 1 and summary["jobs_without_cost"] == 0
    assert summary["currency"] == "ZAR" and not summary["mixed_currencies"]
    assert Decimal(summary["total_cost"]) == Decimal(detail["total_cost"])
    assert Decimal(summary["kwh"]) == Decimal(detail["energy"]["kwh"])
    assert Decimal(summary["filament_g"]) > 0
    assert summary["by_month"][0]["period"] == "2026-11"

    outside = setup.client.get(
        "/api/v1/reports/summary", params={"from": (T0 + timedelta(days=1)).isoformat()}
    ).json()
    assert outside["jobs"] == 0 and Decimal(outside["total_cost"]) == 0
    assert setup.client.get("/api/v1/reports/summary?from=2026-11-01T00:00:00").status_code == 422


def test_csv_export_and_formula_injection_guard(setup):
    setup.configure()
    setup.sync(samples(), [START, dict(DONE, payload={**DONE["payload"], "filename": "=SUM(A1)"})])
    response = setup.client.get("/api/v1/export/jobs.csv")
    assert response.headers["content-type"].startswith("text/csv")
    lines = response.text.strip().splitlines()
    assert lines[0].startswith("job_id,filename,state")
    assert len(lines) == 2 and JOB and "completed" in lines[1]
    assert ",=SUM" not in lines[1]


def test_spool_can_be_edited_and_archived(setup):
    spool_id = setup.spool()
    patched = setup.client.patch(
        f"/api/v1/spools/{spool_id}", json={"name": "Renamed", "status": "archived"}
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Renamed" and patched.json()["status"] == "archived"
    assert patched.json()["remaining_g"] == "1000"
    half = setup.client.patch(f"/api/v1/spools/{spool_id}", json={"purchase_cost": "100"})
    assert half.status_code == 422
    bad = setup.client.patch(f"/api/v1/spools/{spool_id}", json={"status": "gone"})
    assert bad.status_code == 422


def test_built_web_app_is_served_from_web_dir(db_url, tmp_path):
    from fastapi.testclient import TestClient

    from stunsail_api.app import create_app
    from stunsail_core.settings import CoreSettings

    (tmp_path / "index.html").write_text("<h1>StunSail</h1>")
    client = TestClient(create_app(CoreSettings(db_url, None, str(tmp_path))))
    assert "StunSail" in client.get("/").text
    assert client.get("/api/v1/health").json()["status"] == "ok"
