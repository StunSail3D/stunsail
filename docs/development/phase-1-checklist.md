# Phase 1 — Moonraker integration prototype

Status: **Implemented; hardware validation pending**

## Implemented (verified against mocks and a local WebSocket server)

- [x] Moonraker HTTP + WebSocket client (`packages/moonraker`).
- [x] Discovery of printer info and available objects; subscription limited to
  objects the printer exposes.
- [x] Heater, fan, `print_stats`, and `virtual_sdcard` capture (raw snapshots).
- [x] Job start/pause/resume/complete/cancel/error detection and restart
  reconciliation (ADR 0005).
- [x] Timestamped samples/events persisted in local SQLite; survive restart.
- [x] Reconnect with bounded backoff; gaps recorded as `telemetry.gap`.

## Hardware exit criteria (not yet met)

- [ ] A real Ender 3 V2 print is detected and monitored with Mainsail closed.
- [ ] Job events and samples survive a real Agent service restart.
- [ ] Actual object names/fields/units (heater `power`, fans) confirmed.

## Running against a printer

```
uv run stunsail-agent discover --config agent.yaml   # inspect objects and fields
uv run stunsail-agent run --config agent.yaml        # observe and persist
uv run stunsail-agent report --config agent.yaml     # jobs and sample counts
```

Use `deployment/installer/configs/agent-only.example.yaml` as the template
(optional `agent.agent_id` and `agent.sample_interval_seconds`, default 1.0).
Only one Moonraker instance per Agent is supported in this phase.
