# Phase 1 — Moonraker integration prototype

Status: **Complete — hardware validated 5 November 2026**

## Implemented (verified against mocks and a local WebSocket server)

- [x] Moonraker HTTP + WebSocket client (`packages/moonraker`).
- [x] Discovery of printer info and available objects; subscription limited to
  objects the printer exposes.
- [x] Heater, fan, `print_stats`, and `virtual_sdcard` capture (raw snapshots).
- [x] Job start/pause/resume/complete/cancel/error detection and restart
  reconciliation (ADR 0005).
- [x] Timestamped samples/events persisted in local SQLite; survive restart.
- [x] Reconnect with bounded backoff; gaps recorded as `telemetry.gap`.

## Hardware exit criteria (met)

- [x] A real print is detected and monitored (5 Nov 2026, Klipper
  v0.13.0-740, Moonraker v0.10.0-31; `Cube_PETG_7m44s.gcode`: one job,
  `completed`, 509 job samples). Mainsail closed: confirmed by the operator.
- [x] Job events and samples survive a real Agent restart (two restarts
  mid-print: still one job, `telemetry.gap` events recorded).
- [x] Object names/fields confirmed: `extruder.power` and `heater_bed.power`
  are 0-1 duty fractions (observed max 0.995 and 0.91); `fan.speed` and
  `heater_fan <name>.speed` are 0-1. Wattage conversion remains a Phase 2 task.
- Note: the test printer has a toolboard (`mcu orbitool`), not a stock Ender 3 V2.
  Confirm the hardware profile before Phase 2 heater/PSU assumptions.

## Running against a printer

```
uv run stunsail-agent discover --config agent.yaml   # inspect objects and fields
uv run stunsail-agent run --config agent.yaml        # observe and persist
uv run stunsail-agent report --config agent.yaml     # jobs and sample counts
```

Use `deployment/installer/configs/agent-only.example.yaml` as the template
(optional `agent.agent_id` and `agent.sample_interval_seconds`, default 1.0).
Only one Moonraker instance per Agent is supported in this phase.
