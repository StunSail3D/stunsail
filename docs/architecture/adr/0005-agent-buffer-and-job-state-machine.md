# ADR 0005: Agent local buffer and job state machine

Status: Accepted (Phase 1 prototype)

## Context

The Agent must observe Moonraker independently of any browser, persist evidence
before any delivery, and survive restarts and Moonraker outages.

## Decision

- The Agent buffer is its own SQLite file (WAL, `synchronous=FULL`) holding
  `events` (contract v1 envelopes with a monotonic `sequence`), `samples`
  (timestamped raw status snapshots with a quality flag), `jobs`, and `kv`.
- The buffer schema is versioned with `PRAGMA user_version` and an ordered,
  append-only migration list in `stunsail_agent.store`. It is separate from the
  Core schema, which remains managed only by Alembic (ADR 0003).
- Jobs are a durable state machine: `printing`, `paused`, `completed`,
  `cancelled`, `error`, `interrupted`. Only non-terminal jobs are "active", so a
  job is finalised exactly once. Evidence (print_stats, history job) is stored.
- On every (re)connect the Agent reconciles a persisted active job against the
  current snapshot and Moonraker history; unresolved jobs become `interrupted`.
- Samples are only written while Klippy is ready. Missing time is recorded as a
  `telemetry.gap` event, never interpolated.
- Sessions retry with bounded exponential backoff and re-subscribe each time.
- Subscribed objects are chosen from the printer's discovered object list.

## Consequences

Field semantics (e.g. heater `power` and units) are stored raw and must be
verified on the real printer before the Phase 2 estimator relies on them.
Event delivery to Core (`delivered` column) is deferred to a later phase.
