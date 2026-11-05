# StunSail

StunSail is a local-first, self-hosted platform for monitoring Klipper printers
and understanding the cost of each print. The first release focuses on reliable
print records, filament accounting, and explicitly estimated electricity costs.

This is the public Community repository. Proprietary Pro and Fleet modules live
in the separate private `stunsail-commercial` repository and build on the
documented plugin SDK in `packages/plugin-sdk`. Phase 0 foundation status and
acceptance checks are in the [Phase 0 checklist](docs/development/phase-0-checklist.md).

## Repository map

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

Core owns business truth and database writes. The Agent observes Moonraker and
persists collected events before delivery. The UI communicates only through
documented Core APIs. Shared contracts are versioned independently from runtime
packages.

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

The initial API health route is `GET /api/v1/health`. No printer-control,
Moonraker, licensing, or remote-access behavior is implemented in Phase 0.

## Project direction

- Standalone (Core + Agent together) is the default deployment; Agent-only is
  for remote printer hosts.
- Moonraker HTTP and WebSocket APIs are the initial printer integration.
- SQLite is the initial database; migrations must remain portable to PostgreSQL.
- The initial access model is single-user and local-network-only.
- Power is an estimate until calibrated against a meter; measured and estimated
  values must never be conflated.
- Community, Pro, and Fleet boundaries are documented, but licensing terms are
  intentionally undecided pending legal review.

See [architecture](docs/architecture/overview.md),
[operations](docs/architecture/operations.md), and the [security baseline](docs/architecture/security.md).
