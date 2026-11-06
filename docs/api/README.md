# API documentation

The API is versioned under `/api/v1`; OpenAPI is generated from the FastAPI application in `apps/api`.

`POST /api/v1/agents/{agent_id}/reset-token` requires the admin credential when
configured. It replaces the existing Agent token immediately and returns
`{"agent_id": "...", "token": "..."}` once. Store the token securely and
restart the Agent with `STUNSAIL_AGENT_TOKEN` set to it. The Agent's identity,
printer, jobs and buffered data are unchanged. If the response is lost, reset
again to obtain a new token. An unknown Agent returns 404.
