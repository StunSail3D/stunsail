"""Live status, summary report and CSV export routes."""

import csv
import io
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from stunsail_core import models
from stunsail_core.service import DomainError

from . import schemas as s

ACTIVE_STATES = ("printing", "paused")
CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
ZERO = Decimal(0)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise HTTPException(
            422, detail={"code": "invalid_range", "message": "timestamps need a timezone offset"}
        )
    return value


def _csv_safe(value: Any) -> Any:
    # Stop spreadsheets from executing a G-code filename that starts like a formula.
    if isinstance(value, str) and value.startswith(CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


def build_router(
    session_dep: Any, admin: Any, job_detail: Callable[[Session, models.Job], s.JobDetail]
) -> APIRouter:
    router = APIRouter()

    @router.get("/printers/{printer_id}/live", tags=["printers"], dependencies=[admin])
    def live(printer_id: str, session: Annotated[Session, session_dep]) -> s.LiveOut:
        printer = session.get(models.Printer, printer_id)
        if printer is None:
            raise DomainError("printer_not_found", f"printer {printer_id!r} not found")
        agent = session.get(models.Agent, printer.agent_id)
        sample = session.scalars(
            select(models.TelemetrySample)
            .where(models.TelemetrySample.agent_id == printer.agent_id)
            .order_by(models.TelemetrySample.observed_at.desc())
            .limit(1)
        ).first()
        job = session.scalars(
            select(models.Job)
            .where(models.Job.agent_id == printer.agent_id, models.Job.state.in_(ACTIVE_STATES))
            .order_by(models.Job.started_at.desc())
            .limit(1)
        ).first()
        status = sample.payload.get("status") if sample else None
        return s.LiveOut(
            printer_id=printer.id,
            agent_last_sync_at=agent.last_sync_at if agent else None,
            sample_observed_at=sample.observed_at if sample else None,
            sample_age_s=(datetime.now(UTC) - sample.observed_at).total_seconds()
            if sample
            else None,
            status=status if isinstance(status, dict) else None,
            active_job=s.JobOut.model_validate(job) if job else None,
        )

    def finalised_jobs(
        session: Session, start: datetime | None, end: datetime | None
    ) -> list[models.Job]:
        query = (
            select(models.Job)
            .where(models.Job.finalised_at.is_not(None))
            .order_by(models.Job.started_at)
        )
        if start:
            query = query.where(models.Job.started_at >= start)
        if end:
            query = query.where(models.Job.started_at < end)
        return list(session.scalars(query))

    @router.get("/reports/summary", tags=["reports"], dependencies=[admin])
    def summary(
        session: Annotated[Session, session_dep],
        date_from: Annotated[datetime | None, Query(alias="from")] = None,
        date_to: Annotated[datetime | None, Query(alias="to")] = None,
    ) -> s.SummaryOut:
        start, end = _aware(date_from), _aware(date_to)
        details = [job_detail(session, j) for j in finalised_jobs(session, start, end)]
        currencies = {c.currency for d in details for c in d.costs}
        mixed = len(currencies) > 1
        buckets: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"jobs": 0, "kwh": ZERO, "g": ZERO, "elec": ZERO, "fil": ZERO}
        )
        total = {"kwh": ZERO, "g": ZERO, "elec": ZERO, "fil": ZERO}
        uncosted = 0
        for d in details:
            bucket = buckets[d.started_at.strftime("%Y-%m")]
            bucket["jobs"] += 1
            if not d.costs:
                uncosted += 1
            values = {
                "kwh": d.energy.kwh if d.energy else ZERO,
                "g": ZERO,
                "elec": ZERO,
                "fil": ZERO,
            }
            for c in d.costs:
                if c.kind == "electricity":
                    values["elec"] = c.amount
                else:
                    values["fil"] = c.amount
            usage = session.scalars(
                select(models.SpoolLedger.weight_delta_g).where(
                    models.SpoolLedger.job_id == d.id, models.SpoolLedger.movement_type == "usage"
                )
            )
            values["g"] = -sum(usage, start=ZERO)
            for key, value in values.items():
                total[key] += value
                bucket[key] += value
        return s.SummaryOut(
            currency=next(iter(currencies)) if len(currencies) == 1 else None,
            mixed_currencies=mixed,
            jobs=len(details),
            jobs_without_cost=uncosted,
            kwh=total["kwh"],
            filament_g=total["g"],
            electricity_cost=total["elec"],
            filament_cost=total["fil"],
            total_cost=total["elec"] + total["fil"],
            by_month=[
                s.SummaryBucket(
                    period=period,
                    jobs=b["jobs"],
                    kwh=b["kwh"],
                    filament_g=b["g"],
                    electricity_cost=b["elec"],
                    filament_cost=b["fil"],
                )
                for period, b in sorted(buckets.items())
            ],
        )

    @router.get("/export/jobs.csv", tags=["reports"], dependencies=[admin])
    def export_jobs(
        session: Annotated[Session, session_dep],
        date_from: Annotated[datetime | None, Query(alias="from")] = None,
        date_to: Annotated[datetime | None, Query(alias="to")] = None,
    ) -> Response:
        start, end = _aware(date_from), _aware(date_to)
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(
            [
                "job_id",
                "filename",
                "state",
                "started_at",
                "ended_at",
                "duration_s",
                "filament_used_mm",
                "spool_id",
                "energy_kwh",
                "energy_basis",
                "profile_version",
                "electricity_cost",
                "filament_cost",
                "total_cost",
                "currency",
            ]
        )
        query = select(models.Job).order_by(models.Job.started_at)
        if start:
            query = query.where(models.Job.started_at >= start)
        if end:
            query = query.where(models.Job.started_at < end)
        for job in session.scalars(query):
            d = job_detail(session, job)
            cost = {c.kind: c.amount for c in d.costs}
            writer.writerow(
                [
                    _csv_safe(v)
                    for v in (
                        d.id,
                        d.filename,
                        d.state,
                        d.started_at.isoformat(),
                        d.ended_at.isoformat() if d.ended_at else "",
                        d.duration_s,
                        d.filament_used_mm,
                        d.spool_id,
                        d.energy.kwh if d.energy else "",
                        d.energy.basis if d.energy else "",
                        d.energy.profile_version if d.energy else "",
                        cost.get("electricity", ""),
                        cost.get("filament", ""),
                        d.total_cost if d.total_cost is not None else "",
                        d.total_cost_currency or "",
                    )
                ]
            )
        return Response(
            out.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="stunsail-jobs.csv"'},
        )

    return router
