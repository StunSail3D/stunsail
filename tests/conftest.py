from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]


def alembic_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "database" / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture
def db_url(tmp_path, monkeypatch) -> str:
    """A fresh SQLite database created by the real Alembic migrations."""
    url = f"sqlite:///{(tmp_path / 'core.db').as_posix()}"
    monkeypatch.setenv("STUNSAIL_DATABASE_URL", url)
    command.upgrade(alembic_config(url), "head")
    return url
