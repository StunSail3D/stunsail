"""Core domain service: idempotent event ingestion, job finalisation, costs and spool ledger.

All functions operate on a caller-owned Session and never commit; the caller wraps one
request in one transaction so a failed batch leaves nothing half-applied.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stunsail_cost_engine import (
    CalibrationProfile as EngineProfile,
)
from stunsail_cost_engine import (
    Tariff as EngineTariff,
)
from stunsail_cost_engine import (
    calculate_cost,
    filament_cost,
    filament_mass_g,
    integrate_energy,
)

from .models import (
    TERMINAL_STATES,
    Agent,
    AgentEvent,
    CalibrationProfile,
    Job,
    JobCost,
    JobEnergy,
    Printer,
    Spool,
    SpoolLedger,
    Tariff,
    TelemetrySample,
    utcnow,
)

log = logging.getLogger("stunsail.core")

TERMINAL_EVENTS = {
    "job.completed": "completed",
    "job.cancelled": "cancelled",
    "job.errored": "error",
    "job.interrupted": "interrupted",
}
ENERGY_METHOD = "trapezoidal-v1"


class DomainError(Exception):
    """Business-rule violation with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# --- agents ---------------------------------------------------------------------------


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def register_agent(session: Session, agent_id: str, name: str) -> tuple[Agent, str]:
    """Create an agent and return it with its one-time plaintext token."""
    if session.get(Agent, agent_id) is not None:
        raise DomainError("agent_exists", f"agent {agent_id!r} is already registered")
    token = secrets.token_urlsafe(32)
    agent = Agent(id=agent_id, name=name, token_hash=_hash_token(token))
    session.add(agent)
    session.flush()
    return agent, token


def authenticate_agent(session: Session, agent_id: str, token: str) -> Agent | None:
    agent = session.get(Agent, agent_id)
    if agent is None:
        # Spend comparable time so unknown ids are not distinguishable by timing.
        hmac.compare_digest(_hash_token(token), "0" * 64)
        return None
    valid = hmac.compare_digest(agent.token_hash, _hash_token(token))
    return agent if valid and not agent.revoked else None


def reset_agent_token(session: Session, agent_id: str) -> str:
    """Replace an agent's credential and return the new token once."""
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise DomainError("agent_not_found", f"agent {agent_id!r} not found")
    token = secrets.token_urlsafe(32)
    agent.token_hash = _hash_token(token)
    agent.revoked = False
    session.flush()
    return token


# --- ingestion ------------------------------------------------------------------------


@dataclass
class IngestResult:
    accepted_event_ids: list[str] = field(default_factory=list)
    accepted_sample_sequences: list[int] = field(default_factory=list)
    duplicate_events: int = 0
    duplicate_samples: int = 0


def ingest_batch(
    session: Session,
    agent: Agent,
    samples: list[dict[str, Any]],
    events: list[dict[str, Any]],
    now: datetime | None = None,
) -> IngestResult:
    """Apply a batch. Samples go first so finalisation sees every sample in the batch.

    Duplicates are acknowledged without effect, which makes retries and replays safe.
    """
    printer_for_agent(session, agent.id)
    now = now or utcnow()
    result = IngestResult()

    sequences = [s["sequence"] for s in samples]
    known = {
        row.agent_sequence: row
        for row in session.scalars(
            select(TelemetrySample).where(
                TelemetrySample.agent_id == agent.id,
                TelemetrySample.agent_sequence.in_(sequences),
            )
        )
    }
    for sample in samples:
        if sample["sequence"] in known:
            previous = known[sample["sequence"]]
            if (
                previous.job_key != sample.get("job_id")
                or previous.observed_at != sample["observed_at"]
                or previous.quality != sample["quality"]
                or previous.payload != sample["payload"]
            ):
                raise DomainError(
                    "sample_conflict",
                    f"agent {agent.id!r} reused sample sequence "
                    f"{sample['sequence']} with different data",
                )
            result.duplicate_samples += 1
        else:
            record = TelemetrySample(
                agent_id=agent.id,
                agent_sequence=sample["sequence"],
                job_key=sample.get("job_id"),
                observed_at=sample["observed_at"],
                received_at=now,
                quality=sample["quality"],
                payload=sample["payload"],
            )
            known[sample["sequence"]] = record
            session.add(record)
        result.accepted_sample_sequences.append(sample["sequence"])
    session.flush()

    event_ids = [e["event_id"] for e in events]
    seen = {
        row.event_id: row
        for row in session.scalars(
            select(AgentEvent).where(
                AgentEvent.agent_id == agent.id, AgentEvent.event_id.in_(event_ids)
            )
        )
    }
    for envelope in sorted(events, key=lambda e: e["sequence"]):
        if envelope["event_id"] in seen:
            previous = seen[envelope["event_id"]]
            if (
                previous.sequence != envelope["sequence"]
                or previous.event_type != envelope["event_type"]
                or previous.observed_at != envelope["observed_at"]
                or previous.payload != envelope["payload"]
            ):
                raise DomainError(
                    "event_conflict",
                    f"agent {agent.id!r} reused an event id with different data",
                )
            result.duplicate_events += 1
        else:
            record = AgentEvent(
                agent_id=agent.id,
                event_id=envelope["event_id"],
                sequence=envelope["sequence"],
                event_type=envelope["event_type"],
                observed_at=envelope["observed_at"],
                received_at=now,
                payload=envelope["payload"],
                processing_status="applied",
            )
            seen[envelope["event_id"]] = record
            session.add(record)
            session.flush()
            record.processing_status = _apply_event(session, agent, record, now)
        result.accepted_event_ids.append(envelope["event_id"])

    agent.last_sync_at = now
    return result


