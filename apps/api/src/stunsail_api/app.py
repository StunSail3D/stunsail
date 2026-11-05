"""Application factory and v1 routes."""

import hmac
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from stunsail_core import models, service
from stunsail_core.db import make_engine, make_session_factory
from stunsail_core.service import DomainError
from stunsail_core.settings import CoreSettings
from stunsail_cost_engine import CalibrationProfile as EngineProfile

from . import schemas as s
from .reports import build_router

API_VERSION = "v1"


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def create_app(
    settings: CoreSettings | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> FastAPI:
    app = FastAPI(title="StunSail API", version="0.1.0")
    app.state.settings = settings
    app.state.session_factory = session_factory

    def get_settings() -> CoreSettings:
        if app.state.settings is None:
            app.state.settings = CoreSettings.from_env()
        return app.state.settings

    def get_session() -> Iterator[Session]:
        if app.state.session_factory is None:
            app.state.session_factory = make_session_factory(
                make_engine(get_settings().database_url)
            )
        with app.state.session_factory() as session:
            yield session

    SessionDep = Annotated[Session, Depends(get_session)]

    def require_admin(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = get_settings().admin_token
        if expected is None:
            return
        supplied = _bearer(authorization)
        if supplied is None or not hmac.compare_digest(supplied, expected):
            raise HTTPException(
                401, detail={"code": "unauthorized", "message": "admin token required"}
            )

    Admin = Depends(require_admin)

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        status = 404 if exc.code.endswith("_not_found") else 409
        return JSONResponse(
            status_code=status, content={"error": {"code": exc.code, "message": str(exc)}}
        )

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        detail = (
            exc.detail if isinstance(exc.detail, dict) else {"code": "error", "message": exc.detail}
        )
        return JSONResponse(status_code=exc.status_code, content={"error": detail})

    def fetch(session: Session, model: type, key: str, code: str) -> Any:
        row = session.get(model, key)
        if row is None:
            raise DomainError(code, f"{model.__name__.lower()} {key!r} not found")
        return row

    api = APIRouter(prefix=f"/api/{API_VERSION}")

    # --- system -------------------------------------------------------------------------
    @api.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "api_version": API_VERSION}

    @api.get("/health/ready", tags=["system"])
    def ready(session: SessionDep) -> JSONResponse:
        try:
            session.execute(text("SELECT 1 FROM alembic_version")).one()
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "reason": "database not migrated"},
            )
        return JSONResponse(content={"status": "ready", "api_version": API_VERSION})

    # --- agents -------------------------------------------------------------------------
    @api.post("/agents", status_code=201, tags=["agents"], dependencies=[Admin])
    def register_agent(body: s.AgentIn, session: SessionDep) -> s.AgentRegistered:
        _, token = service.register_agent(session, body.agent_id, body.name)
        session.commit()
        return s.AgentRegistered(agent_id=body.agent_id, token=token)

    @api.get("/agents", tags=["agents"], dependencies=[Admin])
    def list_agents(session: SessionDep) -> list[s.AgentOut]:
        return [s.AgentOut.model_validate(a) for a in session.scalars(select(models.Agent))]

    @api.post("/agents/{agent_id}/sync", tags=["agents"])
    def sync(
        agent_id: str,
        body: s.SyncIn,
        session: SessionDep,
        authorization: Annotated[str | None, Header()] = None,
    ) -> s.SyncOut:
        token = _bearer(authorization)
        agent = service.authenticate_agent(session, agent_id, token) if token else None
        if agent is None:
            raise HTTPException(
                401, detail={"code": "unauthorized", "message": "invalid agent credentials"}
            )
        if any(e.agent_id != agent_id for e in body.events):
            raise HTTPException(
                422,
                detail={"code": "agent_mismatch", "message": "event agent_id differs from path"},
            )
        try:
            result = service.ingest_batch(
                session,
                agent,
                [x.model_dump() for x in body.samples],
                [x.model_dump() for x in body.events],
            )
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                409,
                detail={
                    "code": "sequence_conflict",
                    "message": "event sequence reused with a different event id",
                },
            ) from exc
        return s.SyncOut(**result.__dict__)

    # --- calibration profiles, printers, tariffs ------------------------------------------
    @api.post("/calibration-profiles", status_code=201, tags=["settings"], dependencies=[Admin])
    def create_profile(body: s.ProfileIn, session: SessionDep) -> s.ProfileOut:
        data = {
            **body.data,
            "name": body.name,
            "version": body.version,
            "calibrated_against_meter": body.calibrated_against_meter,
        }
        try:
            EngineProfile.from_snapshot(data)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                422, detail={"code": "invalid_profile", "message": f"invalid profile data: {exc!r}"}
            ) from exc
        row = models.CalibrationProfile(
            name=body.name,
            version=body.version,
            data=data,
            calibrated_against_meter=body.calibrated_against_meter,
        )
        session.add(row)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise DomainError("profile_exists", "profile name and version already exist") from exc
        return s.ProfileOut.model_validate(row)

    @api.get("/calibration-profiles", tags=["settings"], dependencies=[Admin])
    def list_profiles(session: SessionDep) -> list[s.ProfileOut]:
        rows = session.scalars(
            select(models.CalibrationProfile).order_by(
                models.CalibrationProfile.name, models.CalibrationProfile.version
            )
        )
        return [s.ProfileOut.model_validate(r) for r in rows]

    @api.post("/printers", status_code=201, tags=["printers"], dependencies=[Admin])
    def create_printer(body: s.PrinterIn, session: SessionDep) -> s.PrinterOut:
        fetch(session, models.Agent, body.agent_id, "agent_not_found")
        if body.calibration_profile_id:
            fetch(
                session, models.CalibrationProfile, body.calibration_profile_id, "profile_not_found"
            )
        row = models.Printer(**body.model_dump())
        session.add(row)
        session.commit()
        return s.PrinterOut.model_validate(row)

    @api.get("/printers", tags=["printers"], dependencies=[Admin])
    def list_printers(session: SessionDep) -> list[s.PrinterOut]:
        return [s.PrinterOut.model_validate(p) for p in session.scalars(select(models.Printer))]

    @api.patch("/printers/{printer_id}", tags=["printers"], dependencies=[Admin])
    def patch_printer(printer_id: str, body: s.PrinterPatch, session: SessionDep) -> s.PrinterOut:
        printer = fetch(session, models.Printer, printer_id, "printer_not_found")
        if body.calibration_profile_id:
            fetch(
                session, models.CalibrationProfile, body.calibration_profile_id, "profile_not_found"
            )
            printer.calibration_profile_id = body.calibration_profile_id
        if body.name:
            printer.name = body.name
        session.commit()
        return s.PrinterOut.model_validate(printer)

    @api.post("/tariffs", status_code=201, tags=["settings"], dependencies=[Admin])
    def create_tariff(body: s.TariffIn, session: SessionDep) -> s.TariffOut:
        row = models.Tariff(**body.model_dump())
        session.add(row)
        session.commit()
        return s.TariffOut.model_validate(row)

    @api.get("/tariffs", tags=["settings"], dependencies=[Admin])
    def list_tariffs(session: SessionDep) -> list[s.TariffOut]:
        rows = session.scalars(select(models.Tariff).order_by(models.Tariff.effective_from))
        return [s.TariffOut.model_validate(t) for t in rows]

    # --- spools -------------------------------------------------------------------------
    def spool_out(session: Session, spool: models.Spool) -> s.SpoolOut:
        out = s.SpoolOut.model_validate(spool)
        out.remaining_g = service.spool_remaining_g(session, spool.id)
        return out

    @api.post("/spools", status_code=201, tags=["spools"], dependencies=[Admin])
    def create_spool(body: s.SpoolIn, session: SessionDep) -> s.SpoolOut:
        if (body.purchase_cost is None) != (body.currency is None):
            raise HTTPException(
                422,
                detail={
                    "code": "invalid_spool",
                    "message": "purchase_cost and currency go together",
                },
            )
        spool = service.create_spool(session, **body.model_dump())
        session.commit()
        return spool_out(session, spool)

    @api.get("/spools", tags=["spools"], dependencies=[Admin])
    def list_spools(
        session: SessionDep,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[s.SpoolOut]:
        rows = session.scalars(
            select(models.Spool).order_by(models.Spool.created_at).limit(limit).offset(offset)
        )
        return [spool_out(session, r) for r in rows]

    @api.get("/spools/{spool_id}", tags=["spools"], dependencies=[Admin])
    def get_spool(spool_id: str, session: SessionDep) -> s.SpoolOut:
        return spool_out(session, fetch(session, models.Spool, spool_id, "spool_not_found"))

    @api.patch("/spools/{spool_id}", tags=["spools"], dependencies=[Admin])
    def patch_spool(spool_id: str, body: s.SpoolPatch, session: SessionDep) -> s.SpoolOut:
        spool = fetch(session, models.Spool, spool_id, "spool_not_found")
        changes = body.model_dump(exclude_unset=True)
        if ("purchase_cost" in changes) != ("currency" in changes):
            raise HTTPException(
                422,
                detail={
                    "code": "invalid_spool",
                    "message": "purchase_cost and currency go together",
                },
            )
        for field, value in changes.items():
            if value is None and field in ("name", "status"):
                continue
            setattr(spool, field, value)
        session.commit()
        return spool_out(session, spool)

    @api.get("/spools/{spool_id}/ledger", tags=["spools"], dependencies=[Admin])
    def spool_ledger(
        spool_id: str,
        session: SessionDep,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[s.LedgerOut]:
        fetch(session, models.Spool, spool_id, "spool_not_found")
        rows = session.scalars(
            select(models.SpoolLedger)
            .where(models.SpoolLedger.spool_id == spool_id)
            .order_by(models.SpoolLedger.id)
            .limit(limit)
            .offset(offset)
        )
        return [s.LedgerOut.model_validate(r) for r in rows]

    @api.post(
        "/spools/{spool_id}/adjustments", status_code=201, tags=["spools"], dependencies=[Admin]
    )
    def adjust_spool(spool_id: str, body: s.AdjustmentIn, session: SessionDep) -> s.LedgerOut:
        spool = fetch(session, models.Spool, spool_id, "spool_not_found")
        entry = service.add_adjustment(
            session, spool, body.weight_delta_g, body.notes, body.idempotency_key
        )
        session.commit()
        return s.LedgerOut.model_validate(entry)

    # --- jobs ---------------------------------------------------------------------------
    def job_detail(session: Session, job: models.Job) -> s.JobDetail:
        energy = session.scalars(
            select(models.JobEnergy)
            .where(models.JobEnergy.job_id == job.id)
            .order_by(models.JobEnergy.revision.desc())
        ).first()
        costs = []
        for kind in ("electricity", "filament"):
            latest = session.scalars(
                select(models.JobCost)
                .where(models.JobCost.job_id == job.id, models.JobCost.kind == kind)
                .order_by(models.JobCost.revision.desc())
            ).first()
            if latest is not None:
                costs.append(latest)
        currencies = {c.currency for c in costs}
        total = sum((c.amount for c in costs), start=0) if len(currencies) == 1 else None
        return s.JobDetail(
            **s.JobOut.model_validate(job).model_dump(),
            energy=s.EnergyOut.model_validate(energy) if energy else None,
            costs=[s.CostOut.model_validate(c) for c in costs],
            total_cost=total,
            total_cost_currency=next(iter(currencies)) if len(currencies) == 1 else None,
        )

    @api.get("/jobs", tags=["jobs"], dependencies=[Admin])
    def list_jobs(
        session: SessionDep,
        state: str | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[s.JobOut]:
        query = (
            select(models.Job).order_by(models.Job.started_at.desc()).limit(limit).offset(offset)
        )
        if state:
            query = query.where(models.Job.state == state)
        return [s.JobOut.model_validate(j) for j in session.scalars(query)]

    @api.get("/jobs/{job_id}", tags=["jobs"], dependencies=[Admin])
    def get_job(job_id: str, session: SessionDep) -> s.JobDetail:
        return job_detail(session, fetch(session, models.Job, job_id, "job_not_found"))

    @api.post("/jobs/{job_id}/spool", tags=["jobs"], dependencies=[Admin])
    def assign_job_spool(job_id: str, body: s.JobSpoolIn, session: SessionDep) -> s.JobDetail:
        job = fetch(session, models.Job, job_id, "job_not_found")
        spool = fetch(session, models.Spool, body.spool_id, "spool_not_found")
        service.assign_spool(session, job, spool)
        session.commit()
        return job_detail(session, job)

    @api.post("/jobs/{job_id}/recalculate", tags=["jobs"], dependencies=[Admin])
    def recalculate_job(job_id: str, session: SessionDep) -> s.JobDetail:
        job = fetch(session, models.Job, job_id, "job_not_found")
        if job.finalised_at is None:
            raise DomainError("job_not_finalised", "only finalised jobs can be recalculated")
        if service.compute_job_costs(session, job) is None:
            raise DomainError(
                "no_evidence", "printer has no calibration profile or the job has no samples"
            )
        session.commit()
        return job_detail(session, job)

    api.include_router(build_router(Depends(get_session), Admin, job_detail))
    app.include_router(api)

    web_dir = settings.web_dir if settings else os.environ.get("STUNSAIL_WEB_DIR")
    if web_dir and Path(web_dir).is_dir():
        # Hash-based routing in the web app means no SPA fallback is needed.
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app
