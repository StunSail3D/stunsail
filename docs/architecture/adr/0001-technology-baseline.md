# ADR 0001: Technology baseline

- Status: Accepted for Phase 0
- Date: 2026-11-04

## Context

The roadmap and technical specification choose Python services, a Vue/TypeScript
UI, Moonraker's public HTTP/WebSocket APIs, SQLite first, and PostgreSQL as a
later supported Core database.

## Decision

- Python 3.11+ with FastAPI for Core's API and Python for Agent.
- Vue 3 and TypeScript for the browser UI.
- SQLite for initial Core and Agent persistence; preserve PostgreSQL portability.
- Moonraker HTTP and WebSocket APIs; no Klipper extra is required for the initial
  product.
- Run production services under Linux systemd.

## Consequences

The repository has independently installable Python packages and a separate
Node-based UI. Exact supported Linux distributions, Moonraker field semantics,
and production dependency versions are verified against target hardware before
release, not assumed by this ADR.