def _apply_event(session: Session, agent: Agent, event: AgentEvent, now: datetime) -> str:
    payload = event.payload
    job_key = payload.get("job_id")
    if event.event_type == "job.started" and job_key:
        _get_or_create_job(session, agent, job_key, event, payload.get("state", "printing"))
        return "applied"
    if event.event_type in ("job.paused", "job.resumed") and job_key:
        job = _find_job(session, agent.id, job_key)
        if job is None or job.finalised_at is not None:
            return "ignored"
        job.state = "paused" if event.event_type == "job.paused" else "printing"
        return "applied"
    if event.event_type in TERMINAL_EVENTS and job_key:
        job = _get_or_create_job(session, agent, job_key, event, "printing", partial=True)
        if job.finalised_at is not None:
            return "ignored"
        finalise_job(session, job, TERMINAL_EVENTS[event.event_type], event, now)
        return "applied"
    return "applied"


def _find_job(session: Session, agent_id: str, job_key: str) -> Job | None:
    return session.scalars(
        select(Job).where(Job.agent_id == agent_id, Job.external_job_key == job_key)
    ).first()


def printer_for_agent(session: Session, agent_id: str) -> Printer | None:
    printers = list(session.scalars(select(Printer).where(Printer.agent_id == agent_id).limit(2)))
    if len(printers) > 1:
        raise DomainError(
            "ambiguous_agent_printers",
            f"agent {agent_id!r} has multiple printers; one Agent per printer is required",
        )
    return printers[0] if printers else None


def _get_or_create_job(
    session: Session,
    agent: Agent,
    job_key: str,
    event: AgentEvent,
    state: str,
    partial: bool = False,
) -> Job:
    job = _find_job(session, agent.id, job_key)
    if job is not None:
        return job
    printer = printer_for_agent(session, agent.id)
    job = Job(
        agent_id=agent.id,
        printer_id=printer.id if printer else None,
        external_job_key=job_key,
        filename=event.payload.get("filename"),
        state=state,
        started_at=event.observed_at,
        source_metadata={"start_event_missing": True} if partial else {},
    )
    session.add(job)
    session.flush()
    return job


def finalise_job(session: Session, job: Job, state: str, event: AgentEvent, now: datetime) -> None:
    """Finalise exactly once: later corrections must be explicit revisions."""
    if job.finalised_at is not None:
        return
    payload = event.payload
    job.state = state
    job.ended_at = event.observed_at
    job.duration_s = payload.get("print_duration_s")
    job.filament_used_mm = payload.get("filament_used_mm")
    job.filename = payload.get("filename") or job.filename
    job.finalised_at = now
    job.source_metadata = {
        **job.source_metadata,
        "end_source": payload.get("end_source"),
        "end_event_id": event.event_id,
    }
    compute_job_costs(session, job, now)
    if job.spool_id:
        deduct_spool(session, job, now)


# --- energy and electricity cost --------------------------------------------------------


def compute_job_costs(session: Session, job: Job, now: datetime | None = None) -> JobEnergy | None:
    """Compute a new energy/electricity revision. Returns None when it cannot be evidenced."""
    now = now or utcnow()
    printer = session.get(Printer, job.printer_id) if job.printer_id else None
    if printer is None or printer.calibration_profile_id is None:
        return None
    profile_row = session.get(CalibrationProfile, printer.calibration_profile_id)
    rows = session.execute(
        select(TelemetrySample.observed_at, TelemetrySample.quality, TelemetrySample.payload)
        .where(
            TelemetrySample.agent_id == job.agent_id,
            TelemetrySample.job_key == job.external_job_key,
        )
        .order_by(TelemetrySample.observed_at)
    ).all()
    if profile_row is None or not rows:
        return None
    profile = EngineProfile.from_snapshot(profile_row.data)
    samples = [
        (at, payload.get("status", {}) if quality == "ok" else {}) for at, quality, payload in rows
    ]
    energy = integrate_energy(samples, profile)
    revision = (
        session.scalar(select(func.max(JobEnergy.revision)).where(JobEnergy.job_id == job.id)) or 0
    ) + 1
    record = JobEnergy(
        job_id=job.id,
        revision=revision,
        kwh=Decimal(repr(energy.kwh)),
        covered_s=energy.covered_s,
        uncovered_s=energy.uncovered_s,
        invalid_samples=energy.invalid_samples,
        basis="measured" if profile.calibrated_against_meter else "estimated",
        method=ENERGY_METHOD,
        profile_id=profile_row.id,
        profile_version=profile_row.version,
        profile_snapshot=profile_row.data,
        computed_at=now,
    )
    session.add(record)

    tariffs = _applicable_tariffs(session)
    if tariffs:
        cost = calculate_cost(energy.intervals, tariffs)
        session.add(
            JobCost(
                job_id=job.id,
                kind="electricity",
                revision=revision,
                currency=cost.currency or tariffs[0].currency,
                amount=cost.total,
                details={
                    "uncosted_kwh": cost.uncosted_kwh,
                    "lines": [
                        {
                            "rate_per_kwh": str(line.tariff.rate_per_kwh),
                            "effective_from": line.tariff.effective_from.isoformat(),
                            "kwh": line.kwh,
                            "cost": str(line.cost),
                        }
                        for line in cost.lines
                    ],
                },
                computed_at=now,
            )
        )
    session.flush()
    return record


