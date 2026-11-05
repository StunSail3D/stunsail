# ADR 0007: Web UI and static serving

Status: Accepted

## Context

StunSail 0.1 must be installable by one user on a LAN host without a separate
web server, and the UI must only use documented Core APIs.

## Decision

- The UI is a Vue 3 + TypeScript single-page app using hash-based routing
  (`#/jobs`). Hash routing means the API can serve the built files with plain
  static hosting and no SPA fallback rules.
- When `STUNSAIL_WEB_DIR` points at `apps/web/dist`, the API mounts it at `/`.
  API routes stay under `/api/v1`. Unset, the API serves no UI (Agent-only and
  development setups).
- Money, energy and quantities arrive as decimal strings and are formatted for
  display only; the UI never sums money across currencies (the summary reports
  `mixed_currencies` instead).
- Every energy and cost figure is labelled "Estimated (not meter-calibrated)"
  until its profile is calibrated. Coverage below 90% is flagged, because gaps
  are not estimated and energy may be understated.
- The admin API is open unless `STUNSAIL_ADMIN_TOKEN` (16+ characters) is set.
  The UI keeps the token in `localStorage` and prompts after a 401. This is a
  LAN-only baseline, not internet-grade authentication; do not expose the port.
- Spool price changes apply to future prints only. Power profiles are
  immutable; a correction is a new version.

## Consequences

- One process serves API and UI, which keeps the 0.1 install simple.
- A future reverse proxy or history-mode routing is possible without API changes.
- Storing the token in `localStorage` is acceptable only under the LAN-only
  security boundary of ADR 0004.
