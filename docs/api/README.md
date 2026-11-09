# API documentation

The API is versioned under `/api/v1`; OpenAPI is generated from the FastAPI application in `apps/api`.

`POST /api/v1/agents/{agent_id}/reset-token` requires the admin credential when
configured. It replaces the existing Agent token immediately and returns
`{"agent_id": "...", "token": "..."}` once. Store the token securely and
restart the Agent with `STUNSAIL_AGENT_TOKEN` set to it. The Agent's identity,
printer, jobs and buffered data are unchanged. If the response is lost, reset
again to obtain a new token. An unknown Agent returns 404.

`POST /api/v1/agents/{agent_id}/revoke` requires the admin credential when
configured and disables that Agent's credential without deleting its records.
Syncs authenticated after revocation are rejected; an already executing sync
may still complete. Resetting the token re-enables access with a new credential.
An unknown Agent returns 404.

Each Agent currently supports one registered printer. Creating another printer
for an assigned Agent returns `409 agent_printer_exists`. If older data already
contains multiple printers for an Agent, live status and sync return
`409 ambiguous_agent_printers` instead of attributing data to the wrong printer.
Agent sync also rejects reused sample sequences or event IDs with different data
as `409 sample_conflict` or `409 event_conflict`; exact replays remain safe.

`GET /api/v1/settings/currency` and `PUT /api/v1/settings/currency` use the
admin credential when configured. The shared setting is
`{"currency": "ZAR", "symbol": "R"}` by default; PUT accepts a three-letter
uppercase currency code and a nonblank symbol of up to 16 characters. Changing
it does not convert or rewrite existing spool prices, tariffs, or job costs.