def _applicable_tariffs(session: Session) -> list[EngineTariff]:
    rows = list(session.scalars(select(Tariff).order_by(Tariff.effective_from)))
    if not rows:
        return []
    currency = rows[-1].currency
    return [
        EngineTariff(t.currency, t.rate_per_kwh, t.effective_from, t.effective_to)
        for t in rows
        if t.currency == currency
    ]


# --- spools -------------------------------------------------------------------------------


def create_spool(session: Session, now: datetime | None = None, **fields: Any) -> Spool:
    spool = Spool(**fields)
    session.add(spool)
    session.flush()
    session.add(
        SpoolLedger(
            spool_id=spool.id,
            movement_type="opening",
            weight_delta_g=spool.opening_weight_g,
            occurred_at=now or utcnow(),
            idempotency_key=f"spool:{spool.id}:opening",
        )
    )
    session.flush()
    return spool


def spool_remaining_g(session: Session, spool_id: str) -> Decimal:
    deltas = session.scalars(
        select(SpoolLedger.weight_delta_g).where(SpoolLedger.spool_id == spool_id)
    )
    return sum(deltas, Decimal(0))


def add_adjustment(
    session: Session, spool: Spool, weight_delta_g: Decimal, notes: str, key: str | None
) -> SpoolLedger:
    entry = SpoolLedger(
        spool_id=spool.id,
        movement_type="adjustment",
        weight_delta_g=weight_delta_g,
        occurred_at=utcnow(),
        idempotency_key=f"adjustment:{spool.id}:{key}" if key else None,
        notes=notes,
    )
    if key:
        existing = session.scalars(
            select(SpoolLedger).where(SpoolLedger.idempotency_key == entry.idempotency_key)
        ).first()
        if existing is not None:
            return existing
    session.add(entry)
    session.flush()
    return entry


def assign_spool(session: Session, job: Job, spool: Spool, now: datetime | None = None) -> None:
    if job.spool_id is not None and job.spool_id != spool.id:
        raise DomainError("spool_already_assigned", "job is already assigned to another spool")
    job.spool_id = spool.id
    if job.finalised_at is not None:
        deduct_spool(session, job, now or utcnow())


def deduct_spool(session: Session, job: Job, now: datetime) -> SpoolLedger | None:
    """Deduct a finalised job's filament once, guarded by a unique idempotency key."""
    spool = session.get(Spool, job.spool_id) if job.spool_id else None
    if spool is None or not job.filament_used_mm or job.filament_used_mm <= 0:
        return None
    key = f"job:{job.id}:usage"
    existing = session.scalars(
        select(SpoolLedger).where(SpoolLedger.idempotency_key == key)
    ).first()
    if existing is not None:
        return existing
    mass = filament_mass_g(job.filament_used_mm, spool.diameter_mm, spool.density_g_cm3)
    entry = SpoolLedger(
        spool_id=spool.id,
        job_id=job.id,
        movement_type="usage",
        weight_delta_g=-mass,
        occurred_at=now,
        idempotency_key=key,
        notes=f"{job.state} job; length from Moonraker print_stats (estimated mass)",
    )
    try:
        with session.begin_nested():
            session.add(entry)
            session.flush()
    except IntegrityError:
        return session.scalars(select(SpoolLedger).where(SpoolLedger.idempotency_key == key)).one()
    if spool.purchase_cost is not None and spool.currency:
        session.add(
            JobCost(
                job_id=job.id,
                kind="filament",
                revision=1,
                currency=spool.currency,
                amount=filament_cost(mass, spool.purchase_cost, spool.opening_weight_g),
                details={
                    "mass_g": str(mass),
                    "length_mm": job.filament_used_mm,
                    "spool_id": spool.id,
                    "mass_basis": "estimated from filament length, diameter and density",
                },
                computed_at=now,
            )
        )
    session.flush()
    return entry


def terminal(state: str) -> bool:
    return state in TERMINAL_STATES
