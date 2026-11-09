# API documentation

The API is versioned under `/api/v1`; OpenAPI is generated from the FastAPI application in `apps/api`.

`POST /api/v1/agents/{agent_id}/reset-token` requires the admin credential when
configured. It replaces the existing Agent token immediately and returns
`{"agent_id": "...", "token": "..."}` once. Store the token securely and
restart the Agent with `STUNSAIL_AGENT_TOKEN` set to it. The Agent's identity,
printer, jobs and buffered data are unchanged. If the response is lost, reset
again to obtain a new token. An unknown Agent returns 404.

`GET /api/v1/settings/currency` and `PUT /api/v1/settings/currency` use the
admin credential when configured. The shared setting is
`{"currency": "ZAR", "symbol": "R"}` by default; PUT accepts a three-letter
uppercase currency code and a nonblank symbol of up to 16 characters. Changing
it does not convert or rewrite existing spool prices, tariffs, or job costs.
