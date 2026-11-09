"""Request/response models for the v1 API. Money and exact weights serialise as strings."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _require_tz(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must include a timezone offset")
    return value


class Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SampleIn(BaseModel):
    sequence: int = Field(ge=1)
    observed_at: datetime
    job_id: str | None = Field(default=None, max_length=100)
    quality: str = Field(max_length=20)
    payload: dict[str, Any]

    _tz = field_validator("observed_at")(_require_tz)


class EventIn(BaseModel):
    contract_version: Literal[1]
    event_id: str = Field(min_length=1, max_length=100)
    agent_id: str = Field(min_length=1, max_length=100)
    sequence: int = Field(ge=1)
    event_type: str = Field(max_length=100)
    observed_at: datetime
    payload: dict[str, Any]

    _tz = field_validator("observed_at")(_require_tz)


class SyncIn(BaseModel):
    samples: list[SampleIn] = Field(default_factory=list, max_length=1000)
    events: list[EventIn] = Field(default_factory=list, max_length=1000)


class SyncOut(BaseModel):
    accepted_event_ids: list[str]
    accepted_sample_sequences: list[int]
    duplicate_events: int
    duplicate_samples: int


class AgentIn(BaseModel):
    agent_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    name: str = Field(min_length=1, max_length=200)


class AgentOut(Orm):
    id: str
    name: str
    created_at: datetime
    last_sync_at: datetime | None


class AgentRegistered(BaseModel):
    agent_id: str
    token: str


class CurrencySettings(BaseModel):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    symbol: str = Field(min_length=1, max_length=16)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("symbol must not be blank")
        return value


class PrinterIn(BaseModel):
    agent_id: str
    name: str = Field(min_length=1, max_length=200)
    moonraker_instance: str | None = None
    model: str | None = None
    calibration_profile_id: str | None = None


class PrinterPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    calibration_profile_id: str | None = None


class PrinterOut(Orm):
    id: str
    agent_id: str
    name: str
    moonraker_instance: str | None
    model: str | None
    calibration_profile_id: str | None


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: int = Field(ge=1)
    data: dict[str, Any]
    calibrated_against_meter: bool = False


class ProfileOut(Orm):
    id: str
    name: str
    version: int
    data: dict[str, Any]
    calibrated_against_meter: bool
    created_at: datetime


class TariffIn(BaseModel):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    rate_per_kwh: Decimal = Field(gt=0, max_digits=12, decimal_places=6)
    effective_from: datetime
    effective_to: datetime | None = None
    notes: str | None = None

    _tz = field_validator("effective_from", "effective_to")(
        lambda v: v if v is None else _require_tz(v)
    )


class TariffOut(Orm):
    id: str
    currency: str
    rate_per_kwh: Decimal
    effective_from: datetime
    effective_to: datetime | None
    notes: str | None


class SpoolIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    material: str = Field(min_length=1, max_length=50)
    brand: str | None = None
    colour: str | None = None
    diameter_mm: Decimal = Field(default=Decimal("1.75"), gt=0, le=5)
    density_g_cm3: Decimal = Field(gt=0, le=25)
    opening_weight_g: Decimal = Field(gt=0, le=100000)
    purchase_cost: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


class SpoolPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    brand: str | None = None
    colour: str | None = None
    status: Literal["active", "archived"] | None = None
    purchase_cost: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


class SpoolOut(Orm):
    id: str
    name: str
    material: str
    brand: str | None
    colour: str | None
    diameter_mm: Decimal
    density_g_cm3: Decimal
    opening_weight_g: Decimal
    purchase_cost: Decimal | None
    currency: str | None
    status: str
    remaining_g: Decimal | None = None


class LedgerOut(Orm):
    id: int
    spool_id: str
    job_id: str | None
    movement_type: str
    weight_delta_g: Decimal
    occurred_at: datetime
    notes: str | None


class AdjustmentIn(BaseModel):
    weight_delta_g: Decimal = Field(max_digits=12, decimal_places=3)
    notes: str = Field(min_length=1, max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=100)


class EnergyOut(Orm):
    revision: int
    kwh: Decimal
    covered_s: float
    uncovered_s: float
    invalid_samples: int
    basis: str
    method: str
    profile_id: str
    profile_version: int
    computed_at: datetime


class CostOut(Orm):
    kind: str
    revision: int
    currency: str
    amount: Decimal
    details: dict[str, Any]


class JobOut(Orm):
    id: str
    agent_id: str
    printer_id: str | None
    filename: str | None
    state: str
    started_at: datetime
    ended_at: datetime | None
    duration_s: float | None
    filament_used_mm: float | None
    finalised_at: datetime | None
    spool_id: str | None


class JobDetail(JobOut):
    energy: EnergyOut | None
    costs: list[CostOut]
    total_cost: Decimal | None
    total_cost_currency: str | None


class JobSpoolIn(BaseModel):
    spool_id: str


class LiveOut(BaseModel):
    printer_id: str
    agent_last_sync_at: datetime | None
    sample_observed_at: datetime | None
    sample_age_s: float | None
    status: dict[str, Any] | None
    active_job: JobOut | None


class SummaryBucket(BaseModel):
    period: str
    jobs: int
    kwh: Decimal
    filament_g: Decimal
    electricity_cost: Decimal
    filament_cost: Decimal


class SummaryOut(BaseModel):
    currency: str | None
    mixed_currencies: bool
    jobs: int
    jobs_without_cost: int
    kwh: Decimal
    filament_g: Decimal
    electricity_cost: Decimal
    filament_cost: Decimal
    total_cost: Decimal
    by_month: list[SummaryBucket]
