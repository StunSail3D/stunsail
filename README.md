# StunSail

StunSail is a local-first, self-hosted platform for monitoring Klipper printers
and understanding the cost of each print. It records print jobs, tracks filament
consumption against a spool inventory, and computes **explicitly estimated**
electricity costs. It runs alongside Mainsail/Fluidd and does not depend on them
being open.

**Status: experimental.** The current focus is reliable print records, filament
accounting, and credible electricity-cost estimates. StunSail **monitors** prints;
it does not control the printer. Installation, distributed Agents, TLS, and
backup/restore/uninstall tooling exist and have been exercised on a real printer
host, but they are not production-ready. See the
[Phase 5 checklist](docs/development/phase-5-checklist.md) for what was validated
and what remains open.

This is the public **Community** repository. Proprietary **Pro** and **Fleet**
modules are planned for the separate private `stunsail-commercial` repository and
build on the documented plugin SDK in `packages/plugin-sdk`; they are **not
included here**. Edition boundaries below are documented intent — licensing and
entitlement enforcement are not yet implemented.

## What the UI does today

The web UI (Vue 3 + TypeScript) is a client of the documented Core APIs:

- **Dashboard** — live temperatures, print progress, stale-data warnings, a month
  summary, and recent jobs. Cards are draggable/resizable; layouts are stored per
  browser, page, and screen size.
- **Print history** — job list with state filter and paging; per-job detail with a
  filament + electricity cost breakdown, an estimated-energy badge, coverage
  warnings, spool assignment, and recalculation.
- **Spools** — create (with material density presets), edit, archive, and ledger
  adjustments; filament consumption is deducted from the assigned spool.
- **Reports** — date-range summaries and CSV export (with a spreadsheet formula
  guard).
- **Settings** — admin token, Agent registration (token shown once) with reset and
  revocation, printers, electricity tariffs, power-profile versions, and a shared
  currency.

Energy is an **estimate** until calibrated against a meter; estimated and measured
values are never conflated. StunSail never sends control commands to the printer.
Printer control (pause/resume/cancel/emergency stop), macros, webcam, multi-user
accounts, and secure remote access are **later phases, not current capabilities**.

## Editions

The commercial model is an open-source Community edition with proprietary paid
Pro and Fleet extensions. The Community edition must remain genuinely useful as a
standalone self-hosted product.

| Edition | Audience | Intended scope |
| --- | --- | --- |
| **Community** (free, this repo) | Hobbyists, single printer | One printer; standalone install; monitoring; print history; basic spool inventory and filament tracking; estimated electricity and print costs; basic dashboard/reports; local-network access; export/backup; update notices and manual updates. |
| **Pro** (paid, planned) | Advanced enthusiasts, small setups | Multiple printers/hosts; advanced analytics and reports; deeper spool management; external meter/smart-plug integrations; custom dashboards; advanced notifications; scheduled reports; secure remote access. |
| **Fleet** (paid, planned) | Print farms, organisations | Larger fleets; multi-user access and role-based permissions; groups/locations; fleet-wide reports; operator audit trails; utilisation and production metrics; central administration and advanced alerting. |

Pro and Fleet are **planned proprietary modules, not shipped features**. The
distributed-Agent architecture in this repository supports multiple Agents and
hosts, but the edition entitlements that would gate Community (one printer) versus
Pro/Fleet are **not implemented yet**.

Free-feature protection (design commitments): basic printer operation,
safety-critical controls, print history, basic filament tracking, and basic cost
calculation are not paywalled; users own and can export their data; a subscription
lapse must not stop a print, disable local access, or lock users out of their data;
ordinary local operation never requires a permanent internet connection. The exact
open-source licence, proprietary module boundary, and contribution policy are
explicit legal decisions still to be made before public release.

## Installation

Installation is **experimental** and has been validated on a real printer host, but
not on every supported platform. Supported targets: Debian 12, Raspberry Pi OS
Bookworm, Ubuntu 24.04, and Armbian 26 (Bookworm/Noble base) on x86-64 or AArch64.
Debian 13 Trixie is an opt-in **experimental** platform.

Two deployment modes share one codebase:

