# Phase 3 — Core backend

Status: **Implemented and tested; not yet run against the real printer**

## Implemented

- [x] Core schema (migration `0002_core_schema`): agents, printers, calibration
  profiles, tariffs, events, samples, spools, jobs, spool ledger, job energy, job costs.
- [x] Idempotent ingest (`POST /api/v1/agents/{id}/sync`) with token auth.
- [x] Job finalisation; per-job energy and electricity cost stored with the
  calibration **profile version**; filament cost via the spool ledger.
- [x] Spool ledger with one usage deduction per job; adjustments; late assignment.
- [x] Recalculation as an explicit new revision.
- [x] Agent sync client with bounded jittered backoff; delivery marked only on ack.
- [x] ADR 0006; migration/model drift test; end-to-end Agent → Core test.

## Run it

```
$env:STUNSAIL_DATABASE_URL = "sqlite:///./data/core.db"
uv run alembic upgrade head
uv run uvicorn stunsail_api.main:app --host 0.0.0.0 --port 8000
```

Register the Agent (`POST /api/v1/agents` with `{"agent_id": "...", "name": "..."}`),
store the returned token in `STUNSAIL_AGENT_TOKEN`, set `agent.core_url` (for example
`http://host:8000`) in `agent.yaml`, then `uv run stunsail-agent run --config ...`.
Create a calibration profile, a printer linked to the agent, a tariff and a spool via the API.

## Not yet met

- [ ] Real print synced end to end against the printer (manual).
- [ ] Meter calibration (Phase 2) is still pending; costs are estimates until then.
- [ ] Admin API is open unless `STUNSAIL_ADMIN_TOKEN` is set.
