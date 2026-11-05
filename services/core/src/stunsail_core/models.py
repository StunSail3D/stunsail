from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .types import DecimalString, UTCDateTime

TERMINAL_STATES = ("completed", "cancelled", "error", "interrupted")


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class CalibrationProfile(Base):
    __tablename__ = "calibration_profiles"
    __table_args__ = (UniqueConstraint("name", "version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    calibrated_against_meter: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Printer(Base):
    __tablename__ = "printers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    moonraker_instance: Mapped[str | None] = mapped_column(String(200))
    model: Mapped[str | None] = mapped_column(String(200))
    calibration_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("calibration_profiles.id")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Tariff(Base):
    __tablename__ = "tariffs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    currency: Mapped[str] = mapped_column(String(3))
    rate_per_kwh: Mapped[Decimal] = mapped_column(DecimalString)
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime)
    effective_to: Mapped[datetime | None] = mapped_column(UTCDateTime)
    notes: Mapped[str | None] = mapped_column(Text)


class AgentEvent(Base):
    __tablename__ = "agent_events"
    __table_args__ = (
        UniqueConstraint("agent_id", "event_id"),
        UniqueConstraint("agent_id", "sequence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    event_id: Mapped[str] = mapped_column(String(100))
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(100))
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    processing_status: Mapped[str] = mapped_column(String(20))


class TelemetrySample(Base):
    __tablename__ = "telemetry_samples"
    __table_args__ = (
        UniqueConstraint("agent_id", "agent_sequence"),
        Index("ix_telemetry_job", "agent_id", "job_key", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    agent_sequence: Mapped[int] = mapped_column(Integer)
    job_key: Mapped[str | None] = mapped_column(String(100))
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime)
    quality: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class Spool(Base):
    __tablename__ = "spools"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    material: Mapped[str] = mapped_column(String(50))
    brand: Mapped[str | None] = mapped_column(String(100))
    colour: Mapped[str | None] = mapped_column(String(50))
    diameter_mm: Mapped[Decimal] = mapped_column(DecimalString)
    density_g_cm3: Mapped[Decimal] = mapped_column(DecimalString)
    opening_weight_g: Mapped[Decimal] = mapped_column(DecimalString)
    purchase_cost: Mapped[Decimal | None] = mapped_column(DecimalString)
    currency: Mapped[str | None] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("agent_id", "external_job_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    printer_id: Mapped[str | None] = mapped_column(ForeignKey("printers.id"))
    external_job_key: Mapped[str] = mapped_column(String(100))
    filename: Mapped[str | None] = mapped_column(String(500))
    state: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    duration_s: Mapped[float | None] = mapped_column(Float)
    filament_used_mm: Mapped[float | None] = mapped_column(Float)
    finalised_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    spool_id: Mapped[str | None] = mapped_column(ForeignKey("spools.id"))
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SpoolLedger(Base):
    """Append-only; remaining weight is the sum of weight_delta_g."""

    __tablename__ = "spool_ledger"
    __table_args__ = (
        CheckConstraint("movement_type IN ('opening', 'usage', 'adjustment')"),
        Index("ix_ledger_spool", "spool_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spool_id: Mapped[str] = mapped_column(ForeignKey("spools.id"))
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"))
    movement_type: Mapped[str] = mapped_column(String(20))
    weight_delta_g: Mapped[Decimal] = mapped_column(DecimalString)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    notes: Mapped[str | None] = mapped_column(Text)


class JobEnergy(Base):
    """One energy result per revision; revisions are explicit, never overwritten."""

    __tablename__ = "job_energy"
    __table_args__ = (UniqueConstraint("job_id", "revision"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    revision: Mapped[int] = mapped_column(Integer)
    kwh: Mapped[Decimal] = mapped_column(DecimalString)
    covered_s: Mapped[float] = mapped_column(Float)
    uncovered_s: Mapped[float] = mapped_column(Float)
    invalid_samples: Mapped[int] = mapped_column(Integer)
    basis: Mapped[str] = mapped_column(String(20))
    method: Mapped[str] = mapped_column(String(50))
    profile_id: Mapped[str] = mapped_column(ForeignKey("calibration_profiles.id"))
    profile_version: Mapped[int] = mapped_column(Integer)
    profile_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime)


class JobCost(Base):
    __tablename__ = "job_costs"
    __table_args__ = (
        UniqueConstraint("job_id", "kind", "revision"),
        CheckConstraint("kind IN ('electricity', 'filament')"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    kind: Mapped[str] = mapped_column(String(20))
    revision: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal] = mapped_column(DecimalString)
    details: Mapped[dict[str, Any]] = mapped_column(JSON)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime)
