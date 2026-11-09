from alembic import command
from conftest import alembic_config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from stunsail_api.app import create_app
from stunsail_core.settings import CoreSettings


def test_currency_settings_persist_without_rewriting_prices(db_url):
    admin = {"Authorization": "Bearer admin-token-123456"}
    client = TestClient(create_app(CoreSettings(db_url, "admin-token-123456")))
    url = "/api/v1/settings/currency"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=admin).json() == {"currency": "ZAR", "symbol": "R"}
    spool = client.post(
        "/api/v1/spools",
        headers=admin,
        json={
            "name": "PLA",
            "material": "PLA",
            "density_g_cm3": "1.24",
            "opening_weight_g": "1000",
            "purchase_cost": "100",
            "currency": "ZAR",
        },
    ).json()
    assert client.put(url, json={"currency": "USD", "symbol": "$"}).status_code == 401
    assert client.put(url, headers=admin, json={"currency": "USD", "symbol": "$"}).json() == {
        "currency": "USD",
        "symbol": "$",
    }
    assert client.get(f"/api/v1/spools/{spool['id']}", headers=admin).json()["currency"] == "ZAR"
    assert client.put(url, headers=admin, json={"currency": "us", "symbol": "$"}).status_code == 422
    assert (
        client.put(url, headers=admin, json={"currency": "USD", "symbol": " "}).status_code == 422
    )
    new_client = TestClient(create_app(CoreSettings(db_url, "admin-token-123456")))
    assert new_client.get(url, headers=admin).json() == {"currency": "USD", "symbol": "$"}


def test_currency_migration_downgrade_and_upgrade(db_url):
    engine = create_engine(db_url)
    assert "currency_settings" in inspect(engine).get_table_names()
    command.downgrade(alembic_config(db_url), "0002_core_schema")
    assert "currency_settings" not in inspect(engine).get_table_names()
    assert "spools" in inspect(engine).get_table_names()
    command.upgrade(alembic_config(db_url), "head")
    assert "currency_settings" in inspect(engine).get_table_names()
    engine.dispose()
