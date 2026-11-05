# Phase 4 checklist: UI and StunSail 0.1

## Delivered

- [x] Dashboard: live temperatures, progress, stale-data warning, month summary, recent jobs (`GET /printers/{id}/live`).
- [x] Print history with state filter and paging; job detail with cost breakdown, estimated-energy badge, coverage warning, spool assignment and recalculation.
- [x] Spools: create (material density presets), edit, archive, ledger adjustments (`PATCH /spools/{id}`).
- [x] Settings: admin token, agent registration (token shown once), printers, tariffs, power profile versions.
- [x] Reports: date-range summary and CSV export with spreadsheet formula guard.
- [x] API serves the built UI via `STUNSAIL_WEB_DIR` ([ADR 0007](../architecture/adr/0007-web-ui-and-static-serving.md)).
- [x] Automated tests: backend integration (`tests/integration/test_reports_api.py`) and frontend (vitest).

## Run it

```powershell
Set-Location apps/web; npm ci; npm run build; Set-Location ../..
$env:STUNSAIL_DATABASE_URL = "sqlite:///data/stunsail.db"
$env:STUNSAIL_WEB_DIR = "$PWD/apps/web/dist"
# optional: $env:STUNSAIL_ADMIN_TOKEN = "<16+ characters>"
uv run alembic upgrade head
uv run uvicorn stunsail_api.main:app --host 0.0.0.0 --port 8000
```

Open `http://<host>:8000/`. For UI development use `npm run dev` in `apps/web`
(proxies `/api` to 127.0.0.1:8000).

First-time setup in Settings: add a power profile, register the agent (copy the
token into the Agent's `STUNSAIL_AGENT_TOKEN`), create a printer using that
profile, add a tariff, then add a spool.

## Exit-criteria verification (manual, still open)

- [ ] Run a real print on the printer with the Agent syncing to Core; confirm it appears in Print history with a plausible cost.
- [ ] Assign the spool, confirm the filament cost and spool ledger move.
- [ ] Restart the Agent mid-print; confirm one job, no duplicates.
- [ ] After wall-meter calibration (phase 2 checklist), add a calibrated profile version and recalculate.

## Known limits

- LAN-only, single-user. Do not expose the port to the internet.
- Energy is estimated until meter calibration; the 15 W electronics base load and light-load PSU efficiency points are unverified.