- **Standalone (default)** — Core/API/UI and an Agent on one Linux host; the Agent
  observes a local Moonraker instance.
- **Agent-only** — an Agent near one or more Moonraker instances, buffering durably
  and connecting outbound over authenticated TLS to an existing Core.

A guided installer and an allowlisted Debian package are provided. The installer
creates dedicated service accounts, prepares a locked runtime, migrates the
database, and starts systemd services. Core binds to loopback only; Moonraker is
never exposed. An experimental TLS frontend (port 8443) can expose the Core UI/API
over HTTPS using a private CA generated on a trusted PC. Backup, verify, restore,
offline upgrade/rollback, and a backup-first complete uninstall are included.

See the [installer documentation](deployment/installer/README.md) for the exact
commands, confirmation flags, and safety notes, and
[TLS frontend](docs/architecture/tls_frontend.md) for certificate generation and
provisioning. Do not expose Core or the frontend to the internet.

## Architecture

Core owns business truth and database writes. The Agent observes Moonraker and
persists collected events locally before delivery. The UI communicates only through
documented Core APIs. Shared wire contracts are versioned independently from runtime
packages.

| Path | Responsibility |
| --- | --- |
| `apps/api` | FastAPI entry point and versioned HTTP API |
| `apps/web` | Vue 3 and TypeScript user interface |
| `services/core` | Canonical domain logic and persistence |
| `services/agent` | Local Moonraker observation and durable collection |
| `packages/shared-models` | Shared typed models |
| `packages/moonraker` | Reusable Moonraker HTTP/WebSocket client |
| `packages/plugin-sdk` | Documented, versioned extension interfaces |
| `packages/cost-engine` | Filament and electricity cost calculations |
| `packages/shared-models/contracts` | Versioned Agent event envelope schemas |
| `plugins/examples` | Example plugins built on the plugin SDK |
| `database/migrations` | Alembic database migration history |
| `database/schemas` | Reference schema documentation |
| `deployment/installer` | Installer and Standalone/Agent-only config examples |
| `deployment/debian`, `deployment/systemd` | Debian packaging and service units |
| `tests` | Unit, integration, and hardware-in-the-loop tests |
| `docs` | Architecture decisions and operating assumptions |

SQLite is the initial database; migrations remain portable to PostgreSQL. The
initial access model is single-user and local-network-only. Power is an estimate
until calibrated against a meter.

## Development setup

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 22.12+, and npm.

```powershell
uv sync --locked --all-packages --group dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run alembic upgrade head
uv run alembic downgrade base

Set-Location apps/web
npm ci
npm run check
npm run test
npm run build
```

The Python workspace and frontend dependencies are locked in `uv.lock` and
`apps/web/package-lock.json`. The API skeleton is served locally with:

```powershell
uv run uvicorn stunsail_api.main:app --app-dir apps/api/src --reload
```

The API health route is `GET /api/v1/health`. To serve the web UI from the API,
build it and set `STUNSAIL_WEB_DIR`; see the
[Phase 4 checklist](docs/development/phase-4-checklist.md) for the full
run-and-setup steps.

## Project status and direction

Phases 0–4 (foundation, Moonraker integration, energy engine, Core, and the 0.1 UI)
are built and tested. Phase 5 (installation, multi-printer and distributed Agents,
TLS, backup/restore/upgrade/uninstall) is built and has been validated on a real
host; the offline upgrade/rollback real-systemd validation is deferred to the next
round.

Later phases are **planned, not shipped**: everyday printer management and control
(Phase 6), a fuller Mainsail/Fluidd alternative with multi-user accounts and secure
remote access (Phase 7), and production readiness for 1.0 (Phase 8). Release
milestones progress from 0.1 (single-printer cost tracking) through 0.2
(multi-printer/distributed Agents) toward 1.0 (production-ready platform). The
[phase checklists](docs/development/README.md) record what each phase delivered and
its exit criteria; the staged plan is a planning baseline, not a delivery promise.

Known limits: experimental and not production-ready; LAN-only and single-user;
energy is estimated until calibration; licensing/entitlements are not implemented.

See [architecture](docs/architecture/overview.md),
[operations](docs/architecture/operations.md), and the
[security baseline](docs/architecture/security.md).
