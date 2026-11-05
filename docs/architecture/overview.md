# Architecture overview

StunSail is a local-first platform designed to run all-in-one on a printer host
or split into a Core and outbound-connected Agents. Initial releases coexist
with Mainsail/Fluidd; they do not depend on them being open.

## Responsibilities and dependencies

- **Core** (`services/core`) owns canonical printers, jobs, spools, tariffs,
  calibration, cost calculations, persistence, and entitlement enforcement.
- **API** (`apps/api`) exposes explicit, versioned HTTP/WebSocket contracts and
  delegates domain behavior to Core. UI and Agents never access Core's database.
- **Agent** (`services/agent`) discovers local Moonraker capabilities, observes
  job and telemetry state, and persists observations locally before delivery.
  It does not decide canonical job, spool, or cost state.
- **Moonraker package** (`packages/moonraker`) provides the reusable HTTP and
  WebSocket client used by Agent. Field availability and semantics must be
  verified against the target installation.
- **Shared models** (`packages/shared-models`) contains models shared by Python
  packages. Cross-language wire contracts are canonical JSON Schema documents
  under `packages/shared-models/contracts/`.
- **UI** (`apps/web`) is a presentation client of documented Core APIs; UI
  visibility is not an authorization boundary.

The API prefix is `/api/v1`. Agent event envelopes carry a contract version,
stable event and Agent identifiers, a per-Agent monotonic sequence, observation
time, event type, and opaque typed payload. A breaking wire change requires a
new schema version and a compatibility plan. Core deduplicates before applying
domain effects. Store both observation and receipt times when ingestion is
implemented.

## Persistence and data integrity

SQLite is the initial Core and Agent persistence target. Alembic revisions are
the only schema-change mechanism. Use stable IDs, UTC timestamps, foreign keys,
transactional finalization, and unique idempotency keys. Preserve raw evidence
and provenance for derived energy and filament values. Use decimal or integer
minor units for currency. Avoid PostgreSQL-incompatible SQLite shortcuts.

The final logical schema will be introduced with Core domain implementation;
the Phase 0 migration baseline is intentionally empty.

## Deployment modes

- **Standalone (default):** Core/API/UI and Agent share one Linux host; Agent
  observes a local Moonraker instance. Data and configuration are local.
- **Agent-only:** Agent runs near one or more Moonraker instances, buffers
  durably, and initiates authenticated TLS communication to an existing Core.
- **Multi-host fleet:** later topology; one Core coordinates multiple Agents.

Service identities, target paths, configuration ownership, and network
assumptions are specified in `deployment/installer/configs/README.md`. The exact
co-located Core-Agent transport is intentionally deferred until implementation.

## Quality invariants

- No normal local operation depends on a cloud service or permanent internet.
- Do not expose Moonraker publicly; secure remote access is a later phase.
- Mark estimates as estimates, retain gaps, and never reconstruct missing energy
  as though measured.
- Make job finalization and spool deductions retry-safe and auditable.
- Printer-control operations, when introduced, are explicit, authorized, and
  audited.
- Keep the Community edition useful; licensing must not affect essential
  printing, local access, or data export.
