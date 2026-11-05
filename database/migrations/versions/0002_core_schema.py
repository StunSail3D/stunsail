"""Core domain schema.

Revision ID: 0002_core_schema
Revises: 0001_initial
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_core_schema"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _dt() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def _dec() -> sa.String:
    # Exact decimals are stored as text; see stunsail_core.types.DecimalString.
    return sa.String(40)


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", _dt(), nullable=False),
        sa.Column("last_sync_at", _dt()),
    )
    op.create_table(
        "calibration_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("data", sa.JSON, nullable=False),
        sa.Column("calibrated_against_meter", sa.Boolean, nullable=False),
        sa.Column("created_at", _dt(), nullable=False),
        sa.UniqueConstraint("name", "version"),
    )
    op.create_table(
        "printers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(100), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("moonraker_instance", sa.String(200)),
        sa.Column("model", sa.String(200)),
        sa.Column(
            "calibration_profile_id", sa.String(36), sa.ForeignKey("calibration_profiles.id")
        ),
        sa.Column("created_at", _dt(), nullable=False),
    )
    op.create_index("ix_printers_agent_id", "printers", ["agent_id"])
    op.create_table(
        "tariffs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("rate_per_kwh", _dec(), nullable=False),
        sa.Column("effective_from", _dt(), nullable=False),
        sa.Column("effective_to", _dt()),
        sa.Column("notes", sa.Text),
    )
    op.create_table(
        "agent_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("agent_id", sa.String(100), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("event_id", sa.String(100), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("observed_at", _dt(), nullable=False),
        sa.Column("received_at", _dt(), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("processing_status", sa.String(20), nullable=False),
        sa.UniqueConstraint("agent_id", "event_id"),
        sa.UniqueConstraint("agent_id", "sequence"),
    )
    op.create_table(
        "telemetry_samples",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("agent_id", sa.String(100), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("agent_sequence", sa.Integer, nullable=False),
        sa.Column("job_key", sa.String(100)),
        sa.Column("observed_at", _dt(), nullable=False),
        sa.Column("received_at", _dt(), nullable=False),
        sa.Column("quality", sa.String(20), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.UniqueConstraint("agent_id", "agent_sequence"),
    )
    op.create_index("ix_telemetry_job", "telemetry_samples", ["agent_id", "job_key", "observed_at"])
    op.create_table(
        "spools",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("material", sa.String(50), nullable=False),
        sa.Column("brand", sa.String(100)),
        sa.Column("colour", sa.String(50)),
        sa.Column("diameter_mm", _dec(), nullable=False),
        sa.Column("density_g_cm3", _dec(), nullable=False),
        sa.Column("opening_weight_g", _dec(), nullable=False),
        sa.Column("purchase_cost", _dec()),
        sa.Column("currency", sa.String(3)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", _dt(), nullable=False),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(100), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("printer_id", sa.String(36), sa.ForeignKey("printers.id")),
        sa.Column("external_job_key", sa.String(100), nullable=False),
        sa.Column("filename", sa.String(500)),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("started_at", _dt(), nullable=False),
        sa.Column("ended_at", _dt()),
        sa.Column("duration_s", sa.Float),
        sa.Column("filament_used_mm", sa.Float),
        sa.Column("finalised_at", _dt()),
        sa.Column("spool_id", sa.String(36), sa.ForeignKey("spools.id")),
        sa.Column("source_metadata", sa.JSON, nullable=False),
        sa.UniqueConstraint("agent_id", "external_job_key"),
    )
    op.create_index("ix_jobs_agent_id", "jobs", ["agent_id"])
    op.create_index("ix_jobs_started_at", "jobs", ["started_at"])
    op.create_table(
        "spool_ledger",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("spool_id", sa.String(36), sa.ForeignKey("spools.id"), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id")),
        sa.Column("movement_type", sa.String(20), nullable=False),
        sa.Column("weight_delta_g", _dec(), nullable=False),
        sa.Column("occurred_at", _dt(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), unique=True),
        sa.Column("notes", sa.Text),
        sa.CheckConstraint("movement_type IN ('opening', 'usage', 'adjustment')"),
    )
    op.create_index("ix_ledger_spool", "spool_ledger", ["spool_id", "occurred_at"])
    op.create_table(
        "job_energy",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("kwh", _dec(), nullable=False),
        sa.Column("covered_s", sa.Float, nullable=False),
        sa.Column("uncovered_s", sa.Float, nullable=False),
        sa.Column("invalid_samples", sa.Integer, nullable=False),
        sa.Column("basis", sa.String(20), nullable=False),
        sa.Column("method", sa.String(50), nullable=False),
        sa.Column(
            "profile_id", sa.String(36), sa.ForeignKey("calibration_profiles.id"), nullable=False
        ),
        sa.Column("profile_version", sa.Integer, nullable=False),
        sa.Column("profile_snapshot", sa.JSON, nullable=False),
        sa.Column("computed_at", _dt(), nullable=False),
        sa.UniqueConstraint("job_id", "revision"),
    )
    op.create_table(
        "job_costs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount", _dec(), nullable=False),
        sa.Column("details", sa.JSON, nullable=False),
        sa.Column("computed_at", _dt(), nullable=False),
        sa.UniqueConstraint("job_id", "kind", "revision"),
        sa.CheckConstraint("kind IN ('electricity', 'filament')"),
    )


def downgrade() -> None:
    op.drop_table("job_costs")
    op.drop_table("job_energy")
    op.drop_index("ix_ledger_spool", table_name="spool_ledger")
    op.drop_table("spool_ledger")
    op.drop_index("ix_jobs_started_at", table_name="jobs")
    op.drop_index("ix_jobs_agent_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("spools")
    op.drop_index("ix_telemetry_job", table_name="telemetry_samples")
    op.drop_table("telemetry_samples")
    op.drop_table("agent_events")
    op.drop_table("tariffs")
    op.drop_index("ix_printers_agent_id", table_name="printers")
    op.drop_table("printers")
    op.drop_table("calibration_profiles")
    op.drop_table("agents")
