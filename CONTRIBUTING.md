# Contributing

StunSail prioritizes trustworthy data, local-first operation, and small changes
that preserve the boundaries in `docs/architecture/overview.md`.

## Before changing code

- Read the applicable architecture decision records in `docs/architecture/adr`.
- Keep Core authoritative for jobs, spools, tariffs, calibration, and costs.
- Persist Agent observations before attempting delivery; do not make Core domain
  decisions in the Agent.
- Keep external contracts versioned and update contract tests when they change.
- Do not add printer control, remote access, or licensing workflows ahead of
  their roadmap phases.

## Coding and tests

- Python: Python 3.11+, four-space indentation, type annotations, Ruff lint and
  formatting.
- UI: Vue 3, TypeScript, two-space indentation, Prettier, and Vitest.
- Use UTC timestamps for persisted time and decimal or integer-minor-unit
  arithmetic for money.
- Preserve raw evidence and provenance for derived values. Represent sample gaps
  and uncertainty explicitly; never fabricate measurements.
- Add unit tests for domain rules, integration tests for component boundaries,
  and hardware-in-the-loop tests for behavior that requires a real printer.
- Run the checks listed in the README before requesting review.

## Changes to data and contracts

- Use Alembic revisions for every database schema change; never edit a migration
  that has already been released.
- Review generated migrations before committing them. Test both upgrade and
  downgrade on SQLite, and avoid SQLite-only schema assumptions.
- Breaking API or Agent contract changes require a new version and a documented
  compatibility plan.
- Never commit credentials, private keys, live printer configuration, or
  customer data. Add only redacted examples.

## Pull requests

Describe the behavior change, tests run, migration/contract impact, and any
operational or security implications. Keep unrelated refactors out of a focused
change.
