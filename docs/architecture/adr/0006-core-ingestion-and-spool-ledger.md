# ADR 0006: Core ingestion, idempotency and spool ledger

Status: Accepted

## Context

The Agent delivers samples and events to Core over an unreliable link and may
resend anything. Core must never double-count a job, double-deduct filament, or
invent energy it has no evidence for.

## Decision

- **Delivery is at-least-once; Core makes it effectively once.** Events are unique
  on `(agent_id, event_id)` and `(agent_id, sequence)`; samples on
  `(agent_id, agent_sequence)`. Duplicates are acknowledged without effect. A
  reused sequence with a different event id is a 409 and rolls back the whole batch.
- **The Agent marks delivered only what Core acknowledges**, and sends events only
  after the samples they depend on, so a job never finalises before its samples arrive.
- **Jobs finalise once.** Later corrections are explicit new energy revisions
  (`POST /jobs/{id}/recalculate`), never in-place edits.
- **Every result records its basis**: the energy row stores the calibration profile
  version and `basis` (`estimated` unless the profile is meter-calibrated). With no
  profile or no samples, no energy is produced.
- **Filament is an append-only ledger.** Usage is keyed `job:{id}:usage`, so retries,
  duplicate terminal events, late spool assignment and restarts deduct at most once.
  A job's spool cannot be reassigned (409).
- Money and weights are stored as decimal text; timestamps are UTC and naive
  datetimes are rejected.
- Core uses Alembic (ADR 0003); a test fails if models and migrations drift.

## Security note

Agent endpoints require the per-agent bearer token (stored as a SHA-256 hash).
Management endpoints require `STUNSAIL_ADMIN_TOKEN` (16+ characters) **only when it
is set**; with it unset the management API is open. Acceptable on a trusted LAN
only; set the token before exposing Core.

## Agent registration

Choose an `agent_id` in the Agent config, call `POST /api/v1/agents`, and put the
one-time returned token in `STUNSAIL_AGENT_TOKEN` on the Agent host.
