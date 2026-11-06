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

Git Bash equivalent (run from the `stunsail` folder):

```bash
unset VIRTUAL_ENV   # clear any stale environment from another path
(cd apps/web && npm ci && npm run build)
export STUNSAIL_DATABASE_URL="sqlite:///data/stunsail.db"
export STUNSAIL_WEB_DIR="$PWD/apps/web/dist"
# optional: export STUNSAIL_ADMIN_TOKEN="<16+ characters>"
uv run alembic upgrade head
uv run uvicorn stunsail_api.main:app --host 0.0.0.0 --port 8000
```

Open `http://<host>:8000/`. For UI development use `npm run dev` in `apps/web`
(proxies `/api` to 127.0.0.1:8000).

Cards can be moved by their drag bar and resized from their lower-right corner.
Layouts are stored in the browser, separately for each page and screen size:
three columns at 1200 px and above, two at 768–1199 px, and one below 768 px.
Use **Reset layout** to restore the current page and screen size. Card contents
scroll when they exceed the selected size. The logo button collapses the
sidebar; on tablet and mobile, the expanded sidebar overlays the page and
closes when a navigation link is selected or Escape is pressed.

For the Windows VS Code workspace rooted at `project`, select **StunSail: API
+ Web + Agent** in Run and Debug and press F5. The API migrates
`data/stunsail-dev.db` before starting; the web and Agent wait up to 90 seconds
for its health endpoint. Stop any existing API on port 8000 and any other
Agent using the same identity or buffer before starting. Configure the Agent's
`core_url` to reach this API and set its token in the git-ignored `stunsail/.env`.
The F5 database is separate from `data/stunsail.db`, so registration and the
token must belong to the dev database. The API listens on all interfaces;
keep it on a trusted LAN and configure an admin token if appropriate.

First-time setup in Settings: add a power profile, register the agent (copy the
token into the Agent's `STUNSAIL_AGENT_TOKEN`), create a printer using that
profile, add a tariff, then add a spool.

To replace a lost or exposed Agent token, use **Settings → Agents → Reset
token**, confirm, and copy the new token immediately into the Agent's
`STUNSAIL_AGENT_TOKEN` environment variable (for F5, `stunsail/.env`). Restart
the Agent; the old token stops working as soon as the reset succeeds. Do not
delete the Agent, printer, buffer, or database. If the new token is lost, reset
it again. This changes credentials only in the database served by that API.

## Exit-criteria verification (manual, still open)

- [ ] Run a real print on the printer with the Agent syncing to Core; confirm it appears in Print history with a plausible cost.
- [ ] Assign the spool, confirm the filament cost and spool ledger move.
- [ ] Restart the Agent mid-print; confirm one job, no duplicates.
- [ ] After wall-meter calibration (phase 2 checklist), add a calibrated profile version and recalculate.

## Known limits

- LAN-only, single-user. Do not expose the port to the internet.
- Energy is estimated until meter calibration; the 15 W electronics base load and light-load PSU efficiency points are unverified.
