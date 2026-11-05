# ADR 0002: Workspace tooling and contract versioning

- Status: Accepted for Phase 0
- Date: 2026-11-04

## Context

Core, Agent, UI, and shared packages must remain independently configured while
cross-process and cross-language communication remains stable.

## Decision

- Use a uv Python workspace with one pyproject per Python runtime/library
  package and a committed `uv.lock`.
- Use npm for the Vue application with a committed package lock.
- Keep the Agent wire envelope in canonical, versioned JSON Schema under
  `packages/shared-models/contracts/agent/vN`; Python shared models do not own or silently redefine the
  wire format.
- Start the Agent event envelope at contract version 1. Breaking changes require
  a new schema version; additive or payload-specific changes must be compatible
  with the negotiated contract.
- Use Ruff for Python lint/format, Prettier and Vue type-checking for the UI, and
  pytest/Vitest for automated tests.

## Consequences

Package dependencies make the Core/Agent direction explicit. Contract changes
require schema validation and compatibility review. The event payload vocabulary
and transport are deferred until the Moonraker prototype establishes actual
observations and sync behavior.
