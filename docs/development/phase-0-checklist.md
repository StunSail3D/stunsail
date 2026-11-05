# Phase 0 — Architecture and project foundation

Status: **Complete** — 4 November 2026

The checkbox is checked only after the task is implemented and its relevant
validation has passed. Phase 0 establishes the repository and documented
interfaces; it does not include Moonraker collection or production deployment.

## Completion checklist

- [x] Create the monorepo, development tooling, CI checks, coding standards, and
  test layout.
- [x] Define Core, Agent, UI, and shared-package boundaries and a versioned
  Agent event contract.
- [x] Select Alembic for SQLite-first, PostgreSQL-portable schema migrations and
  establish migration review and testing discipline.
- [x] Define Standalone and Agent-only profiles, including service identities,
  filesystem paths, configuration, and secret handling.
- [x] Document structured logging, diagnostics, backup/restore,
  upgrade/rollback, and security assumptions.
- [x] Record architecture decisions for technology, package/contract boundaries,
  migrations, and deployment/security choices.

## Phase 0 verification

- [x] Python workspace installs; Ruff lint and format checks pass.
- [x] Python unit and integration tests pass.
- [x] Alembic upgrade and downgrade both pass on SQLite.
- [x] Frontend formatting/type checks, tests, and production build pass.
- [x] CI workflow covers the same checks on supported CI runtimes.

## Deferred decisions

These are explicitly outside Phase 0 completion and remain tracked for the
phase where evidence or legal review is available:

- Confirm target Raspberry Pi/Linux distribution, hardware resources, and
  Ender 3 V2 host/Klipper/Moonraker versions before Phase 1 hardware testing.
- Validate heater ratings, PSU efficiency, base load, tariff assumptions, and
  estimator accuracy against a wall meter before presenting accuracy claims.
- Finalize the physical Core-Agent local transport before implementing sync.
- Finalize the production database schema as Core domain behavior is defined.
- Select the Community licence, proprietary module terms, and contribution
  policy before public release; payment/licensing providers are later decisions.
- Select supported meter integrations and numerical accuracy thresholds after
  collecting baseline measurements.
